"""Gmail SMTP receipt tests. All SMTP connections are mocked."""
import smtplib
import ssl
import unittest
from unittest.mock import patch
from smartshop.extensions import db
from smartshop.models import Checkout, Customer, Product, Purchase
from smartshop.presentation.i18n import tr
from smartshop.services.checkout import finalize
from smartshop.services.receipts import deliver


class GmailReceiptTests(unittest.TestCase):
    def setUp(self):
        from tests.test_phase3 import ShopTests
        self.shop = ShopTests()
        self.shop.setUp()
        self.addCleanup(self.shop.tearDown)
        self.addCleanup(self.shop.runtime.reader.stop)
        self.path = self.shop.new_cart()
        for _ in range(2):
            self.shop.post(self.path, {'action': 'barcode', 'upc': '0000000000000'})
        cart = db.session.get(Checkout, self.path.rsplit('/', 1)[1])
        cart.customer_email = 'member@example.com'
        db.session.commit()
        self.shop.ready(self.path)
        self.purchase = finalize(cart, 'fr')
        self.config = {'RECEIPT_EMAIL_PROVIDER': 'gmail', 'GMAIL_ADDRESS': 'sender@example.test',
                       'GMAIL_APP_PASSWORD': 'abcd efgh ijkl mnop', 'ALERT_TO': 'wrong@example.test',
                       'RECEIPT_FROM': 'also-wrong@example.test'}

    def test_tls_login_saved_recipient_quantity_and_no_repeat_after_success(self):
        with patch('smartshop.services.receipts.smtplib.SMTP_SSL') as factory, patch('requests.post') as resend:
            client = factory.return_value.__enter__.return_value
            client.send_message.return_value = {}
            deliver(self.purchase.id, self.config)
            factory.assert_called_once()
            self.assertEqual(factory.call_args.args, ('smtp.gmail.com', 465))
            self.assertEqual(factory.call_args.kwargs['timeout'], 10)
            context = factory.call_args.kwargs['context']
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            client.login.assert_called_once_with('sender@example.test', 'abcdefghijklmnop')
            message = client.send_message.call_args.args[0]
            self.assertEqual(str(message['From']), 'SmartShop <sender@example.test>')
            self.assertEqual(str(message['To']), 'member@example.com')
            self.assertEqual(str(message['Subject']), tr('SmartShop receipt', 'fr'))
            self.assertIn('× 2', message.get_content())
            self.assertIn('2.50 CAD', message.get_content())
            self.assertIn(self.purchase.id, message['Message-ID'])
            self.assertEqual(client.send_message.call_args.kwargs['to_addrs'], ['member@example.com'])
            self.assertEqual(client.send_message.call_args.kwargs['from_addr'], 'sender@example.test')
            self.assertEqual(self.purchase.receipt_status, 'sent')
            deliver(self.purchase.id, self.config)
            client.send_message.assert_called_once()
            resend.assert_not_called()
        self.assertEqual(self.purchase.receipt_attempts, 1)

    def test_auth_failure_and_retry_do_not_repeat_sale(self):
        with patch('smartshop.services.receipts.smtplib.SMTP_SSL') as factory:
            client = factory.return_value.__enter__.return_value
            client.login.side_effect = smtplib.SMTPAuthenticationError(535, b'Invalid credentials')
            deliver(self.purchase.id, self.config)
            self.assertEqual(self.purchase.receipt_status, 'failed')
            client.send_message.assert_not_called()
            client.login.side_effect = None
            client.send_message.return_value = {}
            deliver(self.purchase.id, self.config)
            self.assertEqual(self.purchase.receipt_status, 'sent')
        self.assertEqual(self.purchase.receipt_attempts, 2)
        self.assertEqual(Purchase.query.count(), 1)
        self.assertEqual(db.session.get(Product, 1).stock, 1)
        self.assertEqual(db.session.get(Customer, 'member@example.com').points, 2)

    def test_connection_failure_or_refused_recipient_is_failed(self):
        with patch('smartshop.services.receipts.smtplib.SMTP_SSL', side_effect=OSError('offline')):
            deliver(self.purchase.id, self.config)
        self.assertEqual(self.purchase.receipt_status, 'failed')
        with patch('smartshop.services.receipts.smtplib.SMTP_SSL') as factory:
            client = factory.return_value.__enter__.return_value
            client.send_message.return_value = {'member@example.com': (550, b'refused')}
            deliver(self.purchase.id, self.config)
        self.assertEqual(self.purchase.receipt_status, 'failed')
        self.assertEqual(Purchase.query.count(), 1)

    def test_missing_credentials_and_unknown_provider_never_connect(self):
        with patch('smartshop.services.receipts.smtplib.SMTP_SSL') as factory, patch('requests.post') as resend:
            for config in ({'RECEIPT_EMAIL_PROVIDER': 'gmail'},
                           {'RECEIPT_EMAIL_PROVIDER': 'gmail', 'GMAIL_ADDRESS': 'sender@example.test'},
                           {'RECEIPT_EMAIL_PROVIDER': 'unknown'}):
                deliver(self.purchase.id, config)
                self.assertEqual(self.purchase.receipt_status, 'failed')
            factory.assert_not_called()
            resend.assert_not_called()

    def test_guest_receipt_never_connects(self):
        self.purchase.recipient = None
        self.purchase.receipt_status = 'not_required'
        db.session.commit()
        with patch('smartshop.services.receipts.smtplib.SMTP_SSL') as factory:
            deliver(self.purchase.id, self.config)
            factory.assert_not_called()
        self.assertEqual(self.purchase.receipt_status, 'not_required')
        self.assertEqual(self.purchase.receipt_attempts, 0)
