"""Send motion emails without storing sensor readings or alert logs."""
from email.message import EmailMessage
from email.utils import formataddr
import smtplib
import ssl


class MotionEmailSender:
    def __init__(self, config):
        self.config = config
        self.provider = config.get('BLE_MOTION_EMAIL_PROVIDER') or config.get('RECEIPT_EMAIL_PROVIDER', 'resend')

    @property
    def configured(self):
        if self.provider == 'gmail':
            return bool(self.config.get('GMAIL_ADDRESS') and self.config.get('GMAIL_APP_PASSWORD'))
        if self.provider == 'resend':
            return bool(self.config.get('RESEND_API_KEY') and self.config.get('ALERT_FROM'))
        return False

    def send(self, alert):
        if not self.configured:
            return False
        subject = f"SmartShop: motion detected — {alert['name']}"
        body = (f"Motion was detected by {alert['name']}.\n"
                f"Sensor: {alert['address']}\n"
                f"Received: {alert['received_at']}\n\n"
                "Motion monitoring is enabled in SmartShop. You can disable it on the BLE page.")
        try:
            if self.provider == 'gmail':
                address = self.config['GMAIL_ADDRESS'].strip()
                message = EmailMessage()
                message['From'] = formataddr(('SmartShop', address))
                message['To'] = alert['recipient']
                message['Subject'] = subject
                message['Message-ID'] = f"<motion-{alert['id']}@{address.rsplit('@', 1)[-1]}>"
                message.set_content(body)
                with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=10,
                                      context=ssl.create_default_context()) as client:
                    client.login(address, self.config['GMAIL_APP_PASSWORD'].replace(' ', ''))
                    return not client.send_message(message, from_addr=address, to_addrs=[alert['recipient']])
            import requests
            response = requests.post('https://api.resend.com/emails', json={
                'from': self.config['ALERT_FROM'], 'to': [alert['recipient']],
                'subject': subject, 'text': body,
            }, headers={'Authorization': 'Bearer ' + self.config['RESEND_API_KEY'],
                        'Idempotency-Key': 'motion-' + alert['id']}, timeout=10)
            return response.ok
        except Exception:
            return False
