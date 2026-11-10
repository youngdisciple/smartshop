"""L293D fan control. GPIO is imported only when the fan is first enabled."""
from threading import RLock


class FanController:
    ENABLE = 22
    INPUT_1 = 27
    INPUT_2 = 17

    def __init__(self):
        self.fan_is_on = False
        self._gpio = None
        self._lock = RLock()

    def setup(self):
        with self._lock:
            if self._gpio is not None:
                return
            import RPi.GPIO as GPIO

            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            for pin in (self.ENABLE, self.INPUT_1, self.INPUT_2):
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
            self._gpio = GPIO

    def fan_on(self):
        with self._lock:
            self.setup()
            gpio = self._gpio
            gpio.output(self.INPUT_1, gpio.HIGH)
            gpio.output(self.INPUT_2, gpio.LOW)
            gpio.output(self.ENABLE, gpio.HIGH)
            self.fan_is_on = True

    def fan_off(self):
        with self._lock:
            if self._gpio is not None:
                for pin in (self.ENABLE, self.INPUT_1, self.INPUT_2):
                    self._gpio.output(pin, self._gpio.LOW)
            self.fan_is_on = False

    def cleanup(self):
        with self._lock:
            self.fan_off()
            if self._gpio is not None:
                self._gpio.cleanup((self.ENABLE, self.INPUT_1, self.INPUT_2))
                self._gpio = None
