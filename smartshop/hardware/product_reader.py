"""Adapter boundary. CF600 transport awaits the supplied SDK and Pi evidence."""
from threading import RLock
from time import monotonic
from uuid import uuid4
from smartshop.services.catalog import epc


class UnavailableReader:
    def start(self):
        raise ValueError('CF600 SDK unavailable')

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
    def __init__(self, adapter=None, clock=monotonic):
        self.adapter = adapter or UnavailableReader()
        self.clock = clock
        self.operation = None
        self.lock = RLock()

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
            except Exception:
                self.stop()
                raise ValueError('Reader failed') from None
            return list(operation['seen'])

    def cancel_owner(self, owner):
        with self.lock:
            if self.operation and self.operation['owner'] == owner:
                self.stop()

    def stop(self):
        with self.lock:
            try:
                self.adapter.stop()
            finally:
                self.operation = None
