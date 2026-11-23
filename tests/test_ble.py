"""Minew frame decoding, bounded radio scans and administrator BLE workflows."""
from copy import deepcopy
import json
from threading import Event
from datetime import datetime, timezone
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from smartshop import create_app
from smartshop.extensions import db
from smartshop.models import BLESensor, Customer
from smartshop.presentation.ble import receipt, sensor_view
from smartshop.routes.ble import live_payload
from smartshop.services.ble import BLEService, MINEW_SERVICE, decode_minew
from smartshop.services.migrations import migrate


ADDRESS = 'AC:23:3F:AA:46:DF'
MAC_BYTES = bytes.fromhex('df46aa3f23ac')


def frame(kind, payload=b''):
    return bytes([0xa1, kind, 90]) + payload + MAC_BYTES


def device_record():
    return {'address': ADDRESS, 'name': 'MSP01', 'rssi': -45,
            'last_seen': '2026-11-23T15:00:00+00:00', 'frames': {},
            'measurements': {'temperature': {'value': 21.5, 'received_at': '2026-11-23T15:00:00+00:00'}}}


class BLEPresentationTests(unittest.TestCase):
    def test_light_bar_distinguishes_missing_dim_and_bright_with_a_fixed_cutoff(self):
        record = device_record()
        app = create_app({'BLE_LIGHT_BRIGHT_PS': 300, 'BLE_LIGHT_BRIGHT_LUX': 100})
        with app.app_context():
            for value, state in ((None, 'unknown'), (0, 'dim'), (299, 'dim'), (300, 'bright'), (900, 'bright')):
                record['measurements']['light'] = {'value': value, 'received_at': record['last_seen']}
                view = sensor_view(SimpleNamespace(**record))
                meter = view['readings'][2]['light_meter']
                self.assertEqual(meter['state'], state)
                self.assertEqual(meter['maximum'], 600)
                self.assertTrue(0 <= meter['percent'] <= 100)
                if value == 0:
                    self.assertEqual(meter['percent'], 0)
                    self.assertEqual(meter['label'], 'Dim')
                elif value == 300:
                    self.assertEqual(meter['percent'], 50)
                elif value == 900:
                    self.assertEqual(meter['percent'], 100)
                    self.assertEqual(view['readings'][2]['display'], '900')
            # Lux uses its own cutoff, not the raw PS threshold.
            record['measurements']['illuminance'] = {'value': 100, 'received_at': record['last_seen']}
            meter = sensor_view(SimpleNamespace(**record))['readings'][2]['light_meter']
            self.assertEqual(meter['state'], 'bright')
            self.assertEqual(meter['maximum_label'], '200 lux')

    def test_individual_readings_age_independently_of_the_sensor(self):
        record = device_record()
        record['last_seen'] = '2026-11-23T16:00:00+00:00'
        view = sensor_view(SimpleNamespace(**record), datetime(2026, 11, 23, 16, 0, 5, tzinfo=timezone.utc))
        self.assertEqual(view['receipt']['state'], 'recent')
        self.assertEqual(view['receipt']['relative'], 'Just now')
        self.assertEqual(view['readings'][0]['receipt']['state'], 'older')
        self.assertEqual(view['readings'][0]['receipt']['relative'], '1 hour ago')
        self.assertEqual(view['readings'][1]['display'], '—')
        self.assertEqual(view['readings'][1]['receipt']['state'], 'missing')
        self.assertTrue(view['missing'])

    def test_zero_false_and_light_units_are_not_confused_with_missing_data(self):
        record = device_record()
        for key, value in [('temperature', 0), ('humidity', 0), ('light', 0), ('motion', False), ('battery', 0)]:
            record['measurements'][key] = {'value': value, 'received_at': record['last_seen']}
        view = sensor_view(SimpleNamespace(**record))
        self.assertFalse(view['missing'])
        self.assertEqual([reading['display'] for reading in view['readings']], ['0', '0.00', '0', 'No motion detected'])
        self.assertEqual(view['readings'][2]['unit'], 'PS')
        self.assertEqual(view['battery']['display'], '0')
        record['measurements']['illuminance'] = {'value': 0, 'received_at': record['last_seen']}
        view = sensor_view(SimpleNamespace(**record))
        self.assertEqual(view['readings'][2]['unit'], 'lux')
        self.assertEqual(view['secondary_light']['display'], '0')

    def test_receipt_handles_missing_invalid_and_old_naive_timestamps(self):
        now = datetime(2026, 11, 23, 15, 1, tzinfo=timezone.utc)
        for invalid in (None, '', 'not a date'):
            self.assertEqual(receipt(invalid, now)['state'], 'missing')
        self.assertEqual(receipt('2026-11-23T15:00:00', now)['relative'], '1 minute ago')
        self.assertEqual(receipt('2026-11-23T15:00:00', now)['absolute'], '2026-11-23 15:00:00 UTC')


