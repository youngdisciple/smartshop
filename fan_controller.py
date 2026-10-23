
import RPi.GPIO as GPIO

# L293D motor driver pins (BCM numbering)
Motor1 = 22  # Enable pin (EN1)
Motor2 = 27  # Input (IN1)
Motor3 = 17  # Input (IN2)

fan_is_on = False
gpio_ready = False


def setup():
    global gpio_ready

    if gpio_ready:
        return

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    GPIO.setup(Motor1, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(Motor2, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(Motor3, GPIO.OUT, initial=GPIO.LOW)

    gpio_ready = True


def fan_on():
    global fan_is_on

    setup()

    GPIO.output(Motor2, GPIO.HIGH)
    GPIO.output(Motor3, GPIO.LOW)
    GPIO.output(Motor1, GPIO.HIGH)

    fan_is_on = True


def fan_off():
    global fan_is_on

    if gpio_ready:
        GPIO.output(Motor1, GPIO.LOW)
        GPIO.output(Motor2, GPIO.LOW)
        GPIO.output(Motor3, GPIO.LOW)

    fan_is_on = False


def cleanup():
    fan_off()

    if gpio_ready:
        GPIO.cleanup()


if __name__ == "__main__":
    setup()
    fan_off()
