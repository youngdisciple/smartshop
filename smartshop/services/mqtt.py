"""MQTT transport for the existing Frig1 and Frig2 topic namespaces."""


class MqttService:
    def __init__(self, host, port, monitor):
        self.host = host
        self.port = port
        self.monitor = monitor
        self.client = None
        self.connected = False

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            self._mark_disconnected()
            return
        self.connected = True
        client.subscribe("Frig1/#")
        client.subscribe("Frig2/#")

    def _mark_disconnected(self):
        self.connected = False
        self.monitor.mark_unavailable()

    def on_connect_fail(self, client, userdata):
        self._mark_disconnected()

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self._mark_disconnected()

    def on_message(self, client, userdata, message):
        try:
            fridge, kind = message.topic.split("/")
            fridge_id = int(fridge.replace("Frig", ""))
            value = float(message.payload)
        except (ValueError, TypeError):
            return
        self.monitor.update(fridge_id, kind, value)

    def start(self):
        if self.client is not None:
            return
        if not isinstance(self.host, str) or not self.host.strip():
            raise ValueError(
                "MQTT_BROKER_HOST is missing or empty. Set it in the project .env "
                "to your MQTT broker hostname or IP address."
            )
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, reconnect_on_failure=True)
        client.on_connect = self.on_connect
        client.on_message = self.on_message
        client.on_connect_fail = self.on_connect_fail
        client.on_disconnect = self.on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        try:
            client.connect_async(self.host, self.port)
            client.loop_start()
        except Exception:
            client.disconnect()
            client.loop_stop()
            raise
        self.client = client

    def stop(self):
        self._mark_disconnected()
        if self.client is not None:
            try:
                self.client.disconnect()
            finally:
                self.client.loop_stop()
                self.client = None
