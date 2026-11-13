from email.message import EmailMessage
import math
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from smartshop.config import load_config
from smartshop.hardware.fan import FanController
from smartshop.presentation.gauges import gauge
from smartshop.runtime import Runtime
from smartshop.services.alerts import AlertSender
from smartshop.services.fridge_monitor import ERROR_VALUE, FridgeMonitor
from smartshop.services.mqtt import MqttService
from smartshop.services.reply_reader import ReplyReader, get_email_text


def immediate(function, *args):
    function(*args)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.fan = Mock(fan_is_on=False)
        self.sender = Mock(return_value=True)
        self.clock = Mock(return_value=0)
        self.monitor = FridgeMonitor(self.fan, self.sender, immediate, self.clock)

    def test_alert_suppression_reset_and_retry(self):
        for value in (6, 7):
            self.monitor.update(1, 'temperature', value)
        self.sender.assert_called_once_with(1, 6, 5)
        self.monitor.update(1, 'temperature', 5)
        self.monitor.update(1, 'temperature', 7)
        self.assertEqual(self.sender.call_count, 2)
        self.monitor.set_threshold(1, 6)
        self.sender.return_value = False
        self.monitor.update(1, 'temperature', 8)
        self.assertFalse(self.monitor.alert_sent[1])
        self.monitor.update(1, 'temperature', 8)
        self.assertEqual(self.sender.call_count, 4)

    def test_error_and_humidity_do_not_alert(self):
        self.monitor.update(1, 'temperature', ERROR_VALUE)
        self.monitor.update(1, 'humidity', 90)
        self.sender.assert_not_called()
        readings, thresholds = self.monitor.snapshot()
        readings[1]['temperature'] = 42
        thresholds[1] = 42
        self.assertEqual(self.monitor.latest_readings[1]['temperature'], ERROR_VALUE)
        self.assertEqual(self.monitor.thresholds[1], 5)

    def test_cooldown_requires_five_continuous_seconds(self):
        self.fan.fan_is_on = True
        self.monitor.update(1, 'temperature', 3)
        self.monitor.check_fan_cooldown()
        self.assertIsNone(self.monitor.below_threshold_since)
        self.monitor.update(2, 'temperature', 3)
        self.monitor.check_fan_cooldown()
        self.clock.return_value = 4.9
        self.monitor.check_fan_cooldown()
        self.fan.fan_off.assert_not_called()
        self.monitor.update(2, 'temperature', 8)
        self.monitor.check_fan_cooldown()
        self.assertIsNone(self.monitor.below_threshold_since)
        self.monitor.update(2, 'temperature', 3)
        self.monitor.check_fan_cooldown()
        self.clock.return_value = 9.9
        self.monitor.check_fan_cooldown()
        self.fan.fan_off.assert_called_once()

    def test_off_fan_and_disabled_threshold_reset_cooldown(self):
        self.monitor.below_threshold_since = 1
        self.monitor.check_fan_cooldown()
        self.assertIsNone(self.monitor.below_threshold_since)
        self.fan.fan_is_on = True
        self.monitor.latest_readings[1]['temperature'] = 2
        self.monitor.latest_readings[2]['temperature'] = 2
        self.monitor.thresholds[1] = None
        self.monitor.check_fan_cooldown()
        self.fan.fan_off.assert_not_called()

    def test_mqtt_messages_and_subscriptions(self):
        mqtt = MqttService('broker', 1883, self.monitor)
        client = Mock()
        mqtt.on_connect(client, None, None, 0, None)
        self.assertEqual([c.args[0] for c in client.subscribe.call_args_list],
                         ['Frig1/#', 'Frig2/#'])
        for topic, payload in [('Frig1/temperature', b'2.5'),
                               ('Frig2/humidity', b'45'),
                               ('Frig3/temperature', b'10'),
                               ('Frig1/other', b'10'), ('bad/topic/extra', b'10'),
                               ('Frig1/temperature', b'invalid')]:
            mqtt.on_message(None, None, SimpleNamespace(topic=topic, payload=payload))
        self.assertEqual(self.monitor.latest_readings[1]['temperature'], 2.5)
        self.assertEqual(self.monitor.latest_readings[2]['humidity'], 45)
        self.sender.assert_not_called()

    def test_disconnect_discards_stale_readings_and_reconnect_resubscribes(self):
        service = MqttService('broker', 1883, self.monitor)
        client = Mock()
        service.on_connect(client, None, None, 0, None)
        self.assertTrue(service.connected)
        self.fan.fan_is_on = True
        self.monitor.update(1, 'temperature', 2)
        self.monitor.update(2, 'temperature', 2)
        self.monitor.check_fan_cooldown()
        service.on_disconnect(client, None, None, 1, None)
        self.assertFalse(service.connected)
        self.assertIsNone(self.monitor.below_threshold_since)
        self.clock.return_value = 10
        self.monitor.check_fan_cooldown()
        self.fan.fan_off.assert_not_called()
        readings, thresholds = self.monitor.snapshot()
        self.assertEqual(readings[1]['temperature'], ERROR_VALUE)
        self.assertEqual(readings[2]['humidity'], ERROR_VALUE)
        self.assertEqual(thresholds, {1: 5, 2: 4})
        client.reset_mock()
        service.on_connect(client, None, None, 0, None)
        self.assertTrue(service.connected)
        self.assertEqual(client.subscribe.call_count, 2)
        service.on_message(client, None,
                           SimpleNamespace(topic='Frig1/temperature', payload=b'3'))
        self.assertEqual(self.monitor.latest_readings[1]['temperature'], 3)

    def test_rejected_connection_does_not_subscribe(self):
        service = MqttService('broker', 1883, self.monitor)
        client = Mock()
        service.on_connect(client, None, None, 5, None)
        self.assertFalse(service.connected)
        client.subscribe.assert_not_called()

    def test_gauges(self):
        self.assertTrue(gauge(999, -10, 50, '°C')['error'])
        self.assertEqual(gauge(999, -10, 50, '°C')['label'], '999')
        self.assertEqual(gauge(-20, -10, 50, '°C')['angle'], -90)
        self.assertEqual(gauge(80, -10, 50, '°C')['angle'], 90)
        self.assertAlmostEqual(gauge(20, -10, 50, '°C')['dash'], math.pi * 45)