class MinewDecoderTests(unittest.TestCase):
    def test_ht_fixed_point_signed_temperature_and_humidity(self):
        result = decode_minew(frame(0x01, bytes.fromhex('fe804080')))
        self.assertEqual(result, {'temperature': -1.5, 'humidity': 64.5, 'battery': 90})

    def test_motion_light_and_lux_are_distinct_and_zero_is_a_reading(self):
        self.assertTrue(decode_minew(frame(0x11, b'\x00\x01'))['motion'])
        self.assertFalse(decode_minew(frame(0x11, b'\x00\x02'))['motion'])
        self.assertEqual(decode_minew(frame(0x19, b'\x00\xd6'))['light'], 214)
        self.assertNotIn('illuminance', decode_minew(frame(0x19, b'\x00\xd6')))
        self.assertEqual(decode_minew(frame(0x05, b'\x01\x00'))['illuminance'], 256)
        self.assertEqual(decode_minew(frame(0x19, b'\x00\x00'))['light'], 0)

    def test_bad_frames_and_unknown_versions_do_not_invent_values(self):
        for data in (b'', b'\xa1', b'\xa1\x01', frame(0xff), frame(0x01),
                     frame(0x11, b'\x01'), b'\xa2' + frame(0x11, b'\x00\x01')[1:]):
            with self.subTest(data=data):
                self.assertEqual(decode_minew(data), {})
        self.assertNotIn('humidity', decode_minew(frame(0x01, bytes.fromhex('15007fff'))))


