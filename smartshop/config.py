"""Load settings once, before constructing application services."""
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parent.parent


def load_config():
    load_dotenv(ROOT / ".env")
    return {
        "SECRET_KEY": os.getenv("SECRET_KEY", "smartshop"),
        "SQLALCHEMY_DATABASE_URI": URL.create(
            "mysql+pymysql", username=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"), host="localhost", database="smartshop",
        ),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "MQTT_BROKER_HOST": os.getenv("MQTT_BROKER_HOST"),
        "MQTT_BROKER_PORT": 1883,
        "RESEND_API_KEY": os.getenv("RESEND_API_KEY"),
        "ALERT_FROM": os.getenv("ALERT_FROM", "onboarding@resend.dev"),
        "ALERT_TO": os.getenv("ALERT_TO"),
        "GMAIL_ADDRESS": os.getenv("GMAIL_ADDRESS"),
        "GMAIL_APP_PASSWORD": os.getenv("GMAIL_APP_PASSWORD"),
    }
