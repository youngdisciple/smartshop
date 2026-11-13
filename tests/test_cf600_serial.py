"""CF serial framing tests, including one recorded hardware packet."""
import errno
from queue import Queue, Empty
from threading import Event
import unittest
from unittest.mock import Mock
from smartshop.hardware.cf600 import ReaderError
from smartshop.hardware.cf600_serial import CFFrameDecoder, CF600SerialReader, crc16
from smartshop.hardware.product_reader import configured_adapter

# Captured on the attached CF600, not a seeded product mapping.
CAPTURE = bytes.fromhex('cf0000011200fc8601000ca0000000000000000000496562f4')
CAPTURE_EPC = 'A00000000000000000004965'


def packet(epc='00AA', *, command=b'\x00\x01', status=0):
    data = bytes.fromhex(epc)
    payload = bytes([status]) + b'\xfc\x86\x01\x00' + bytes([len(data)]) + data
    body = b'\xcf\x00' + command + bytes([len(payload)]) + payload
    return body + crc16(body)


class SerialDecoderTests(unittest.TestCase):
    def test_hardware_packet_and_crc(self):
        self.assertEqual(crc16(CAPTURE[:-2]), b'\x62\xf4')
        decoder = CFFrameDecoder()
        values = []
        for byte in b'\x00\x00' + CAPTURE:
            values.extend(decoder.feed(bytes([byte])))
        self.assertEqual(values, [CAPTURE_EPC])
        self.assertEqual(decoder.buffer, b'')

    def test_split_coalesced_frames_duplicates_and_hex_leading_zeroes(self):
        data = packet('0000ABCD') + packet('00BB') + packet('00BB')
        for split in range(len(data) + 1):
            decoder = CFFrameDecoder()
            self.assertEqual(decoder.feed(data[:split]) + decoder.feed(data[split:]),
                             ['0000ABCD', '00BB', '00BB'])

    def test_noise_corruption_and_false_incomplete_header_resync(self):
        corrupt = bytearray(packet())
        corrupt[-1] ^= 1
        decoder = CFFrameDecoder()
        self.assertEqual(decoder.feed(b'noise\xcf\x00\x00\x01\xff' + corrupt + packet('00CC')), ['00CC'])
        self.assertEqual(decoder.buffer, b'')
        decoder.feed(b'\xcf' * 10000)
        self.assertLessEqual(len(decoder.buffer), 261)
        self.assertEqual(decoder.feed(packet('00DD')), ['00DD'])

    def test_only_successful_inventory_with_consistent_epc_length_is_accepted(self):
        malformed = bytearray(packet())
        malformed[10] = 12
        malformed[-2:] = crc16(malformed[:-2])
        decoder = CFFrameDecoder()
        stream = (packet(status=0x12) + packet(command=b'\x00\x70') + malformed
                  + packet('AA' * 13) + packet(''))
        self.assertEqual(decoder.feed(stream), [])
        self.assertEqual(decoder.feed(packet()), ['00AA'])


class Port:
    def __init__(self):
        self.chunks = Queue()
        self.open = Mock()
        self.close = Mock()
        self.reset_input_buffer = Mock()

    @property
    def in_waiting(self):
        return 1

    def read(self, size):
        try:
            value = self.chunks.get(timeout=0.01)
        except Empty:
            return b''
        if isinstance(value, Exception):
            raise value
        if isinstance(value, Event):
            value.set()
            return b''
        return value

    def feed(self, data):
        done = Event()
        self.chunks.put(data)
        self.chunks.put(done)
        if not done.wait(1):
            raise AssertionError('Serial worker did not decode the chunk')


