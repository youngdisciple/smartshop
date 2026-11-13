"""Own shared device state and the lifecycle of all background services."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock, Thread
from .hardware.fan import FanController
from .services.alerts import AlertSender
from .services.fridge_monitor import FridgeMonitor
from .services.mqtt import MqttService
from .services.reply_reader import ReplyReader
from .services.membership import MembershipReader
from .hardware.product_reader import ProductReader, configured_adapter


class Runtime:
    def __init__(self, config, *, fan=None):
        self.config = config
        self.membership = MembershipReader(config)
        self.reader = ProductReader(configured_adapter(config))
        self.checkout_lock = RLock()
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
                workers = []
                if self.config.get('FRIDGE_SERVICES_ENABLED', True):
                    self.mqtt.start()
                    workers.append(("fan-cooldown", self.monitor.run_cooldown))
                if self.config.get('GMAIL_SERVICE_ENABLED', True):
                    workers.append(("gmail-replies", self.replies.run))
                if self.config.get('MEMBERSHIP_SERVICE_ENABLED'):
                    self.membership.start()
                for name, target in workers:
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
            failure = None
            # Always release every resource, even when one adapter fails.
            for service in (self.mqtt, self.membership, self.reader):
                try:
                    service.stop()
                except Exception as error:
                    failure = failure or error
            try:
                for thread in self._threads:
                    thread.join()
                self._threads.clear()
                if self._executor is not None:
                    self._executor.shutdown(wait=True)
                    self._executor = None
            finally:
                try:
                    self.fan.cleanup()
                finally:
                    self.monitor.below_threshold_since = None
                    self.started = False
            if failure:
                raise failure
