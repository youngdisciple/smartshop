"""Shared live BLE reception and on-demand discovery and Minew BeaconPlus advertisement decoding.

Frame reference: https://github.com/reelyactive/advlib-ble-services/blob/master/lib/minew.js
The MSP01 broadcasts sensor data; monitoring does not require a GATT pairing.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import re
from threading import Event, Lock, RLock, Thread
from time import monotonic
from uuid import uuid4


MINEW_SERVICE = '0000ffe1-0000-1000-8000-00805f9b34fb'


def normalize_address(address):
    if not isinstance(address, str) or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', address):
        raise ValueError('Invalid Bluetooth address')
    return address.upper()


def decode_minew(data):
    """Decode supported A1 frames, excluding the service UUID itself.

    HT uses signed big-endian 8.8 values. PS is a photosensitive level, not
    calibrated lux. A light-lux frame, when available, is reported separately.
    Unknown, truncated and out-of-range frames never become sensor readings.
    """
    if len(data) < 3 or data[0] != 0xA1:
        return {}
    kind = data[1]
    lengths = {0x01: 13, 0x05: 11, 0x11: 11, 0x19: 11}
    if kind == 0x08 and len(data) >= 9:
        return {'battery': data[2]} if data[2] <= 100 else {}
    if kind not in lengths or len(data) != lengths[kind]:
        return {}
    readings = {'battery': data[2]} if data[2] <= 100 else {}
    if kind == 0x01:
        temperature = int.from_bytes(data[3:5], 'big', signed=True) / 256
        humidity = int.from_bytes(data[5:7], 'big', signed=True) / 256
        if -100 <= temperature <= 150 and 0 <= humidity <= 100:
            readings.update(temperature=round(temperature, 2), humidity=round(humidity, 2))
    elif kind == 0x11:
        readings['motion'] = bool(int.from_bytes(data[3:5], 'big') & 1)
    elif kind == 0x05:
        readings['illuminance'] = int.from_bytes(data[3:5], 'big')
    elif kind == 0x19:
        readings['light'] = int.from_bytes(data[3:5], 'big')
    return readings


class BLEService:
    """Share one radio listener across visible pages and armed motion monitors."""

    def __init__(self, config, *, scanner_factory=None, alert_sender=None, dispatch=None, clock=monotonic):
        self.seconds = max(1, min(30, float(config.get('BLE_SCAN_SECONDS', 8))))
        self.adapter = config.get('BLE_ADAPTER', 'hci0')
        self.scanner_factory = scanner_factory
        self._alert_sender = alert_sender
        self._dispatch = dispatch
        self._clock = clock
        self.alert_cooldown = max(0, float(config.get('BLE_MOTION_ALERT_COOLDOWN', 60)))
        self._scan_lock = Lock()
        self._state_lock = Lock()
        self._devices = {}
        self._connections = {}
        self._scanned_at = float('-inf')
        self._live_lock = RLock()
        self.data_lock = RLock()
        self._live_thread = None
        self._live_stop = Event()
        self._subscribers = set()
        self._live_state = 'idle'
        self._live_error = None
        self._version = 0

    def discovered(self):
        with self._state_lock:
            if monotonic() - self._scanned_at > 120:
                return {}
            return deepcopy(self._devices)

    def connected(self):
        with self._state_lock:
            return {address: {key: deepcopy(value) for key, value in sensor.items() if not key.startswith('_')}
                    for address, sensor in self._connections.items()}

    @property
    def email_configured(self):
        return bool(self._alert_sender and self._alert_sender.configured)

    def connect(self, address):
        address = normalize_address(address)
        device = self.discovered().get(address)
        if device is None:
            raise ValueError('Scan again before connecting this sensor')
        with self._state_lock:
            self._connections.setdefault(address, {
                'address': address, 'name': device['name'], 'motion_enabled': False,
                'alert_recipient': None, 'alert_status': 'off', 'last_alert_at': None,
                '_generation': uuid4().hex, '_motion_state': None,
                '_last_alert_clock': float('-inf'), '_subscription': None,
            })
            self._version += 1

    def disconnect(self, address):
        address = normalize_address(address)
        with self._live_lock:
            with self._state_lock:
                sensor = self._connections.pop(address, None)
                self._version += 1
            if sensor and sensor.get('_subscription'):
                self.unsubscribe(sensor['_subscription'])

    def set_motion_monitoring(self, address, enabled, recipient=None):
        address = normalize_address(address)
        with self._live_lock:
            with self._state_lock:
                sensor = self._connections.get(address)
                if not sensor:
                    raise ValueError('Connect the sensor first')
                if sensor['motion_enabled'] == enabled and (not enabled or sensor['alert_recipient'] == recipient):
                    return
                if enabled and (not self.email_configured or not recipient):
                    raise ValueError('Configure Gmail or Resend before enabling motion email alerts')
                old_subscription = sensor.get('_subscription')
                sensor.update(motion_enabled=enabled, alert_recipient=recipient if enabled else None,
                              alert_status='armed' if enabled else 'off', _generation=uuid4().hex)
                sensor['_motion_state'] = self._devices.get(address, {}).get('measurements', {}).get('motion', {}).get('value')
                sensor['_last_alert_clock'] = float('-inf')
                self._version += 1
            if enabled and not old_subscription:
                try:
                    subscription = self.subscribe()
                except Exception:
                    with self._state_lock:
                        sensor.update(motion_enabled=False, alert_recipient=None, alert_status='failed')
                        self._version += 1
                    raise
                with self._state_lock:
                    sensor['_subscription'] = subscription
            elif not enabled and old_subscription:
                with self._state_lock:
                    sensor['_subscription'] = None
                self.unsubscribe(old_subscription)

    def _handle_motion(self, address, detected, received_at):
        with self._state_lock:
            sensor = self._connections.get(address)
            if not sensor or not sensor['motion_enabled']:
                return
            previous, sensor['_motion_state'] = sensor['_motion_state'], detected
            if not detected or previous is True or self._clock() - sensor['_last_alert_clock'] < self.alert_cooldown:
                return
            sensor['_last_alert_clock'] = self._clock()
            sensor['alert_status'] = 'sending'
            self._version += 1
            alert = dict(id=uuid4().hex, address=address, name=sensor['name'],
                         recipient=sensor['alert_recipient'], received_at=received_at,
                         generation=sensor['_generation'])
        try:
            if not self._dispatch:
                raise RuntimeError('Email worker is unavailable')
            self._dispatch(self._send_motion_alert, alert)
        except Exception:
            self._finish_motion_alert(alert, False)

    def _send_motion_alert(self, alert):
        with self._state_lock:
            sensor = self._connections.get(alert['address'])
            if not sensor or not sensor['motion_enabled'] or sensor['_generation'] != alert['generation']:
                return
        try:
            success = self._alert_sender.send(alert)
        except Exception:
            success = False
        self._finish_motion_alert(alert, success)

    def _finish_motion_alert(self, alert, success):
        with self._state_lock:
            sensor = self._connections.get(alert['address'])
            if sensor and sensor['_generation'] == alert['generation'] and sensor['motion_enabled']:
                sensor['alert_status'] = 'sent' if success else 'failed'
                if success:
                    sensor['last_alert_at'] = alert['received_at']
                self._version += 1

    def _record(self, devices, device, advertisement):
        try:
            address = normalize_address(device.address)
        except ValueError:
            return False
        data = advertisement.service_data.get(MINEW_SERVICE, b'')
        name = advertisement.local_name or device.name or ''
        if not (data[:1] == b'\xa1' or 'MSP01' in name.upper()):
            return False
        if address not in devices and len(devices) >= 128:
            return False
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        record = devices.setdefault(address, {
            'address': address, 'name': 'Minew sensor', 'measurements': {}, 'frames': {},
        })
        if data[:2] == b'\xa1\x08' and len(data) > 9:
            name = data[9:].decode('utf-8', errors='replace').rstrip('\x00') or name
        if name:
            record['name'] = name[:100]
        record.update(rssi=advertisement.rssi, last_seen=now)
        if data:
            record['frames'][data[:2].hex()] = data[:64].hex()
        for key, value in decode_minew(data).items():
            record['measurements'][key] = {'value': value, 'received_at': now}
        return True

    def _factory(self):
        if self.scanner_factory is not None:
            return self.scanner_factory
        try:
            from bleak import BleakScanner
        except ImportError:
            raise ValueError('Install bleak in the Python environment running SmartShop') from None
        return BleakScanner

    async def _collect(self, scanner_factory):
        devices = {}
        async with scanner_factory(detection_callback=lambda device, adv: self._record(devices, device, adv),
                                   bluez={'adapter': self.adapter}):
            await asyncio.sleep(self.seconds)
        return devices

    def _set_state(self, state, error=None):
        with self._state_lock:
            self._live_state, self._live_error = state, error
            self._version += 1

    def live_snapshot(self):
        with self._state_lock:
            return {'state': self._live_state, 'error': self._live_error,
                    'version': self._version, 'devices': deepcopy(self._devices)}

    async def _listen(self, stop):
        def detected(device, advertisement):
            with self._state_lock:
                if not self._record(self._devices, device, advertisement):
                    return
                self._scanned_at = monotonic()
                self._version += 1
            data = advertisement.service_data.get(MINEW_SERVICE, b'')
            if data[:2] == b'\xa1\x11':
                motion = decode_minew(data).get('motion')
                if motion is not None:
                    self._handle_motion(device.address.upper(), motion,
                                        datetime.now(timezone.utc).isoformat(timespec='seconds'))

        scanner = self._factory()(detection_callback=detected, bluez={'adapter': self.adapter})
        try:
            await asyncio.wait_for(scanner.start(), timeout=10)
            self._set_state('receiving')
            while not stop.is_set():
                await asyncio.sleep(0.1)
        finally:
            await asyncio.wait_for(scanner.stop(), timeout=5)

    def _run_live(self, stop):
        acquired = False
        try:
            while not stop.is_set():
                acquired = self._scan_lock.acquire(timeout=0.1)
                if acquired:
                    break
            if acquired and not stop.is_set():
                while not stop.is_set():
                    try:
                        self._set_state('starting')
                        asyncio.run(self._listen(stop))
                        break
                    except Exception as error:
                        self._set_state('error', str(error))
                        with self._state_lock:
                            armed = any(sensor['motion_enabled'] for sensor in self._connections.values())
                        if not armed or stop.wait(5):
                            raise
        except Exception as error:
            self._set_state('error', str(error))
        else:
            self._set_state('idle')
        finally:
            if acquired:
                self._scan_lock.release()

    def subscribe(self):
        with self._live_lock:
            if self._live_thread and self._live_thread.is_alive() and self._live_stop.is_set():
                self._live_thread.join(timeout=16)
                if self._live_thread.is_alive():
                    raise ValueError('BLE receiver is still stopping. Try again shortly.')
            token = uuid4().hex
            if not self._live_thread or not self._live_thread.is_alive():
                self._live_stop = Event()
                self._set_state('starting')
                self._live_thread = Thread(target=self._run_live, args=(self._live_stop,),
                                           name='ble-live', daemon=True)
                self._live_thread.start()
            self._subscribers.add(token)
            return token

    def unsubscribe(self, token):
        with self._live_lock:
            self._subscribers.discard(token)
            if not self._subscribers:
                self._stop_live()

    def _stop_live(self):
        self._live_stop.set()
        if self._live_thread:
            self._live_thread.join(timeout=16)
            if self._live_thread.is_alive():
                raise ValueError('BLE receiver could not be stopped')

    def stop(self):
        with self._live_lock:
            with self._state_lock:
                for sensor in self._connections.values():
                    sensor['motion_enabled'] = False
                    sensor['_generation'] = uuid4().hex
            self._subscribers.clear()
            self._stop_live()
            with self._state_lock:
                self._devices.clear()
                self._connections.clear()
                self._scanned_at = float('-inf')
                self._version += 1

    def _store_scan(self, devices):
        # Preserve independently advertised frames in RAM across scan windows.
        with self._state_lock:
            for address, incoming in devices.items():
                if address not in self._devices and len(self._devices) >= 128:
                    oldest = min(self._devices, key=lambda key: self._devices[key].get('last_seen', ''))
                    del self._devices[oldest]
                previous = self._devices.get(address, {})
                device = deepcopy(incoming)
                measurements = deepcopy(previous.get('measurements', {}))
                for key, reading in device['measurements'].items():
                    if (reading.get('received_at') or '') >= (measurements.get(key, {}).get('received_at') or ''):
                        measurements[key] = reading
                device['measurements'] = measurements
                device['frames'] = {**previous.get('frames', {}), **device.get('frames', {})}
                if previous.get('last_seen', '') > device['last_seen']:
                    device['last_seen'], device['rssi'] = previous['last_seen'], previous['rssi']
                self._devices[address] = device
            self._scanned_at = monotonic()
            self._version += 1

    def scan(self):
        # Discovery reuses the active listener instead of starting a second radio scan.
        if self._live_thread and self._live_thread.is_alive():
            snapshot = self.live_snapshot()
            if snapshot['error']:
                raise ValueError(snapshot['error'])
            if snapshot['state'] == 'starting':
                raise ValueError('BLE live receiver is starting. Try again shortly.')
            return self.discovered()
        if not self._scan_lock.acquire(blocking=False):
            raise ValueError('BLE scan already in progress')
        try:
            factory = self._factory()
            try:
                devices = asyncio.run(asyncio.wait_for(self._collect(factory), timeout=self.seconds + 10))
            except Exception as error:
                raise ValueError('BLE scan failed. Check Bluetooth power, adapter and permissions: ' + str(error)) from error
            self._store_scan(devices)
            return devices
        finally:
            self._scan_lock.release()