class SerialAdapterTests(unittest.TestCase):
    def setUp(self):
        self.port = Port()
        self.factory = Mock(return_value=self.port)
        self.adapter = CF600SerialReader(serial_factory=self.factory)
        self.addCleanup(self.adapter.stop)

    def test_start_read_stop_and_rearm_discard_partial_data(self):
        self.adapter.start()
        self.factory.assert_called_once_with(port=None, baudrate=57600, timeout=0.1, exclusive=True)
        self.assertFalse(self.port.dtr)
        self.assertFalse(self.port.rts)
        self.port.reset_input_buffer.assert_called_once()
        self.port.feed(CAPTURE + packet('00AA'))
        self.assertEqual(self.adapter.poll(), [CAPTURE_EPC, '00AA'])
        self.assertEqual(self.adapter.poll(), [])
        self.port.feed(packet()[:5])
        self.adapter.stop()
        self.port.close.assert_called_once()
        self.adapter.start()
        self.port.feed(packet('00BB'))
        self.assertEqual(self.adapter.poll(), ['00BB'])

    def test_disconnect_releases_and_reports_error(self):
        self.adapter.start()
        self.port.chunks.put(OSError(errno.ENODEV, 'removed'))
        self.adapter._thread.join(1)
        self.assertFalse(self.adapter._thread.is_alive())
        self.port.close.assert_called_once()
        with self.assertRaisesRegex(ReaderError, 'serial unavailable'):
            self.adapter.poll()

    def test_bounded_queue_overflow_releases_port(self):
        self.adapter.capacity = 1
        self.adapter.start()
        self.port.chunks.put(packet('00AA') + packet('00BB'))
        self.adapter._thread.join(1)
        self.port.close.assert_called_once()
        with self.assertRaisesRegex(ReaderError, 'overflow'):
            self.adapter.poll()

    def test_open_errors_and_busy_mapping(self):
        for error, message in ((PermissionError(errno.EACCES, 'denied'), 'dialout'),
                               (OSError(errno.EAGAIN, 'locked'), 'busy'),
                               (FileNotFoundError(), 'unavailable')):
            self.port.open.side_effect = error
            with self.assertRaisesRegex(ReaderError, message):
                self.adapter.start()
        self.assertEqual(self.port.close.call_count, 3)

    def test_serial_configuration_and_fake_conflict(self):
        adapter = configured_adapter({'PRODUCT_READER_BACKEND': 'cf600_serial',
                                      'CF600_SERIAL_DEVICE': '/test/reader', 'CF600_BAUDRATE': 115200})
        self.assertIsInstance(adapter, CF600SerialReader)
        self.assertEqual(adapter.path, '/test/reader')
        self.assertEqual(adapter.baudrate, 115200)
        with self.assertRaises(ValueError):
            configured_adapter({'PRODUCT_READER_BACKEND': 'cf600_serial', 'FAKE_READERS_ENABLED': True})


class SerialWorkflowTests(unittest.TestCase):
    def test_serial_registration_and_checkout_reuse(self):
        from tests.test_phase3 import ShopTests
        from smartshop.hardware.product_reader import ProductReader
        from smartshop.models import Product, Purchase
        from smartshop.extensions import db
        fixture = ShopTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        port = Port()
        adapter = CF600SerialReader(serial_factory=Mock(return_value=port))
        fixture.runtime.reader.stop()
        fixture.runtime.reader = ProductReader(adapter)
        self.addCleanup(fixture.runtime.reader.stop)
        fixture.app.config['FAKE_READERS_ENABLED'] = False
        fixture.login('admin@example.com')
        self.assertEqual(fixture.post('/reader/product/start').status_code, 200)
        port.feed(packet(fixture.tags[0]))
        self.assertEqual(fixture.post('/reader/product/result').json['tags'], [fixture.tags[0]])
        fixture.post('/reader/product/cancel')
        for stock in (2, 1):
            path = fixture.new_cart()
            fixture.post(path, {'action': 'scan'})
            port.feed(b''.join(packet(tag) for tag in fixture.tags + fixture.tags[:1]))
            response = fixture.post(path + '/poll')
            self.assertEqual(len(response.json['items']), 4)
            self.assertEqual(response.json['total_cents'], 1100)
            fixture.post(path, {'action': 'remove', 'product_id': '1'})
            port.feed(packet(fixture.tags[0]))
            self.assertEqual(len(fixture.post(path + '/poll').json['items']), 3)
            fixture.post(path, {'action': 'restore', 'product_id': '1'})
            fixture.ready(path)
            self.assertIsNone(fixture.runtime.reader.operation)
            fixture.post(path + '/payment', {'outcome': 'success'})
            self.assertEqual(db.session.get(Product, 1).stock, stock)
        self.assertEqual(Purchase.query.count(), 2)
