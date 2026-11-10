"""Run only the reply reader: python -m scripts.read_replies."""
from threading import Event
from smartshop.config import load_config
from smartshop.hardware.fan import FanController
from smartshop.services.reply_reader import ReplyReader


def main():
    config = load_config()
    fan = FanController()
    reader = ReplyReader(config["GMAIL_ADDRESS"], config["GMAIL_APP_PASSWORD"], fan.fan_on)
    try:
        reader.run(Event())
    except KeyboardInterrupt:
        pass
    finally:
        fan.cleanup()


if __name__ == "__main__":
    main()
