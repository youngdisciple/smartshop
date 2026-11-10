"""Optional signup status LEDs; not enabled by the web routes."""
from threading import Lock, Timer


class StatusLeds:
    PINS = (18, 23)
    STATES = ((False, False), (True, False), (False, True))

    def __init__(self):
        self._gpio = None
        self._lock = Lock()
        self._off_timer = None

    def _setup(self):
        if self._gpio is None:
            import RPi.GPIO as GPIO

            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.PINS, GPIO.OUT)
            self._gpio = GPIO

    def _turn_off(self):
        with self._lock:
            if self._gpio is not None:
                self._gpio.output(self.PINS, self.STATES[0])

    def show(self, status):
        state = self.STATES[status]
        with self._lock:
            self._setup()
            if self._off_timer is not None:
                self._off_timer.cancel()
            self._gpio.output(self.PINS, state)
            if status != 0:
                self._off_timer = Timer(3.0, self._turn_off)
                self._off_timer.daemon = True
                self._off_timer.start()

    def cleanup(self):
        with self._lock:
            if self._off_timer is not None:
                self._off_timer.cancel()
            if self._gpio is not None:
                self._gpio.output(self.PINS, self.STATES[0])
                self._gpio.cleanup(self.PINS)
                self._gpio = None
