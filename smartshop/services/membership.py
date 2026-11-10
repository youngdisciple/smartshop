"""Owned 60-second membership leases, independent of refrigerator telemetry."""
import json
import re
from threading import RLock
from time import monotonic, time
from uuid import uuid4


def normalize_uid(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{14}|[0-9a-fA-F]{20})', value):
        raise ValueError('Invalid membership UID')
    return value.upper()


class MembershipReader:
    def __init__(self, config, clock=monotonic):
        self.config = config
        self.clock = clock
        self.client = None
        self.connected = False
        self.reader_epoch = None
        self.heartbeat = float('-inf')
        self.operation = None
        self.lock = RLock()
        self.topic = config.get('MEMBERSHIP_TOPIC', 'SmartShop/membership')

    def _expire(self):
        if self.clock() - self.heartbeat >= 15:
            self.reader_epoch = None
            self.operation = None
        if self.operation and self.clock() >= self.operation['deadline']:
            self._cancel()

    def _publish(self, action, operation):
        if self.client:
            result = self.client.publish(self.topic + '/command', json.dumps({
                'v': 1, 'action': action, 'operation_id': operation['id'],
                'purpose': operation['purpose'], 'reader_epoch': self.reader_epoch,
                'expires_at': operation['expires_at'],
            }), qos=1, retain=False)
            if action == 'arm' and result.rc != 0:
                raise ValueError('Reader disconnected')

    def arm(self, owner, purpose):
        with self.lock:
            self._expire()
            if not self.connected or not self.reader_epoch:
                raise ValueError('Reader disconnected')
            if purpose not in ('enroll', 'checkout'):
                raise ValueError('Invalid operation')
            if self.operation:
                raise ValueError('Reader busy')
            operation = dict(id=uuid4().hex, owner=owner, purpose=purpose,
                             deadline=self.clock() + 60, expires_at=int(time()) + 60,
                             uid=None, event_id=None)
            self._publish('arm', operation)
            self.operation = operation
            return operation['id']

    def result(self, owner, operation_id, purpose):
        with self.lock:
            self._expire()
            if not self.connected or not self.reader_epoch:
                raise ValueError('Reader disconnected')
            op = self.operation
            if not op or op['id'] != operation_id or op['owner'] != owner or op['purpose'] != purpose:
                raise ValueError('Scan expired or cancelled')
            return op['uid']

    def _cancel(self):
        if self.operation:
            self._publish('cancel', self.operation)
        self.operation = None

    def cancel_owner(self, owner):
        with self.lock:
            if self.operation and self.operation['owner'] == owner:
                self._cancel()

    def on_message(self, client, userdata, message):
        if getattr(message, 'retain', False) or len(message.payload) > 1024:
            return
        try:
            data = json.loads(message.payload)
            if not isinstance(data, dict) or data.get('v') != 1:
                return
            with self.lock:
                self._expire()
                if message.topic == self.topic + '/status':
                    epoch = data.get('reader_epoch')
                    if not isinstance(epoch, str) or not 1 <= len(epoch) <= 64:
                        return
                    if data.get('online') is False:
                        if epoch == self.reader_epoch:
                            self.operation = None
                            self.reader_epoch = None
                        return
                    if data.get('online') is not True or not self.connected:
                        return
                    if epoch != self.reader_epoch:
                        self.operation = None
                    self.reader_epoch = epoch
                    self.heartbeat = self.clock()
                elif message.topic == self.topic + '/event':
                    op = self.operation
                    if not self.connected or not op or op['uid'] is not None:
                        return
                    event_id = data.get('event_id')
                    if (data.get('reader_epoch') != self.reader_epoch or data.get('operation_id') != op['id']
                            or not isinstance(event_id, str) or not 1 <= len(event_id) <= 64):
                        return
                    op['uid'] = normalize_uid(data.get('uid'))
                    op['event_id'] = event_id
        except (ValueError, TypeError, UnicodeError):
            return

    def on_connect(self, client, userdata, flags, reason_code, properties):
        with self.lock:
            self.connected = reason_code == 0
            self.operation = None
            self.reader_epoch = None
            if self.connected:
                client.subscribe(self.topic + '/status', qos=1)
                client.subscribe(self.topic + '/event', qos=1)

    def on_disconnect(self, *args):
        with self.lock:
            self.connected = False
            self.reader_epoch = None
            self.operation = None

    def start(self):
        if self.client:
            return
        host = self.config.get('MQTT_BROKER_HOST')
        if not host:
            raise ValueError('MQTT_BROKER_HOST is missing')
        import paho.mqtt.client as mqtt
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='smartshop-membership', clean_session=True)
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.on_connect_fail = lambda *args: self.on_disconnect()
        client.on_message = self.on_message
        if self.config.get('MQTT_USERNAME'):
            client.username_pw_set(self.config['MQTT_USERNAME'], self.config.get('MQTT_PASSWORD'))
        if self.config.get('MQTT_TLS'):
            client.tls_set()
        client.reconnect_delay_set(1, 30)
        self.client = client
        try:
            client.connect_async(host, self.config['MQTT_BROKER_PORT'])
            client.loop_start()
        except Exception:
            self.stop()
            raise

    def stop(self):
        self.on_disconnect()
        if self.client:
            try:
                self.client.disconnect()
            finally:
                self.client.loop_stop()
                self.client = None
