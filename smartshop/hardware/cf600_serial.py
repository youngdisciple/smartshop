"""Passive CF600 CDC-COM inventory, validated against captured CF frames.

Frame/CRC reference: https://electron.id/protocol/el-uhf-rc4-protocol/
The attached reader emits inventory frames continuously; no commands or reader
configuration writes are needed. This is not the older UHFReader18 SDK protocol.
"""
import errno
from collections import deque
from threading import Event, RLock, Thread
from .cf600 import ReaderError

DEFAULT_SERIAL_DEVICE = '/dev/serial/by-id/usb-CFUSB_HID_By_YLW28-if03-port0'


def crc16(data):
    value = 0xFFFF
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ 0x8408 if value & 1 else value >> 1
    return value.to_bytes(2, 'big')


class CFFrameDecoder:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        tags = []
        # Examine each possible header, including past incomplete noise. Only a
        # complete CRC-valid frame can consume a candidate and its payload.
        position = 0
        incomplete = None
        while position < len(self.buffer):
            if self.buffer[position] != 0xCF:
                position += 1
                continue
            remaining = len(self.buffer) - position
            if remaining < 5:
                incomplete = position if incomplete is None else incomplete
                break
            size = self.buffer[position + 4] + 7
            if remaining < size:
                incomplete = position if incomplete is None else incomplete
                position += 1
                continue
            frame = bytes(self.buffer[position:position + size])
            if crc16(frame[:-2]) != frame[-2:]:
                position += 1
                continue
            position += size
            incomplete = None
            # Successful inventory: status, RSSI(2), antenna, channel,
            # EPC byte length, EPC. Other responses never become product tags.
            if frame[2:4] == b'\x00\x01' and frame[4] >= 6 and frame[5] == 0:
                length = frame[10]
                if 1 <= length <= 12 and frame[4] == 6 + length:
                    tags.append(frame[11:11 + length].hex().upper())
        if incomplete is not None:
            del self.buffer[:incomplete]
        else:
            self.buffer.clear()
        return tags


class CF600SerialReader:
    def __init__(self, path=DEFAULT_SERIAL_DEVICE, baudrate=57600, *, serial_factory=None, capacity=256):
        self.path = path
        self.baudrate = baudrate
        self.serial_factory = serial_factory
        self.capacity = capacity
        self._lock = RLock()
        self._stop = Event()
        self._thread = None
        self._reads = deque()
        self._error = None

    @staticmethod
    def _mapped_error(error):
        if isinstance(error, ReaderError):
            return error
        # pyserial wraps permission/busy errors in SerialException.
        code = getattr(error, 'errno', None)
        if isinstance(error, PermissionError) or code in (errno.EACCES, errno.EPERM):
            return ReaderError('CF600 serial permission denied; check dialout access')
        if code in (errno.EBUSY, errno.EAGAIN):
            return ReaderError('Reader busy')
        return ReaderError('CF600 serial unavailable; check CDC-COM mode, driver and port')

    def start(self):
        self.stop()
        factory = self.serial_factory
        if factory is None:
            try:
                from serial import Serial
            except ImportError:
                raise ReaderError('Install pyserial from requirements-pi.txt') from None
            factory = Serial
        port = None
        try:
            port = factory(port=None, baudrate=self.baudrate, timeout=0.1, exclusive=True)
            port.dtr = False
            port.rts = False
            port.port = self.path
            port.open()
            port.reset_input_buffer()
            self._stop.clear()
            self._thread = Thread(target=self._collect, args=(port,), name='cf600-serial', daemon=True)
            self._thread.start()
        except Exception as error:
            self._thread = None
            if port is not None:
                port.close()
            raise self._mapped_error(error) from None

    def _collect(self, port):
        decoder = CFFrameDecoder()
        try:
            while not self._stop.is_set():
                data = port.read(min(max(port.in_waiting, 1), 4096))
                for tag in decoder.feed(data):
                    with self._lock:
                        if len(self._reads) >= self.capacity:
                            raise ReaderError('CF600 input overflow; rearm the scan')
                        self._reads.append(tag)
        except Exception as error:
            with self._lock:
                self._error = self._mapped_error(error)
                self._reads.clear()
        finally:
            port.close()

    def poll(self):
        with self._lock:
            if self._error:
                raise self._error
            values = list(self._reads)
            self._reads.clear()
            return values

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        with self._lock:
            self._reads.clear()
            self._error = None
