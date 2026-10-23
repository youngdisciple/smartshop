import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.resend.com/emails"
API_KEY = os.getenv("RESEND_API_KEY")
ALERT_FROM = os.getenv("ALERT_FROM", "onboarding@resend.dev")
ALERT_TO = os.getenv("ALERT_TO")


def send_alert_email(fridge_id, temperature, threshold):
    payload = {
   	"from": ALERT_FROM,
    	"to": [ALERT_TO],
    	"reply_to": ALERT_TO,
    	"subject": f"SmartShop alert: Fridge {fridge_id} is too warm",
    	"text": (
            f"Fridge {fridge_id} is at {temperature:.1f} °C, "
            f"above its threshold of {threshold:.1f} °C.\n\n"
            "Would you like to turn on the fan?\n"
            "Reply YES to turn it on."
    	),
    }

    try:
        response = requests.post(
            API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=10,
        )
        return response.ok
    except requests.RequestException:
        return False
