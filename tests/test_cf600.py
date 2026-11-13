"""CF600 input-event tests; all EPCs and devices here are synthetic."""
from collections import deque
from threading import Event
from types import SimpleNamespace
import errno
import io
import unittest
from unittest.mock import Mock, patch

from smartshop.hardware.cf600 import CF600Reader, EPCDecoder, ReaderError
from smartshop.hardware.product_reader import ProductReader, FakeReader, configured_adapter
from scripts import scan_products


def key(code, value=1, event_type=1):
    return SimpleNamespace(type=event_type, code=code, value=value)


def events(value):
    codes = {value: code for code, value in EPCDecoder.HEX_KEYS.items()}
    return [key(codes[char]) for char in value] + [key(15)]


class Device:
    def __init__(self):
        self.info = SimpleNamespace(vendor=0x0483, product=0x5750)
        self.name = 'CFUSB_HID By YLW28'
        self.batches = deque()
        self.grab = Mock()
        self.ungrab = Mock()
        self.close = Mock()
        self.consumed = Event()
        self.disconnect = False

    def read(self):
        if self.disconnect:
            raise OSError(errno.ENODEV, 'gone')
        if not self.batches:
            raise BlockingIOError()
        batch = self.batches.popleft()
        self.consumed.set()
        return batch

    def wait(self, readers, writes, errors, timeout):
        if self.batches or self.disconnect:
            return (readers, [], [])
        if timeout:
            Event().wait(min(timeout, 0.005))
        return ([], [], [])


def feed_batch(device, batch):
    # The worker reads this empty marker only after decoding the preceding batch.
    acknowledged = Event()
    original = device.read
    marker = []
    def read():
        result = original()
        if result is marker:
            acknowledged.set()
        return result
    device.read = read
    device.batches.extend([batch, marker])
    try:
        if not acknowledged.wait(1):
            raise AssertionError('Input worker did not finish the batch')
    finally:
        device.read = original


class DecoderTests(unittest.TestCase):
    def test_tab_records_and_ignored_events(self):
        decoder = EPCDecoder()
        batch = [key(42), key(2, 0), key(2, 2), key(4, event_type=4)]
        batch += events('0000ABCDEF12') + events('00BB')
        self.assertEqual([v for event in batch if (v := decoder.feed(event))], ['0000ABCDEF12', '00BB'])

    def test_invalid_oversized_odd_and_partial_records(self):
        for batch in (events('A'), events('A' * 26), [key(34)] + events('00AA'), [key(28)] + events('00AA')):
            decoder = EPCDecoder()
            self.assertFalse(any(decoder.feed(event) for event in batch))
            self.assertEqual([v for event in events('00BB') if (v := decoder.feed(event))], ['00BB'])
        decoder = EPCDecoder()
        decoder.feed(key(2))
        decoder.reset()
        self.assertIsNone(decoder.feed(key(15)))


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.device = Device()
        self.adapter = CF600Reader(device_factory=lambda path: self.device, wait=self.device.wait)
        self.addCleanup(self.adapter.stop)

    def finish_batch(self, batch):
        feed_batch(self.device, batch)

    def test_stale_input_multi_tag_and_rearm(self):
        self.device.batches.append(events('DEAD'))
        self.adapter.start()
        self.assertEqual(self.adapter.poll(), [])
        self.finish_batch(events('00AA') + events('00BB') + events('00CC') + events('00DD'))
        self.assertEqual(self.adapter.poll(), ['00AA', '00BB', '00CC', '00DD'])
        self.assertEqual(self.adapter.poll(), [])
        self.finish_batch([key(2)])
        self.adapter.stop()
        self.device.ungrab.assert_called_once()
        self.device.close.assert_called_once()
        self.adapter.start()
        self.finish_batch([key(15)] + events('00EE'))
        self.assertEqual(self.adapter.poll(), ['00EE'])

    def test_overflow_releases_device_and_reports_failure(self):
        self.adapter.capacity = 1
        self.adapter.start()
        self.device.batches.append(events('00AA') + events('00BB'))
        self.adapter._thread.join(1)
        self.assertFalse(self.adapter._thread.is_alive())
        self.device.close.assert_called_once()
        with self.assertRaisesRegex(ReaderError, 'overflow'):
            self.adapter.poll()

    def test_disconnect_and_syn_dropped(self):
        for disconnect in (False, True):
            self.adapter.start()
            self.device.disconnect = disconnect
            if not disconnect:
                self.device.batches.append([key(3, event_type=0)])
            self.adapter._thread.join(1)
            self.assertFalse(self.adapter._thread.is_alive())
            with self.assertRaises(ReaderError):
                self.adapter.poll()
            self.adapter.stop()
            self.device.disconnect = False

    def test_identity_permissions_missing_and_busy(self):
        self.device.info.vendor = 1
        with self.assertRaisesRegex(ReaderError, 'not the CF600'):
            self.adapter.start()
        self.device.grab.assert_not_called()
        self.device.close.assert_called_once()
        for error, message in ((PermissionError(), 'permission'), (FileNotFoundError(), 'unavailable'),
                               (OSError(errno.EBUSY, 'busy'), 'busy')):
            self.adapter.device_factory = Mock(side_effect=error)
            with self.assertRaisesRegex(ReaderError, message):
                self.adapter.start()

    def test_grab_failure_closes_without_ungrab(self):
        self.device.grab.side_effect = OSError(errno.EBUSY, 'busy')
        with self.assertRaisesRegex(ReaderError, 'busy'):
            self.adapter.start()
        self.device.close.assert_called_once()
        self.device.ungrab.assert_not_called()


