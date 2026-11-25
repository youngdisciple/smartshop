"""Motion controls, bounded alert delivery and mail providers without real mail."""
from threading import Event
from types import SimpleNamespace
import smtplib
import unittest
from unittest.mock import Mock, patch

from smartshop.services.ble import BLEService, MINEW_SERVICE
from smartshop.services.motion_alerts import MotionEmailSender
from tests.test_ble import ADDRESS, device_record, frame


class MotionMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.sender = SimpleNamespace(configured=True, send=Mock(return_value=True))
        self.service = BLEService({}, alert_sender=self.sender,
                                  dispatch=lambda function, *args: function(*args), clock=lambda: self.now)
        self.service._store_scan({ADDRESS: device_record()})
        self.service.connect(ADDRESS)
        self.addCleanup(self.service.stop)

    def arm(self):
        with patch.object(self.service, 'subscribe', return_value='alarm-viewer'):
            self.service.set_motion_monitoring(ADDRESS, True, 'admin@example.com')

    def detect(self, value):
        self.service._handle_motion(ADDRESS, value, '2026-11-23T17:00:00+00:00')

    def test_emails_only_on_new_detections_with_cooldown(self):
        self.detect(True)
        self.sender.send.assert_not_called()
        self.arm()
        self.detect(True)
        self.assertEqual(self.sender.send.call_count, 1)
        self.arm()  # Repeated "on" requests must not reset detection state.
        self.now = 61
        self.detect(True)
        self.assertEqual(self.sender.send.call_count, 1)
        self.detect(False)
        self.detect(True)
        self.assertEqual(self.sender.send.call_count, 2)
        self.now = 62
        self.detect(False)
        self.detect(True)
        self.assertEqual(self.sender.send.call_count, 2)
        self.now = 122
        self.detect(False)
        self.detect(True)
        self.assertEqual(self.sender.send.call_count, 3)
        self.assertEqual(self.service.connected()[ADDRESS]['alert_status'], 'sent')
        self.assertEqual(self.sender.send.call_args.args[0]['recipient'], 'admin@example.com')
        self.assertNotIn('_generation', self.service.connected()[ADDRESS])

    def test_disable_or_disconnect_cancels_queued_alerts(self):
        jobs = []
        self.service._dispatch = lambda function, *args: jobs.append((function, args))
        self.arm()
        self.detect(True)
        self.assertEqual(len(jobs), 1)
        with patch.object(self.service, 'unsubscribe') as unsubscribe:
            self.service.set_motion_monitoring(ADDRESS, False)
            unsubscribe.assert_called_once_with('alarm-viewer')
        function, args = jobs.pop()
        function(*args)
        self.sender.send.assert_not_called()
        self.assertEqual(self.service.connected()[ADDRESS]['alert_status'], 'off')
        self.arm()
        self.detect(True)
        with patch.object(self.service, 'unsubscribe'):
            self.service.disconnect(ADDRESS)
        function, args = jobs.pop()
        function(*args)
        self.sender.send.assert_not_called()

    def test_unconfigured_mail_and_failed_delivery_are_visible(self):
        self.sender.configured = False
        with self.assertRaisesRegex(ValueError, 'Configure Gmail or Resend'):
            self.arm()
        self.assertFalse(self.service.connected()[ADDRESS]['motion_enabled'])
        self.sender.configured = True
        self.sender.send.return_value = False
        self.arm()
        self.detect(True)
        self.assertEqual(self.service.connected()[ADDRESS]['alert_status'], 'failed')
        self.assertIsNone(self.service.connected()[ADDRESS]['last_alert_at'])

    def test_failed_receiver_start_does_not_leave_monitoring_enabled(self):
        with patch.object(self.service, 'subscribe', side_effect=ValueError('Receiver unavailable')):
            with self.assertRaisesRegex(ValueError, 'Receiver unavailable'):
                self.service.set_motion_monitoring(ADDRESS, True, 'admin@example.com')
        self.assertFalse(self.service.connected()[ADDRESS]['motion_enabled'])
        self.sender.send.assert_not_called()

    def test_armed_receiver_survives_browser_disconnect_until_switched_off(self):
        ready, stopped = Event(), Event()
        scanners = []

        class Scanner:
            def __init__(self, detection_callback, **kwargs):
                self.callback = detection_callback
                scanners.append(self)

            async def start(self):
                ready.set()

            async def stop(self):
                stopped.set()

        self.service.scanner_factory = Scanner
        self.service.set_motion_monitoring(ADDRESS, True, 'admin@example.com')
        self.assertTrue(ready.wait(2))
        browser = self.service.subscribe()
        self.service.unsubscribe(browser)
        self.assertTrue(self.service._live_thread.is_alive())
        self.assertFalse(stopped.is_set())
        scanners[0].callback(SimpleNamespace(address=ADDRESS, name='MSP01'),
                             SimpleNamespace(local_name=None, rssi=-45,
                                             service_data={MINEW_SERVICE: frame(0x11, b'\x00\x01')}))
        self.sender.send.assert_called_once()
        self.service.set_motion_monitoring(ADDRESS, False)
        self.assertTrue(stopped.is_set())
        self.assertFalse(self.service._live_thread.is_alive())


class MotionEmailTests(unittest.TestCase):
    def setUp(self):
        self.alert = dict(id='event-1', name='MSP01', address=ADDRESS,
                          recipient='admin@example.com', received_at='2026-11-23T17:00:00+00:00')

    def test_gmail_sends_to_admin_without_database(self):
        sender = MotionEmailSender({'BLE_MOTION_EMAIL_PROVIDER': 'gmail',
                                    'GMAIL_ADDRESS': 'shop@example.com', 'GMAIL_APP_PASSWORD': 'fixture password'})
        with patch('smartshop.services.motion_alerts.smtplib.SMTP_SSL') as smtp:
            client = smtp.return_value.__enter__.return_value
            client.send_message.return_value = {}
            self.assertTrue(sender.send(self.alert))
            client.login.assert_called_once_with('shop@example.com', 'fixturepassword')
            message = client.send_message.call_args.args[0]
            self.assertEqual(message['To'], 'admin@example.com')
            self.assertIn('motion detected', message['Subject'])
            self.assertIn(ADDRESS, message.get_content())

    def test_resend_uses_idempotency_key_and_failure_is_reported(self):
        sender = MotionEmailSender({'BLE_MOTION_EMAIL_PROVIDER': 'resend',
                                    'RESEND_API_KEY': 'fixture-only', 'ALERT_FROM': 'shop@example.com'})
        with patch('requests.post', return_value=SimpleNamespace(ok=True)) as post:
            self.assertTrue(sender.send(self.alert))
            self.assertEqual(post.call_args.kwargs['json']['to'], ['admin@example.com'])
            self.assertEqual(post.call_args.kwargs['headers']['Idempotency-Key'], 'motion-event-1')
        sender = MotionEmailSender({'BLE_MOTION_EMAIL_PROVIDER': 'gmail',
                                    'GMAIL_ADDRESS': 'shop@example.com', 'GMAIL_APP_PASSWORD': 'fixture-only'})
        with patch('smartshop.services.motion_alerts.smtplib.SMTP_SSL', side_effect=smtplib.SMTPException('fixture failure')):
            self.assertFalse(sender.send(self.alert))

    def test_no_credentials_does_not_attempt_delivery(self):
        sender = MotionEmailSender({'BLE_MOTION_EMAIL_PROVIDER': 'gmail'})
        with patch('smartshop.services.motion_alerts.smtplib.SMTP_SSL') as smtp:
            self.assertFalse(sender.send(self.alert))
            smtp.assert_not_called()
