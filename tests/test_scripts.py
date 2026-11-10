import unittest
from unittest.mock import Mock, patch
from scripts import check_gmail, monitor_mqtt, read_replies


class ScriptTests(unittest.TestCase):
    def test_gmail_command(self):
        with patch.object(check_gmail.imaplib, 'IMAP4_SSL') as factory:
            inbox = factory.return_value.__enter__.return_value
            inbox.select.return_value = ('OK', [])
            check_gmail.main()
            inbox.login.assert_called_once()

    def test_mqtt_command_and_cleanup(self):
        with patch('paho.mqtt.client.Client') as factory:
            monitor_mqtt.main()
            factory.return_value.connect.assert_called_once()
            factory.return_value.loop_forever.assert_called_once()
            factory.return_value.disconnect.assert_called_once()

    def test_reply_command_and_cleanup(self):
        with patch.object(read_replies, 'FanController') as fan, \
             patch.object(read_replies, 'ReplyReader') as reader:
            reader.return_value.run.side_effect = KeyboardInterrupt
            read_replies.main()
            reader.return_value.run.assert_called_once()
            fan.return_value.cleanup.assert_called_once()