class LifecycleTests(unittest.TestCase):
    def test_timer_expires_without_browser_poll_and_old_timer_is_harmless(self):
        adapter = Mock()
        timers = Mock()
        reader = ProductReader(adapter, timer_factory=timers)
        first = reader.arm('one', 'registration')
        callback = timers.call_args.args[1]
        self.assertEqual(timers.call_args.args[0], 60)
        callback(first['id'])
        self.assertIsNone(reader.operation)
        adapter.stop.assert_called_once()
        reader.arm('two', 'checkout')
        callback(first['id'])
        self.assertEqual(reader.operation['owner'], 'two')
        reader.stop()

    def test_reader_failure_preserves_actionable_error(self):
        adapter = Mock()
        adapter.poll.side_effect = ReaderError('CF600 input overflow; rearm the scan')
        reader = ProductReader(adapter, timer_factory=Mock())
        operation = reader.arm('one', 'checkout')
        with self.assertRaisesRegex(ValueError, 'overflow'):
            reader.poll('one', operation['id'])
        self.assertIsNone(reader.operation)
        adapter.stop.assert_called_once()

    def test_configuration_and_lazy_app_construction(self):
        self.assertIsInstance(configured_adapter({'FAKE_READERS_ENABLED': True}), FakeReader)
        for config in ({'PRODUCT_READER_BACKEND': 'unknown'},
                       {'PRODUCT_READER_BACKEND': 'cf600_hid', 'FAKE_READERS_ENABLED': True}):
            with self.assertRaises(ValueError):
                configured_adapter(config)
        from smartshop import create_app
        with patch('threading.Thread.start', side_effect=AssertionError('started')), \
             patch.object(CF600Reader, 'start', side_effect=AssertionError('opened')):
            app = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                              'PRODUCT_READER_BACKEND': 'cf600_hid', 'FAKE_READERS_ENABLED': False})
        self.assertIsInstance(app.extensions['smartshop'].reader.adapter, CF600Reader)

    def test_diagnostic_fake_and_hardware_cleanup(self):
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            scan_products.main(['--fake', '00aa', '00AA', '00BB'])
            self.assertEqual(output.getvalue(), '00AA\n00BB\n')
        with patch.object(scan_products, 'CF600SerialReader') as factory, \
             patch.object(scan_products, 'monotonic', side_effect=[0, 0, 2, 2]), \
             patch('sys.stdout', new_callable=io.StringIO):
            scan_products.main(['--hardware', '--seconds', '1'])
            factory.return_value.stop.assert_called_once()
        for argv in (['--hardware', '00AA'], ['--fake'], ['--hardware', '--seconds', 'nan']):
            with patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit):
                scan_products.main(argv)


class WorkflowTests(unittest.TestCase):
    def test_hid_registration_checkout_removal_cancel_and_reuse(self):
        from tests.test_phase3 import ShopTests
        from smartshop.models import Product, Purchase
        from smartshop.extensions import db
        fixture = ShopTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        device = Device()
        adapter = CF600Reader(device_factory=lambda path: device, wait=device.wait)
        fixture.runtime.reader.stop()
        fixture.runtime.reader = ProductReader(adapter)
        self.addCleanup(fixture.runtime.reader.stop)
        fixture.app.config['FAKE_READERS_ENABLED'] = False
        fixture.login('admin@example.com')
        self.assertEqual(fixture.post('/reader/product/start').status_code, 200)
        feed_batch(device, events(fixture.tags[0]))
        self.assertEqual(fixture.post('/reader/product/result').json['tags'], [fixture.tags[0]])
        fixture.post('/reader/product/cancel')
        self.assertIsNone(fixture.runtime.reader.operation)
        for expected_stock in (2, 1):
            path = fixture.new_cart()
            fixture.post(path, {'action': 'scan'})
            feed_batch(device, sum((events(tag) for tag in fixture.tags + fixture.tags[:1] + ['00AA']), []))
            response = fixture.post(path + '/poll')
            self.assertEqual(len(response.json['items']), 4)
            self.assertIn('Unknown product tag', response.json['messages'])
            self.assertEqual(response.json['total_cents'], 1100)
            fixture.post(path, {'action': 'remove', 'product_id': '1'})
            feed_batch(device, events(fixture.tags[0]))
            self.assertEqual(len(fixture.post(path + '/poll').json['items']), 3)
            fixture.post(path, {'action': 'restore', 'product_id': '1'})
            fixture.ready(path)
            self.assertIsNone(fixture.runtime.reader.operation)
            fixture.post(path + '/payment', {'outcome': 'success'})
            self.assertEqual(db.session.get(Product, 1).stock, expected_stock)
        self.assertEqual(Purchase.query.count(), 2)
        path = fixture.new_cart()
        fixture.post(path, {'action': 'scan'})
        fixture.post(path, {'action': 'cancel'})
        self.assertIsNone(fixture.runtime.reader.operation)
        self.assertEqual(device.close.call_count, 4)
