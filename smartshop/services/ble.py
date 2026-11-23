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
    """Share one radio listener across live pages; stop after the last viewer leaves."""

    def __init__(self, config, *, scanner_factory=None):
        self.seconds = max(1, min(30, float(config.get('BLE_SCAN_SECONDS', 8))))
        self.adapter = config.get('BLE_ADAPTER', 'hci0')
        self.scanner_factory = scanner_factory
        self._scan_lock = Lock()
        self._state_lock = Lock()
        self._devices = {}
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
                if self._record(self._devices, device, advertisement):
                    self._scanned_at = monotonic()
                    self._version += 1

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
                asyncio.run(self._listen(stop))
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
            self._subscribers.clear()
            self._stop_live()

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
            with self._state_lock:
                self._devices = deepcopy(devices)
                self._scanned_at = monotonic()
            return devices
        finally:
            self._scan_lock.release()