class ReplyTests(unittest.TestCase):
    def message(self, sender='owner@gmail.com', body='YES', subject='Re: SmartShop alert'):
        message = EmailMessage()
        message['From'] = sender
        message['Subject'] = subject
        message.set_content(body)
        return message

    def test_multipart_plain_text_skips_attachments(self):
        message = self.message(body='\nYES\nquoted text')
        message.add_alternative('<p>YES</p>', subtype='html')
        message.add_attachment(b'NO', maintype='text', subtype='plain', filename='file.txt')
        self.assertEqual(get_email_text(message).strip(), 'YES\nquoted text')

    def test_uid_baseline_sender_and_reply_rules(self):
        fan_on = Mock()
        reader = ReplyReader('owner@gmail.com', 'password', fan_on)
        messages = {
            b'2': self.message(body='\nyes\n> quoted'),
            b'3': self.message(sender='stranger@gmail.com'),
            b'4': self.message(body='YES please'),
            b'5': self.message(subject='unrelated'),
        }
        inbox = Mock()
        inbox.__enter__ = Mock(return_value=inbox)
        inbox.__exit__ = Mock(return_value=False)
        inbox.uid.return_value = ('OK', [b'1'])
        with patch('smartshop.services.reply_reader.imaplib.IMAP4_SSL', return_value=inbox):
            reader.check_replies()
            fan_on.assert_not_called()
            def uid(command, *args):
                if command == 'search':
                    return 'OK', [b'1 2 3 4 5']
                return 'OK', [(b'metadata', messages[args[0]].as_bytes())]
            inbox.uid.side_effect = uid
            reader.check_replies()
            reader.check_replies()
        fan_on.assert_called_once()
        self.assertEqual(reader.last_checked_uid, 5)

    def test_reader_stops_without_polling(self):
        stop = Event()
        stop.set()
        reader = ReplyReader('address', 'password', Mock())
        with patch.object(reader, 'check_replies') as check:
            reader.run(stop)
            check.assert_not_called()


