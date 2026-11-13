"""Load settings once, before constructing application services."""
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parent.parent


def enabled(name, default=False):
    return os.getenv(name, str(default)).lower() in ('1', 'true', 'yes')


def load_config():
    load_dotenv(ROOT / ".env")
    return {
        "SECRET_KEY": os.getenv("SECRET_KEY") or __import__('secrets').token_hex(32),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": enabled("COOKIE_SECURE"),
        "MAX_CONTENT_LENGTH": 65536,
        "SQLALCHEMY_DATABASE_URI": os.getenv("DATABASE_URL") or URL.create(
            "mysql+pymysql", username=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"), host=os.getenv("DB_HOST", "localhost"), database=os.getenv("DB_NAME", "smartshop"),
        ),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "MQTT_BROKER_HOST": os.getenv("MQTT_BROKER_HOST"),
        "MQTT_BROKER_PORT": int(os.getenv("MQTT_BROKER_PORT", "1883")),
        "MQTT_USERNAME": os.getenv("MQTT_USERNAME"),
        "MQTT_PASSWORD": os.getenv("MQTT_PASSWORD"),
        "MQTT_TLS": enabled("MQTT_TLS"),
        "FRIDGE_SERVICES_ENABLED": enabled("FRIDGE_SERVICES_ENABLED", True),
        "GMAIL_SERVICE_ENABLED": enabled("GMAIL_SERVICE_ENABLED", True),
        "MEMBERSHIP_SERVICE_ENABLED": enabled("MEMBERSHIP_SERVICE_ENABLED"),
        "MEMBERSHIP_TOPIC": os.getenv("MEMBERSHIP_TOPIC", "SmartShop/membership"),
        "FAKE_READERS_ENABLED": enabled("FAKE_READERS_ENABLED"),
        "PRODUCT_READER_BACKEND": os.getenv('PRODUCT_READER_BACKEND', 'disabled'),
        "CF600_SERIAL_DEVICE": os.getenv('CF600_SERIAL_DEVICE', '/dev/serial/by-id/usb-CFUSB_HID_By_YLW28-if03-port0'),
        "CF600_BAUDRATE": int(os.getenv('CF600_BAUDRATE', '57600')),
        "CF600_INPUT_DEVICE": os.getenv('CF600_INPUT_DEVICE', '/dev/input/by-id/usb-CFUSB_HID_By_YLW28-if01-event-kbd'),
        "RECEIPT_FROM": os.getenv("RECEIPT_FROM"),
        "RESEND_API_KEY": os.getenv("RESEND_API_KEY"),
        "ALERT_FROM": os.getenv("ALERT_FROM", "onboarding@resend.dev"),
        "ALERT_TO": os.getenv("ALERT_TO"),
        "GMAIL_ADDRESS": os.getenv("GMAIL_ADDRESS"),
        "GMAIL_APP_PASSWORD": os.getenv("GMAIL_APP_PASSWORD"),
    }
