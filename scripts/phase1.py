import RPi.GPIO as GPIO
from threading import Timer, Lock

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

LEDS = [18, 23]
GPIO.setup(LEDS, GPIO.OUT)

states = [
        (False, False),
        (True, False),
        (False, True)
]

_lock = Lock()          # prevents overlapping timers from stepping on each other
_off_timer = None

def _turn_off():
    with _lock:
        GPIO.output(LEDS, states[0])

def printToLed(status: int):
    global _off_timer

    with _lock:
        # cancel any pending "turn off" from a previous call
        if _off_timer is not None:
            _off_timer.cancel()

        if status != 0:
            GPIO.output(LEDS, states[status])
            _off_timer = Timer(3.0, _turn_off)
            _off_timer.start()
        else:
            GPIO.output(LEDS, states[0])
