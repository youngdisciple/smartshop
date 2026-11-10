import importlib
import sys
import unittest
from threading import Event
from unittest.mock import MagicMock, Mock, patch
from werkzeug.security import generate_password_hash, check_password_hash
from smartshop import create_app
from smartshop.extensions import db
from smartshop.models import Customer


class AppTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def post(self, path, data=None):
        self.client.get('/auth/login')
        with self.client.session_transaction() as session:
            token = session['csrf']
        return self.client.post(path, data={'csrf_token': token, **(data or {})})

    def administrator(self):
        with self.app.app_context():
            customer = Customer('admin@example.com', generate_password_hash('secret12'), 'Admin', '123 Main', '')
            customer.is_admin = True
            db.session.add(customer)
            db.session.commit()
        self.post('/auth/login', {'email': 'admin@example.com', 'password': 'secret12'})

    def test_factory_and_imports_have_no_external_side_effects(self):
        with patch('socket.socket', side_effect=AssertionError('network access')), patch('threading.Thread.start', side_effect=AssertionError('worker started')):
            app = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
            for module in ('app', 'scripts.check_gmail', 'scripts.monitor_mqtt', 'scripts.read_replies', 'scripts.setup_shop', 'scripts.check_membership', 'scripts.scan_products', 'smartshop.hardware.leds'):
                importlib.import_module(module)
            self.assertFalse(app.extensions['smartshop'].started)
            self.assertNotIn('RPi.GPIO', sys.modules)

    def test_dashboard_thresholds_and_role_protection(self):
        runtime = self.app.extensions['smartshop']
        self.assertIn(b'No signal', self.client.get('/dashboard').data)
        self.assertEqual(self.client.post('/thresholds/1', data={'threshold': '6'}).status_code, 400)
        self.assertEqual(self.post('/thresholds/1', {'threshold': '6'}).location, '/auth/login')
        self.administrator()
        self.assertEqual(self.post('/thresholds/1', {'threshold': '6.5'}).location, '/dashboard')
        self.assertEqual(runtime.monitor.thresholds[1], 6.5)
        self.post('/thresholds/1', {'threshold': '51'})
        self.assertEqual(runtime.monitor.thresholds[1], 6.5)
        self.assertEqual(self.post('/thresholds/1', {'threshold': 'garbage'}).status_code, 400)

    def test_refrigerator_readings_connection_and_fan_states(self):
        runtime = self.app.extensions['smartshop']
        self.assertIn(b'Refrigerator connection offline', self.client.get('/dashboard').data)
        runtime.mqtt.connected = True
        runtime.fan = Mock(fan_is_on=True)
        runtime.monitor.latest_readings[1].update(temperature=2.5, humidity=45)
        response = self.client.get('/dashboard')
        self.assertIn('2.5 °C'.encode(), response.data)
        self.assertIn(b'45.0 %', response.data)
        self.assertIn(b'>ON</span>', response.data)

    def test_navigation_and_responsive_foundation(self):
        for path in ('/dashboard', '/auth/login', '/auth/signup', '/checkout'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'name="viewport"', response.data)
            self.assertIn(b'aria-current="page"', response.data)
            self.assertIn(b'<html lang="en">', response.data)
            self.assertEqual(b'http-equiv="refresh"' in response.data, path == '/dashboard')
        self.assertEqual(self.client.get('/admin/').location, '/auth/login')
        css = self.client.get('/static/dashboard.css')
        self.assertIn(b':focus-visible', css.data)
        self.assertIn(b'@media', css.data)
        css.close()

    def test_customer_directory_escapes_names_and_hides_passwords(self):
        self.administrator()
        with self.app.app_context():
            db.session.add(Customer('amy@example.com', 'hidden-password', 'Amy <Shop>', '1 Main', ''))
            db.session.commit()
        response = self.client.get('/admin/')
        self.assertIn(b'Amy &lt;Shop&gt;', response.data)
        self.assertNotIn(b'hidden-password', response.data)

    def test_signup_validation_login_logout_and_no_admin_escalation(self):
        data = dict(email='user@example.com', name='User', password='secret12', confirm_password='secret12', address='123 Main', phone='123', is_admin='true')
        for changes, message in [({'email': 'a@b.c'}, b'Invalid email'), ({'name': ''}, b'Invalid customer'), ({'confirm_password': 'different'}, b'not match'), ({'password': 'short', 'confirm_password': 'short'}, b'6 to 128')]:
            response = self.post('/auth/signup', data | changes)
            self.assertIn(message, response.data)
        response = self.post('/auth/signup', data)
        self.assertEqual(response.location, '/account')
        self.assertIn(b'user@example.com', self.client.get('/account').data)
        with self.app.app_context():
            customer = db.session.get(Customer, data['email'])
            self.assertTrue(check_password_hash(customer.password, data['password']))
            self.assertFalse(customer.is_admin)
            self.assertEqual(customer.points, 0)
            self.assertEqual(len(customer.membership_number), 32)
        self.assertEqual(self.client.get('/products').status_code, 403)
        self.assertIn(b'Email already exists', self.post('/auth/signup', data).data)
        self.post('/auth/logout')
        self.assertEqual(self.client.get('/account').location, '/auth/login')
        self.assertIn(b'Invalid email or password', self.post('/auth/login', {'email': data['email'], 'password': 'bad'}).data)
        self.assertEqual(self.post('/auth/login', data).location, '/account')

    def test_offline_broker_retries_while_dashboard_remains_available(self):
        runtime = self.app.extensions['smartshop']
        runtime.mqtt.host = 'offline-broker'
        retried = Event()
        attempts = []
        def refuse(*args, **kwargs):
            attempts.append(1)
            if len(attempts) >= 2:
                retried.set()
            raise ConnectionRefusedError('offline for testing')
        with patch('paho.mqtt.client.Client._create_socket_connection', side_effect=refuse), patch.object(runtime.replies, 'run', side_effect=lambda stop: stop.wait()):
            try:
                runtime.start()
                workers = list(runtime._threads)
                self.assertTrue(retried.wait(4))
                self.assertEqual(self.client.get('/dashboard').status_code, 200)
            finally:
                runtime.stop()
            self.assertTrue(all(not thread.is_alive() for thread in workers))

    def test_separate_apps_have_separate_device_state(self):
        other = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        self.app.extensions['smartshop'].monitor.set_threshold(1, 10)
        self.assertEqual(other.extensions['smartshop'].monitor.thresholds[1], 5)

    def test_entrypoint_reloader_and_cleanup(self):
        import app as entrypoint
        for debug, child, expected in ((True, '', 0), (True, 'true', 1), (False, '', 1)):
            runtime = Mock()
            application = MagicMock(extensions={'smartshop': runtime})
            with patch.object(entrypoint, 'create_app', return_value=application), patch.object(entrypoint, 'migrate') as migration, patch.object(entrypoint.atexit, 'register'), patch.dict('os.environ', {'WERKZEUG_RUN_MAIN': child}):
                entrypoint.main(debug=debug)
                self.assertEqual(runtime.start.call_count, expected)
                self.assertEqual(migration.call_count, expected)
                runtime.stop.assert_called_once()
