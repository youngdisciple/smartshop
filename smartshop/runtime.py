"""Own shared device state and the lifecycle of all background services."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock, Thread
from .hardware.fan import FanController
from .services.alerts import AlertSender
from .services.fridge_monitor import FridgeMonitor
from .services.mqtt import MqttService
from .services.reply_reader import ReplyReader


class Runtime:
    def __init__(self, config, *, fan=None):
        self.fan = fan if fan is not None else FanController()
        self.alerts = AlertSender(
            config["RESEND_API_KEY"], config["ALERT_FROM"], config["ALERT_TO"],
        )
        self._executor = None
        self.monitor = FridgeMonitor(self.fan, self.alerts.send, self._dispatch)
        self.mqtt = MqttService(
            config["MQTT_BROKER_HOST"], config["MQTT_BROKER_PORT"], self.monitor,
        )
        self.replies = ReplyReader(
            config["GMAIL_ADDRESS"], config["GMAIL_APP_PASSWORD"], self.fan.fan_on,
        )
        self._stop_event = Event()
        self._threads = []
        self._lock = RLock()
        self.started = False

    def _dispatch(self, function, *args):
        if self._executor is None:
            raise RuntimeError("Background services have not been started")
        return self._executor.submit(function, *args)

    def start(self):
        with self._lock:
            if self.started:
                return
            self._stop_event.clear()
            self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="alerts")
            try:
                self.mqtt.start()
                for name, target in (
                    ("fan-cooldown", self.monitor.run_cooldown),
                    ("gmail-replies", self.replies.run),
                ):
                    thread = Thread(
                        name=name, target=target, args=(self._stop_event,), daemon=True,
                    )
                    thread.start()
                    self._threads.append(thread)
                self.started = True
            except Exception:
                self.stop()
                raise

    def stop(self):
        with self._lock:
            self._stop_event.set()
            try:
                self.mqtt.stop()
            finally:
                try:
                    for thread in self._threads:
                        thread.join()
                    self._threads.clear()
                    if self._executor is not None:
                        self._executor.shutdown(wait=True)
                        self._executor = None
                finally:
                    self.fan.cleanup()
                    self.monitor.below_threshold_since = None
                    self.started = False
