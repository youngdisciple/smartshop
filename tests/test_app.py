import importlib
from html.parser import HTMLParser
import sys
from threading import Event
import unittest
from unittest.mock import MagicMock, Mock, patch
from werkzeug.security import check_password_hash

from smartshop import create_app
from smartshop.extensions import db
from smartshop.models import Customer


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active_links = []
        self.refreshes = []
        self.scripts = []
        self.stylesheets = []
        self.in_head = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'head':
            self.in_head = True
        if tag == 'a' and attrs.get('aria-current') == 'page':
            self.active_links.append(attrs['href'])
        if tag == 'meta' and attrs.get('http-equiv') == 'refresh':
            self.refreshes.append((attrs['content'], self.in_head))
        if tag == 'script':
            self.scripts.append(attrs)
        if tag == 'link' and attrs.get('rel') == 'stylesheet':
            self.stylesheets.append(attrs['href'])

    def handle_endtag(self, tag):
        if tag == 'head':
            self.in_head = False


class AppTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def test_factory_and_imports_have_no_external_side_effects(self):
        with patch('socket.socket', side_effect=AssertionError('network access')), \
             patch('threading.Thread.start', side_effect=AssertionError('worker started')):
            app = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
            for module in ('app', 'scripts.check_gmail', 'scripts.monitor_mqtt',
                           'scripts.read_replies', 'smartshop.hardware.leds'):
                importlib.import_module(module)
            self.assertFalse(app.extensions['smartshop'].started)
            self.assertNotIn('RPi.GPIO', sys.modules)

    def test_dashboard_and_thresholds(self):
        runtime = self.app.extensions['smartshop']
        response = self.client.get('/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'No signal', response.data)
        self.assertIn(b'/thresholds/1', response.data)
        response = self.client.post('/thresholds/1', data={'threshold': '6.5'})
        self.assertEqual(response.location, '/dashboard')
        self.assertEqual(runtime.monitor.thresholds[1], 6.5)
        self.client.post('/thresholds/1', data={'threshold': '51'})
        self.assertEqual(runtime.monitor.thresholds[1], 6.5)
        runtime.fan = Mock(fan_is_on=True)
        runtime.monitor.latest_readings[1]['temperature'] = 2
        response = self.client.get('/dashboard')
        self.assertIn(b'2.0', response.data)
        self.assertIn(b'ON', response.data)
        self.assertIn(b'No customers yet.', self.client.get('/admin/').data)

    def test_shared_navigation_and_page_specific_refresh(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/dashboard')
        for path in ('/dashboard', '/admin/', '/auth/signup'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                page = PageParser()
                page.feed(response.get_data(as_text=True))
                self.assertEqual(page.active_links, [path])
                self.assertEqual(page.refreshes, [('3', True)] if path == '/dashboard' else [])
                self.assertEqual(page.scripts, [])
                self.assertEqual(page.stylesheets, ['/static/dashboard.css'])
                for link in ('/dashboard', '/admin/', '/auth/signup'):
                    self.assertIn(f'href="{link}"'.encode(), response.data)
                self.assertIn(b'name="viewport"', response.data)
        css = self.client.get('/static/dashboard.css')
        self.assertEqual(css.status_code, 200)
        self.assertIn(b':focus-visible', css.data)
        self.assertIn(b'@media', css.data)
        css.close()

    def test_customer_directory_populated_and_empty(self):
        response = self.client.get('/admin/')
        self.assertIn(b'No customers yet.', response.data)
        self.assertNotIn(b'<th>ID</th>', response.data)
        with self.app.app_context():
            db.session.add_all([
                Customer('zoe@example.com', 'hidden-password', 'Zoe', '9 Main', '555-0100'),
                Customer('amy@example.com', 'hidden-password', 'Amy <Shop>', '1 Main', ''),
            ])
            db.session.commit()
        response = self.client.get('/admin/')
        self.assertNotIn(b'No customers yet.', response.data)
        self.assertIn(b'2 customers', response.data)
        self.assertIn(b'Amy &lt;Shop&gt;', response.data)
        self.assertLess(response.data.index(b'Amy &lt;Shop&gt;'), response.data.index(b'Zoe'))
        for value in (b'zoe@example.com', b'9 Main', b'555-0100'):
            self.assertIn(value, response.data)
        self.assertNotIn(b'hidden-password', response.data)

    def test_refrigerator_readings_connection_and_fan_states(self):
        runtime = self.app.extensions['smartshop']
        response = self.client.get('/dashboard')
        self.assertIn(b'Refrigerator connection offline', response.data)
        self.assertIn(b'Temperature: No signal', response.data)
        self.assertIn(b'Humidity: No signal', response.data)
        self.assertIn(b'>OFF</span>', response.data)
        runtime.mqtt.connected = True
        runtime.fan = Mock(fan_is_on=True)
        runtime.monitor.latest_readings[1].update(temperature=2.5, humidity=45)
        response = self.client.get('/dashboard')
        self.assertNotIn(b'Refrigerator connection offline', response.data)
        self.assertIn(b'>Online</span>', response.data)
        self.assertIn('2.5 °C'.encode(), response.data)
        self.assertIn(b'45.0 %', response.data)
        self.assertIn(b'>ON</span>', response.data)
        for fridge_id, threshold in ((1, '-10'), (2, '50')):
            response = self.client.post(f'/thresholds/{fridge_id}', data={'threshold': threshold})
            self.assertEqual(response.location, '/dashboard')
            self.assertEqual(runtime.monitor.thresholds[fridge_id], float(threshold))

    def test_signup_and_validation(self):
        self.assertEqual(self.client.get('/auth/signup').status_code, 200)
        data = dict(email='user@example.com', name='User', password='secret12',
                    confirm_password='secret12', address='123 Main', phone='123')
        cases = [({'email': 'a@b.c'}, b'Email must'),
                 ({'name': ''}, b'First name must'),
                 ({'confirm_password': 'different'}, b'match'),
                 ({'password': 'short', 'confirm_password': 'short'}, b'atleast')]
        for changes, message in cases:
            with self.subTest(changes=changes):
                response = self.client.post('/auth/signup', data=data | changes)
                self.assertIn(message, response.data)
                with self.app.app_context():
                    self.assertEqual(db.session.query(Customer).count(), 0)
        response = self.client.post('/auth/signup', data=data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/admin/')
        response = self.client.get(response.location)
        self.assertIn(b'Account created!', response.data)
        self.assertIn(b'user@example.com', response.data)
        self.assertIn(b'1 customer', response.data)
        self.assertNotIn(b'No customers yet.', response.data)
        with self.app.app_context():
            customer = db.session.get(Customer, data['email'])
            self.assertEqual(customer.name, 'User')
            self.assertNotEqual(customer.password, data['password'])
            self.assertTrue(check_password_hash(customer.password, data['password']))
        response = self.client.post('/auth/signup', data=data)
        self.assertIn(b'Email Already Exists', response.data)

    def test_offline_broker_retries_while_dashboard_remains_available(self):
        runtime = self.app.extensions['smartshop']
        runtime.mqtt.host = 'offline-broker'
        retried = Event()
        attempts = []

        def refuse_connection(*args, **kwargs):
            attempts.append(1)
            if len(attempts) >= 2:
                retried.set()
            raise ConnectionRefusedError('Broker offline for testing')

        # Run the actual Paho network loop, replacing only socket creation.
        with patch('paho.mqtt.client.Client._create_socket_connection',
                   side_effect=refuse_connection), \
             patch.object(runtime.replies, 'run', side_effect=lambda stop: stop.wait()):
            try:
                runtime.start()
                workers = list(runtime._threads)
                self.assertTrue(runtime.started)
                self.assertTrue(retried.wait(4), 'MQTT did not retry the offline broker')
                response = self.client.get('/dashboard')
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'Refrigerator connection offline', response.data)
                self.assertIn(b'No signal', response.data)
                response = self.client.post('/thresholds/1', data={'threshold': '6'})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(runtime.monitor.thresholds[1], 6)
            finally:
                runtime.stop()
            self.assertFalse(runtime.started)
            self.assertIsNone(runtime.mqtt.client)
            self.assertTrue(all(not thread.is_alive() for thread in workers))

    def test_separate_apps_have_separate_device_state(self):
        other = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        self.app.extensions['smartshop'].monitor.set_threshold(1, 10)
        self.assertEqual(other.extensions['smartshop'].monitor.thresholds[1], 5)

    def test_entrypoint_reloader_and_cleanup(self):
        import app as entrypoint
        for debug, child, expected in ((True, '', 0), (True, 'true', 1), (False, '', 1)):
            with self.subTest(debug=debug, child=child):
                runtime = Mock()
                application = MagicMock(extensions={'smartshop': runtime})
                with patch.object(entrypoint, 'create_app', return_value=application), \
                     patch.object(entrypoint.db, 'create_all') as create_tables, \
                     patch.object(entrypoint.atexit, 'register'), \
                     patch.dict('os.environ', {'WERKZEUG_RUN_MAIN': child}):
                    entrypoint.main(debug=debug)
                    self.assertEqual(runtime.start.call_count, expected)
                    self.assertEqual(create_tables.call_count, expected)
                    runtime.stop.assert_called_once()
                    application.run.assert_called_once_with(debug=debug)
