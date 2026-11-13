"""Persisted receipt rendering and retryable delivery outside the sale."""
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr
import smtplib
import ssl
from sqlalchemy import or_, update
from smartshop.extensions import db
from smartshop.models import Purchase
from smartshop.models.shop import utcnow
from smartshop.presentation.i18n import money, tr


def receipt_text(purchase):
    def label(value):
        return tr(value, purchase.language)
    lines = [f"SmartShop — {label('Receipt')} {purchase.id}",
             f"{label('Date')}: {purchase.created_at.isoformat()} UTC"]
    lines.extend(f'{item.name} × {item.quantity} @ {money(item.unit_cents)} CAD = {money(item.quantity * item.unit_cents)} CAD'
                 for item in purchase.items)
    lines += [f"{label('Total')}: {money(purchase.total_cents)} CAD",
              f"{label('Points earned')}: {purchase.points_earned}"]
    return '\n'.join(lines)


def send_gmail(purchase, config):
    address = (config.get('GMAIL_ADDRESS') or '').strip()
    password = (config.get('GMAIL_APP_PASSWORD') or '').replace(' ', '')
    if not address or not password:
        return False
    message = EmailMessage()
    message['From'] = formataddr(('SmartShop', address))
    message['To'] = purchase.recipient
    message['Subject'] = tr('SmartShop receipt', purchase.language)
    message['Message-ID'] = f'<receipt-{purchase.id}@{address.rsplit("@", 1)[-1]}>'
    message.set_content(receipt_text(purchase))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=10,
                          context=ssl.create_default_context()) as client:
        client.login(address, password)
        refused = client.send_message(message, from_addr=address, to_addrs=[purchase.recipient])
    return not refused


def deliver(purchase_id, config, sender=None):
    now = utcnow()
    changed = db.session.execute(update(Purchase).where(
        Purchase.id == purchase_id, Purchase.recipient.is_not(None),
        or_(Purchase.receipt_status.in_(['pending', 'failed']),
            (Purchase.receipt_status == 'sending') & (Purchase.receipt_claimed_at < now - timedelta(minutes=5))),
    ).values(receipt_status='sending', receipt_claimed_at=now,
             receipt_attempts=Purchase.receipt_attempts + 1))
    db.session.commit()
    if changed.rowcount != 1:
        return
    purchase = db.session.get(Purchase, purchase_id, populate_existing=True)
    try:
        if sender:
            success = sender(purchase.recipient, receipt_text(purchase), purchase.id)
        elif config.get('RECEIPT_EMAIL_PROVIDER', 'resend') == 'gmail':
            success = send_gmail(purchase, config)
        elif config.get('RECEIPT_EMAIL_PROVIDER', 'resend') == 'resend':
            import requests
            success = False
            if config.get('RESEND_API_KEY') and config.get('RECEIPT_FROM'):
                response = requests.post('https://api.resend.com/emails', json={
                    'from': config['RECEIPT_FROM'], 'to': [purchase.recipient],
                    'subject': tr('SmartShop receipt', purchase.language), 'text': receipt_text(purchase),
                }, headers={'Authorization': 'Bearer ' + config['RESEND_API_KEY'],
                            'Idempotency-Key': 'receipt-' + purchase.id}, timeout=10)
                success = response.ok
        else:
            success = False
        purchase.receipt_status = 'sent' if success else 'failed'
    except Exception:
        purchase.receipt_status = 'failed'
    db.session.commit()
