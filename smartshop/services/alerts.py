"""Resend email delivery; configuration is supplied by the application."""


class AlertSender:
    def __init__(self, api_key, sender, recipient):
        self.api_key = api_key
        self.sender = sender
        self.recipient = recipient

    def send(self, fridge_id, temperature, threshold):
        import requests

        payload = {
            "from": self.sender,
            "to": [self.recipient],
            "reply_to": self.recipient,
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
                "https://api.resend.com/emails", json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"}, timeout=10,
            )
            return response.ok
        except requests.RequestException:
            return False