class BLEScanTests(unittest.TestCase):
    def test_live_subscribers_share_one_receiver_and_last_viewer_stops_it(self):
        ready, stopped = Event(), Event()
        instances = []

        class Scanner:
            def __init__(self, detection_callback, **kwargs):
                self.callback = detection_callback
                instances.append(self)

            async def start(self):
                self.callback(SimpleNamespace(address=ADDRESS, name='MSP01'),
                              SimpleNamespace(local_name=None, rssi=-45,
                                              service_data={MINEW_SERVICE: frame(0x01, bytes.fromhex('15804080'))}))
                ready.set()

            async def stop(self):
                stopped.set()

        service = BLEService({}, scanner_factory=Scanner)
        self.addCleanup(service.stop)
        first = service.subscribe()
        self.assertTrue(ready.wait(2))
        second = service.subscribe()
        self.assertEqual(len(instances), 1)
        snapshot = service.live_snapshot()
        self.assertEqual(snapshot['devices'][ADDRESS]['measurements']['temperature']['value'], 21.5)
        # Manual discovery shares the live radio instead of competing for it.
        self.assertIn(ADDRESS, service.scan())
        service.unsubscribe(first)
        self.assertFalse(stopped.is_set())
        service.unsubscribe(second)
        self.assertTrue(stopped.is_set())
        self.assertFalse(service._live_thread.is_alive())

    def test_live_failure_releases_radio_and_allows_retry(self):
        failed, cleaned = Event(), Event()

        class Scanner:
            def __init__(self, **kwargs):
                pass

            async def start(self):
                failed.set()
                raise RuntimeError('Bluetooth powered off')

            async def stop(self):
                cleaned.set()

        service = BLEService({}, scanner_factory=Scanner)
        self.addCleanup(service.stop)
        token = service.subscribe()
        self.assertTrue(failed.wait(2))
        service._live_thread.join(timeout=2)
        self.assertTrue(cleaned.is_set())
        self.assertEqual(service.live_snapshot()['state'], 'error')
        self.assertIn('powered off', service.live_snapshot()['error'])
        service.unsubscribe(token)
        retry = service.subscribe()
        service._live_thread.join(timeout=2)
        self.assertEqual(service.live_snapshot()['state'], 'error')
        service.unsubscribe(retry)

    def test_scan_aggregates_rotating_frames_and_releases_radio(self):
        lifecycle = []

        class Scanner:
            def __init__(self, detection_callback, **kwargs):
                self.callback = detection_callback

            async def __aenter__(self):
                lifecycle.append('started')
                device = SimpleNamespace(address=ADDRESS.lower(), name=None)
                for data in (frame(0x08) + b'MSP01', frame(0x01, bytes.fromhex('15804080')),
                             frame(0x19, b'\x00\xd6'), frame(0x11, b'\x00\x01')):
                    self.callback(device, SimpleNamespace(local_name=None, rssi=-45,
                                                         service_data={MINEW_SERVICE: data}))
                self.callback(SimpleNamespace(address='00:11:22:33:44:55', name='Other device'),
                              SimpleNamespace(local_name=None, rssi=-50, service_data={}))

            async def __aexit__(self, *args):
                lifecycle.append('stopped')

        service = BLEService({}, scanner_factory=Scanner)
        with patch('smartshop.services.ble.asyncio.sleep', new_callable=AsyncMock):
            devices = service.scan()
        self.assertEqual(lifecycle, ['started', 'stopped'])
        self.assertEqual(list(devices), [ADDRESS])
        result = devices[ADDRESS]
        self.assertEqual(result['name'], 'MSP01')
        self.assertEqual(result['measurements']['temperature']['value'], 21.5)
        self.assertEqual(result['measurements']['light']['value'], 214)
        self.assertTrue(result['measurements']['motion']['value'])
        self.assertEqual(len(result['frames']), 4)
        devices.clear()
        self.assertIn(ADDRESS, service.discovered())
        service._scanned_at = monotonic() - 121
        self.assertEqual(service.discovered(), {})

    def test_scan_error_and_concurrent_scan_are_recoverable(self):
        def unavailable(**kwargs):
            raise RuntimeError('Bluetooth adapter is powered off')

        service = BLEService({}, scanner_factory=unavailable)
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, 'powered off'):
                service.scan()
        service._scan_lock.acquire()
        try:
            with self.assertRaisesRegex(ValueError, 'already in progress'):
                service.scan()
        finally:
            service._scan_lock.release()


class BLEAdminTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test',
                               'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        self.context = self.app.app_context()
        self.context.push()
        migrate()
        for email, admin in (('admin@example.com', True), ('member@example.com', False)):
            customer = Customer(email, 'unused', 'Test', '123 Main', '')
            customer.is_admin = admin
            db.session.add(customer)
        db.session.commit()
        self.client = self.app.test_client()
        self.client.get('/auth/login')
        self.service = self.app.extensions['smartshop'].ble

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.service.stop()
        self.context.pop()

    def login_as(self, email):
        with self.client.session_transaction() as session:
            session['email'] = email

    def post(self, action, **data):
        with self.client.session_transaction() as session:
            token = session['csrf']
        return self.client.post('/admin/ble', data={'csrf_token': token, 'action': action, **data},
                                follow_redirects=True)

    def discover(self, record=None):
        devices = {ADDRESS: record or device_record()}
        self.service._devices = deepcopy(devices)
        self.service._scanned_at = monotonic()
        return devices

    def test_admin_only_navigation_and_every_mutation_require_authorization(self):
        with patch.object(self.service, 'scan') as scan:
            self.assertNotIn(b'href="/admin/ble"', self.client.get('/checkout').data)
            self.assertEqual(self.client.get('/admin/ble').location, '/auth/login')
            for action in ('scan', 'refresh', 'connect', 'disconnect'):
                self.assertIn(b'Sign in', self.post(action, address=ADDRESS).data)
            self.login_as('member@example.com')
            self.assertEqual(self.client.get('/admin/ble').status_code, 403)
            for action in ('scan', 'refresh', 'connect', 'disconnect'):
                self.assertEqual(self.post(action, address=ADDRESS).status_code, 403)
            self.login_as('admin@example.com')
            self.assertEqual(self.client.post('/admin/ble', data={'action': 'scan'}).status_code, 400)
            page = self.client.get('/admin/ble')
            self.assertIn(b'href="/admin/ble" class="active"', page.data)
            self.assertNotIn(b'http-equiv="refresh"', page.data)
            self.assertIn(b'/static/ble.js', page.data)
            scan.assert_not_called()

    def test_connect_refresh_retains_independent_readings_and_disconnect(self):
        self.login_as('admin@example.com')
        devices = self.discover()
        with patch.object(self.service, 'scan', return_value=devices) as scan:
            self.assertIn(b'MSP01', self.post('scan').data)
            scan.assert_called_once()
        self.assertIn(b'21.5', self.post('connect', address=ADDRESS.lower()).data)
        db.session.remove()
        sensor = db.session.get(BLESensor, ADDRESS)
        self.assertEqual(sensor.name, 'MSP01')
        self.assertEqual(sensor.measurements['temperature']['value'], 21.5)
        new = device_record()
        new['last_seen'] = '2026-11-23T15:01:00+00:00'
        new['measurements'] = {'motion': {'value': False, 'received_at': new['last_seen']}}
        with patch.object(self.service, 'scan', return_value={ADDRESS: new}):
            page = self.post('refresh')
        self.assertIn(b'No motion detected', page.data)
        self.assertEqual(sensor.measurements['temperature']['received_at'], '2026-11-23T15:00:00+00:00')
        self.assertEqual(sensor.last_seen, new['last_seen'])
        with patch.object(self.service, 'scan', return_value={}):
            page = self.post('refresh')
        self.assertIn(b'No Minew sensors found', page.data)
        self.assertEqual(sensor.last_seen, new['last_seen'])
        self.post('disconnect', address=ADDRESS)
        self.assertIsNone(db.session.get(BLESensor, ADDRESS))

    def test_unscanned_expired_invalid_addresses_and_duplicate_connect(self):
        self.login_as('admin@example.com')
        self.assertIn(b'Scan again', self.post('connect', address=ADDRESS).data)
        self.assertIn(b'Invalid Bluetooth address', self.post('connect', address='bad').data)
        self.discover()
        self.service._scanned_at -= 121
        self.assertIn(b'Scan again', self.post('connect', address=ADDRESS).data)
        self.discover()
        for _ in range(2):
            self.post('connect', address=ADDRESS)
        self.assertEqual(BLESensor.query.count(), 1)

    def test_hardware_errors_render_without_losing_saved_sensor(self):
        self.login_as('admin@example.com')
        self.discover()
        self.post('connect', address=ADDRESS)
        with patch.object(self.service, 'scan', side_effect=ValueError('Bluetooth powered off')):
            self.assertIn(b'Bluetooth powered off', self.post('refresh').data)
        self.assertEqual(BLESensor.query.count(), 1)

    def test_connection_lands_on_readings_and_keeps_setup_and_settings_secondary(self):
        self.login_as('admin@example.com')
        self.discover()
        with self.client.session_transaction() as session:
            token = session['csrf']
        response = self.client.post('/admin/ble', data={'action': 'connect', 'address': ADDRESS, 'csrf_token': token})
        self.assertEqual(response.location, '/admin/ble#sensor-AC233FAA46DF')
        page = self.client.get(response.location).get_data(as_text=True)
        self.assertLess(page.index('class="panel ble-sensor"'), page.index('id="ble-discovery"'))
        self.assertEqual(page.count('<article class="ble-metric '), 4)
        self.assertIn('<details class="ble-device-details">', page)
        self.assertIn('Waiting for more readings.', page)
        self.assertIn('Older reading', page)

    def test_device_names_are_escaped_and_french_labels_are_available(self):
        self.login_as('admin@example.com')
        record = device_record()
        record['name'] = '<script>alert(1)</script>'
        self.discover(record)
        self.assertIn(b'&lt;script&gt;', self.client.get('/admin/ble').data)
        with self.client.session_transaction() as session:
            session['language'] = 'fr'
        self.assertIn('Rechercher des capteurs'.encode(), self.client.get('/admin/ble').data)

    def test_live_stream_authorization_and_no_radio_without_saved_sensors(self):
        with patch.object(self.service, 'subscribe') as subscribe:
            self.assertEqual(self.client.get('/admin/ble/events').location, '/auth/login')
            self.login_as('member@example.com')
            self.assertEqual(self.client.get('/admin/ble/events').status_code, 403)
            self.login_as('admin@example.com')
            self.assertEqual(self.client.get('/admin/ble/events').status_code, 204)
            subscribe.assert_not_called()

    def test_stream_pushes_new_values_persists_them_and_releases_subscription(self):
        self.login_as('admin@example.com')
        self.discover()
        self.post('connect', address=ADDRESS)
        record = device_record()
        record['last_seen'] = '2026-11-23T16:00:00+00:00'
        record['measurements']['temperature'] = {'value': 25, 'received_at': record['last_seen']}
        record['measurements']['motion'] = {'value': False, 'received_at': record['last_seen']}
        snapshot = {'state': 'receiving', 'error': None, 'devices': {ADDRESS: record}, 'version': 1}
        with patch.object(self.service, 'subscribe', return_value='viewer') as subscribe, \
                patch.object(self.service, 'unsubscribe') as unsubscribe, \
                patch.object(self.service, 'live_snapshot', return_value=snapshot), \
                patch('smartshop.routes.ble.sleep'):
            response = self.client.get('/admin/ble/events', buffered=False)
            self.assertEqual(response.mimetype, 'text/event-stream')
            self.assertEqual(response.headers['X-Accel-Buffering'], 'no')
            iterator = iter(response.response)
            self.assertIn(b'retry:', next(iterator))
            data = json.loads(next(iterator).decode().split('data: ', 1)[1])
            self.assertEqual(data['state'], 'receiving')
            self.assertEqual(data['sensors'][0]['readings'][0]['display'], '25')
            self.assertEqual(data['sensors'][0]['readings'][3]['display'], 'No motion detected')
            self.assertEqual(db.session.get(BLESensor, ADDRESS).measurements['temperature']['value'], 25)
            self.assertIn(b'heartbeat', next(iterator))
            snapshot['version'] = 2
            record['measurements']['temperature']['value'] = 26
            data = json.loads(next(iterator).decode().split('data: ', 1)[1])
            self.assertEqual(data['sensors'][0]['readings'][0]['display'], '26')
            response.close()
            subscribe.assert_called_once()
            unsubscribe.assert_called_once_with('viewer')

    def test_older_live_snapshot_cannot_overwrite_newer_persisted_readings(self):
        self.login_as('admin@example.com')
        newer = device_record()
        newer['last_seen'] = '2026-11-23T16:00:00+00:00'
        newer['measurements']['temperature'] = {'value': 30, 'received_at': newer['last_seen']}
        self.discover(newer)
        self.post('connect', address=ADDRESS)
        snapshot = {'state': 'receiving', 'error': None, 'devices': {ADDRESS: device_record()}, 'version': 1}
        with self.app.test_request_context('/admin/ble/events'), \
                patch.object(self.service, 'live_snapshot', return_value=snapshot):
            payload, _ = live_payload(self.service)
        self.assertEqual(payload['sensors'][0]['readings'][0]['display'], '30')
