"""Shared readings, alert decisions, and fan cooldown, independent of Flask/MQTT."""
from threading import RLock
import time

ERROR_VALUE = 999
COOLDOWN_SECONDS = 5


class FridgeMonitor:
    def __init__(self, fan, send_alert, dispatch, clock=time.monotonic):
        self.fan = fan
        self.send_alert = send_alert
        self.dispatch = dispatch
        self.clock = clock
        self.latest_readings = {
            fridge_id: {"temperature": ERROR_VALUE, "humidity": ERROR_VALUE}
            for fridge_id in (1, 2)
        }
        self.thresholds = {1: 5.0, 2: 4.0}
        self.alert_sent = {1: False, 2: False}
        self.below_threshold_since = None
        self._lock = RLock()

    def snapshot(self):
        with self._lock:
            return (
                {key: value.copy() for key, value in self.latest_readings.items()},
                self.thresholds.copy(),
            )

    def mark_unavailable(self):
        """Discard stale samples so disconnected devices cannot satisfy cooldown."""
        with self._lock:
            for reading in self.latest_readings.values():
                reading.update(temperature=ERROR_VALUE, humidity=ERROR_VALUE)
            self.below_threshold_since = None

    def set_threshold(self, fridge_id, value):
        with self._lock:
            self.thresholds[fridge_id] = float(value)
            self.alert_sent[fridge_id] = False

    def update(self, fridge_id, kind, value):
        with self._lock:
            if fridge_id not in self.latest_readings or kind not in ("temperature", "humidity"):
                return
            self.latest_readings[fridge_id][kind] = value
            if kind != "temperature":
                return
            threshold = self.thresholds[fridge_id]
            if threshold is None or value == ERROR_VALUE:
                return
            if value > threshold and not self.alert_sent[fridge_id]:
                self.alert_sent[fridge_id] = True
                try:
                    self.dispatch(self._notify, fridge_id, value, threshold)
                except Exception:
                    self.alert_sent[fridge_id] = False
                    raise
            elif value <= threshold:
                self.alert_sent[fridge_id] = False

    def _notify(self, fridge_id, temperature, threshold):
        sent = False
        try:
            sent = self.send_alert(fridge_id, temperature, threshold)
        finally:
            if not sent:
                with self._lock:
                    self.alert_sent[fridge_id] = False

    def check_fan_cooldown(self):
        with self._lock:
            ready = self.fan.fan_is_on and all(
                reading["temperature"] != ERROR_VALUE
                and self.thresholds[fridge_id] is not None
                and reading["temperature"] <= self.thresholds[fridge_id]
                for fridge_id, reading in self.latest_readings.items()
            )
            if not ready:
                self.below_threshold_since = None
            elif self.below_threshold_since is None:
                self.below_threshold_since = self.clock()
            elif self.clock() - self.below_threshold_since >= COOLDOWN_SECONDS:
                self.fan.fan_off()
                self.below_threshold_since = None
                print("Fan OFF: both fridges stayed below their thresholds for 5 seconds.")

    def run_cooldown(self, stop_event):
        while not stop_event.is_set():
            self.check_fan_cooldown()
            stop_event.wait(0.2)