class LifecycleTests(unittest.TestCase):
    def test_start_stop_restart_and_cleanup(self):
        config = {**load_config(), 'FRIDGE_SERVICES_ENABLED': True,
                  'GMAIL_SERVICE_ENABLED': True, 'MEMBERSHIP_SERVICE_ENABLED': False}
        runtime = Runtime(config, fan=Mock(fan_is_on=False))
        with patch.object(runtime.mqtt, 'start') as start, \
             patch.object(runtime.mqtt, 'stop') as stop, \
             patch.object(runtime.replies, 'run', side_effect=lambda event: event.wait()):
            runtime.start()
            runtime.start()
            self.assertEqual(start.call_count, 1)
            self.assertEqual(len(runtime._threads), 2)
            self.assertTrue(all(t.is_alive() for t in runtime._threads))
            runtime.stop()
            runtime.stop()
            self.assertFalse(runtime.started)
            self.assertIsNone(runtime._executor)
            self.assertEqual(runtime._threads, [])
            runtime.start()
            self.assertEqual(start.call_count, 2)
            runtime.stop()
        runtime.fan.cleanup.assert_called()

    def test_start_failure_cleans_up(self):
        config = {**load_config(), 'FRIDGE_SERVICES_ENABLED': True,
                  'MEMBERSHIP_SERVICE_ENABLED': False}
        runtime = Runtime(config, fan=Mock())
        with patch.object(runtime.mqtt, 'start', side_effect=RuntimeError('failed')), \
             patch.object(runtime.mqtt, 'stop'):
            with self.assertRaises(RuntimeError):
                runtime.start()
        self.assertFalse(runtime.started)
        self.assertIsNone(runtime._executor)
        runtime.fan.cleanup.assert_called_once()

    def test_missing_broker_reports_setting_before_creating_client(self):
        for host in (None, "", "   "):
            with self.subTest(host=host), patch('paho.mqtt.client.Client') as factory:
                service = MqttService(host, 1883, Mock())
                with self.assertRaisesRegex(ValueError, 'MQTT_BROKER_HOST'):
                    service.start()
                factory.assert_not_called()
                self.assertIsNone(service.client)

    def test_mqtt_client_lifecycle(self):
        service = MqttService('broker', 1883, Mock())
        with patch('paho.mqtt.client.Client') as factory:
            service.start()
            service.start()
            factory.assert_called_once()
            factory.return_value.connect_async.assert_called_once_with('broker', 1883)
            service.stop()
            service.stop()
            factory.return_value.disconnect.assert_called_once()
            factory.return_value.loop_stop.assert_called_once()

    def test_gpio_is_lazy_and_pin_sequence_is_preserved(self):
        gpio = Mock(BCM=11, LOW=0, HIGH=1, OUT=0)
        fan = FanController()
        with patch.dict('sys.modules', {'RPi': Mock(GPIO=gpio), 'RPi.GPIO': gpio}):
            fan.fan_off()
            gpio.setup.assert_not_called()
            fan.fan_on()
            self.assertTrue(fan.fan_is_on)
            self.assertEqual([c.args for c in gpio.output.call_args_list],
                             [(27, 1), (17, 0), (22, 1)])
            fan.cleanup()
            fan.cleanup()
            self.assertFalse(fan.fan_is_on)
            gpio.cleanup.assert_called_once_with((22, 27, 17))

    def test_alert_delivery_and_failure(self):
        import requests
        sender = AlertSender('key', 'from@example.com', 'to@example.com')
        with patch('requests.post', return_value=Mock(ok=True)) as post:
            self.assertTrue(sender.send(1, 8, 5))
            self.assertEqual(post.call_args.kwargs['json']['reply_to'], 'to@example.com')
            self.assertEqual(post.call_args.kwargs['timeout'], 10)
        with patch('requests.post', side_effect=requests.RequestException):
            self.assertFalse(sender.send(1, 8, 5))
