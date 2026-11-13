"""Owned product scans with independent expiration and pluggable transports."""
from threading import RLock, Timer
from time import monotonic
from uuid import uuid4
from smartshop.services.catalog import epc
from .cf600 import CF600Reader, DEFAULT_DEVICE, ReaderError
from .cf600_serial import CF600SerialReader, DEFAULT_SERIAL_DEVICE


def configured_adapter(config):
    backend = config.get('PRODUCT_READER_BACKEND', 'disabled')
    if backend not in ('disabled', 'cf600_hid', 'cf600_serial'):
        raise ValueError('Unknown PRODUCT_READER_BACKEND')
    if config.get('FAKE_READERS_ENABLED'):
        if backend != 'disabled':
            raise ValueError('Disable FAKE_READERS_ENABLED before enabling CF600')
        return FakeReader()
    if backend == 'cf600_hid':
        return CF600Reader(config.get('CF600_INPUT_DEVICE', DEFAULT_DEVICE))
    if backend == 'cf600_serial':
        return CF600SerialReader(config.get('CF600_SERIAL_DEVICE', DEFAULT_SERIAL_DEVICE),
                                 config.get('CF600_BAUDRATE', 57600))
    return UnavailableReader()


class UnavailableReader:
    def start(self):
        raise ReaderError('Product reader disabled; configure PRODUCT_READER_BACKEND')

    def poll(self):
        return []

    def stop(self):
        pass


class FakeReader:
    def __init__(self):
        self.reads = []

    def start(self):
        self.reads.clear()

    def poll(self):
        reads, self.reads = self.reads, []
        return reads

    def stop(self):
        self.reads.clear()


class ProductReader:
    def __init__(self, adapter=None, clock=monotonic, timer_factory=Timer):
        self.adapter = adapter or UnavailableReader()
        self.clock = clock
        self.operation = None
        self.lock = RLock()
        self.timer_factory = timer_factory
        self._timer = None

    def _timeout(self, operation_id):
        with self.lock:
            if self.operation and self.operation['id'] == operation_id:
                self.stop()

    def _expire(self):
        if self.operation and self.clock() >= self.operation['deadline']:
            self.stop()

    def arm(self, owner, purpose):
        with self.lock:
            self._expire()
            if self.operation:
                if self.operation['owner'] == owner and self.operation['purpose'] == purpose:
                    return dict(self.operation)
                raise ValueError('Reader busy')
            self.adapter.start()
            self.operation = dict(id=uuid4().hex, owner=owner, purpose=purpose,
                                  deadline=self.clock() + 60, seen=[])
            try:
                self._timer = self.timer_factory(60, self._timeout, args=(self.operation['id'],))
                self._timer.daemon = True
                self._timer.start()
            except Exception:
                self.stop()
                raise
            return dict(self.operation)

    def poll(self, owner, operation_id):
        with self.lock:
            self._expire()
            operation = self.operation
            if not operation or operation['owner'] != owner or operation['id'] != operation_id:
                raise ValueError('Scan expired or cancelled')
            try:
                for value in self.adapter.poll():
                    value = epc(value)
                    if value not in operation['seen']:
                        operation['seen'].append(value)
            except Exception as error:
                self.stop()
                raise ValueError(str(error) if isinstance(error, ReaderError) else 'Reader failed') from None
            return list(operation['seen'])

    def cancel_owner(self, owner):
        with self.lock:
            if self.operation and self.operation['owner'] == owner:
                self.stop()

    def stop(self):
        with self.lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            try:
                self.adapter.stop()
            finally:
                self.operation = None
