"""Read the CF600's dedicated Linux keyboard interface, framed by Tab."""
import errno
from collections import deque
from select import select
from threading import Event, RLock, Thread

DEFAULT_DEVICE = '/dev/input/by-id/usb-CFUSB_HID_By_YLW28-if01-event-kbd'


class ReaderError(ValueError):
    """An actionable, translatable reader error."""


class EPCDecoder:
    # Linux input key codes; independent of the desktop keyboard layout.
    HEX_KEYS = {**dict(zip(range(2, 11), '123456789')), 11: '0',
                30: 'A', 48: 'B', 46: 'C', 32: 'D', 18: 'E', 33: 'F'}
    MODIFIERS = {42, 54}  # Shift changes case only for the supported hex keys.

    def __init__(self):
        self.reset()

    def reset(self):
        self.buffer = ''
        self.invalid = False

    def feed(self, event):
        if event.type != 1 or event.value != 1:  # EV_KEY, key down only
            return None
        if event.code == 15:  # KEY_TAB
            value = self.buffer
            valid = not self.invalid and 2 <= len(value) <= 24 and len(value) % 2 == 0
            self.reset()
            return value if valid else None
        if event.code in self.MODIFIERS:
            return None
        char = self.HEX_KEYS.get(event.code)
        if char is None or len(self.buffer) >= 24:
            self.invalid = True
        elif not self.invalid:
            self.buffer += char
        return None


class CF600Reader:
    def __init__(self, path=DEFAULT_DEVICE, *, device_factory=None, wait=select, capacity=256):
        self.path = path
        self.device_factory = device_factory
        self.wait = wait
        self.capacity = capacity
        self._lock = RLock()
        self._stop = Event()
        self._thread = None
        self._reads = deque()
        self._error = None

    def start(self):
        self.stop()
        self._reads.clear()
        self._error = None
        factory = self.device_factory
        if factory is None:
            try:
                from evdev import InputDevice
            except ImportError:
                raise ReaderError('Install evdev from requirements-pi.txt') from None
            factory = InputDevice
        device = None
        grabbed = False
        try:
            device = factory(self.path)
            if (device.info.vendor, device.info.product) != (0x0483, 0x5750) or device.name != 'CFUSB_HID By YLW28':
                raise ReaderError('Configured input is not the CF600 reader')
            device.grab()
            grabbed = True
            # Discard queued keystrokes from before this scan was armed.
            for _ in range(256):
                if not self.wait([device], [], [], 0)[0]:
                    break
                try:
                    list(device.read())
                except BlockingIOError:
                    break
            else:
                raise ReaderError('CF600 input overflow; rearm the scan')
            self._stop.clear()
            self._thread = Thread(target=self._collect, args=(device,), name='cf600-input', daemon=True)
            self._thread.start()
        except Exception as error:
            self._thread = None
            if device is not None:
                self._close(device, grabbed)
            raise self._mapped_error(error) from None

    @staticmethod
    def _mapped_error(error):
        if isinstance(error, ReaderError):
            return error
        if isinstance(error, PermissionError):
            return ReaderError('CF600 input permission denied; check device access')
        if isinstance(error, OSError) and error.errno == errno.EBUSY:
            return ReaderError('Reader busy')
        return ReaderError('CF600 input unavailable; check connection and device path')

    @staticmethod
    def _close(device, grabbed=True):
        try:
            if grabbed:
                device.ungrab()
        except OSError:
            pass
        finally:
            device.close()

    def _collect(self, device):
        decoder = EPCDecoder()
        try:
            while not self._stop.is_set():
                if not self.wait([device], [], [], 0.1)[0]:
                    continue
                try:
                    events = device.read()
                    for event in events:
                        if event.type == 0 and event.code == 3:  # SYN_DROPPED: lost framing
                            raise ReaderError('CF600 input overflow; rearm the scan')
                        value = decoder.feed(event)
                        if value:
                            with self._lock:
                                if len(self._reads) >= self.capacity:
                                    raise ReaderError('CF600 input overflow; rearm the scan')
                                self._reads.append(value)
                except BlockingIOError:
                    continue
        except Exception as error:
            with self._lock:
                self._error = self._mapped_error(error)
                self._reads.clear()
        finally:
            decoder.reset()
            self._close(device)

    def poll(self):
        with self._lock:
            if self._error:
                raise self._error
            reads = list(self._reads)
            self._reads.clear()
            return reads

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        with self._lock:
            self._reads.clear()
            self._error = None
