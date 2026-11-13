"""Software evidence only: synthetic EPCs are not the four physical EPCs."""
import json
from datetime import date
from pathlib import Path
import tempfile
from threading import Barrier, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import generate_password_hash
from smartshop import create_app
from smartshop.extensions import db
from smartshop.models import Checkout, Customer, MembershipCard, Product, Purchase, Reception
from smartshop.hardware.product_reader import FakeReader, ProductReader
from smartshop.services.membership import MembershipReader, normalize_uid
from smartshop.services.catalog import receive
from smartshop.services.checkout import add_tags, finalize, review
from smartshop.services.migrations import migrate
from smartshop.services.receipts import deliver, receipt_text
from scripts.setup_shop import seed_verified


class ShopTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'FAKE_READERS_ENABLED': True, 'PRODUCT_READER_BACKEND': 'disabled', 'FRIDGE_SERVICES_ENABLED': False,
                               'GMAIL_SERVICE_ENABLED': False, 'RESEND_API_KEY': None})
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        for email in ('admin@example.com', 'member@example.com', 'other@example.com'):
            customer = Customer(email, generate_password_hash('secret12'), email.split('@')[0], '123 Main', '')
            customer.is_admin = email.startswith('admin')
            db.session.add(customer)
        # Explicit synthetic identifiers; never persisted into an operator DB.
        self.tags = ['DE' + '0' * 18 + suffix for suffix in ('4965', '4970', '4968', '4951')]
        for index, tag in enumerate(self.tags):
            db.session.add(Product(name=f'Development product {index + 1}', category='Development', producer='Fixture',
                                   upc=f'000000000000{index}', epc=tag, price_cents=125 + index * 100, stock=0))
        db.session.commit()
        for product in Product.query.all():
            receive(product.id, '3', date.today().isoformat())
        self.client = self.app.test_client()
        self.runtime = self.app.extensions['smartshop']
        self.reader = self.runtime.membership
        self.reader.connected = True
        self.message('/status', {'v': 1, 'reader_epoch': 'test-epoch', 'online': True})

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def message(self, topic, data, retain=False):
        self.reader.on_message(None, None, SimpleNamespace(topic=self.reader.topic + topic, payload=json.dumps(data).encode(), retain=retain))

    def scan_card(self, uid='00010203'):
        self.message('/event', {'v': 1, 'reader_epoch': 'test-epoch', 'operation_id': self.reader.operation['id'], 'event_id': 'event-1', 'uid': uid})

    def post(self, path, data=None, client=None, follow=False):
        client = client or self.client
        client.get('/auth/login')
        with client.session_transaction() as session:
            token = session['csrf']
        return client.post(path, data={'csrf_token': token, **(data or {})}, follow_redirects=follow)

    def login(self, email='member@example.com', client=None):
        return self.post('/auth/login', {'email': email, 'password': 'secret12'}, client=client)

    def new_cart(self, client=None):
        response = self.post('/checkout', client=client)
        return response.location

    def scanned_cart(self, client=None):
        path = self.new_cart(client)
        self.post(path, {'action': 'scan'}, client=client)
        self.post('/reader/fake', {'tags': ' '.join(self.tags + self.tags[:1])}, client=client)
        response = self.post(path + '/poll', client=client)
        self.assertEqual(len(response.json['items']), 4)
        return path

    def ready(self, path):
        self.post(path, {'action': 'review'})
        self.post(path, {'action': 'payment'})

    def test_catalog_validation_barcode_and_admin_boundaries(self):
        for route in ('/products', '/products/new', '/inventory/1', '/products/lookup?upc=0000000000000'):
            self.assertEqual(self.client.get(route).status_code, 302)
        self.login()
        self.assertEqual(self.post('/products/1/delete').status_code, 403)
        self.login('admin@example.com')
        values = dict(name='New', category='Food', producer='Company', price='1.25', upc='000000001', epc='00AA')
        for changes in ({'price': 'NaN'}, {'price': '-1'}, {'price': '1.001'}, {'epc': '496'}, {'upc': '12345678901234'}, {'upc': '１２３'}, {'name': ''}):
            self.post('/products/new', values | changes)
            self.assertEqual(Product.query.count(), 4)
        self.assertEqual(self.post('/products/new', values).location, '/products')
        product = Product.query.filter_by(epc='00AA').one()
        self.assertEqual(product.upc, '000000001')
        self.assertEqual(product.stock, 0)
        self.assertEqual(self.client.get('/products/lookup?upc=000000001%0D%0A').json['id'], product.id)
        self.assertEqual(self.client.get('/products/lookup?upc=9999').status_code, 404)
        self.assertEqual(self.client.get('/products/lookup?upc=abc').status_code, 400)
        self.post('/products/new', values)
        self.assertEqual(Product.query.count(), 5)
        self.post(f'/products/{product.id}/delete')
        self.assertEqual(Product.query.count(), 4)
        self.post('/products/1/delete')
        self.assertTrue(db.session.get(Product, 1).archived)

    def test_receptions_accumulate_and_invalid_data_is_atomic(self):
        self.login('admin@example.com')
        self.post('/inventory/1', {'quantity': '4', 'received_on': '2026-01-01'})
        self.assertEqual(db.session.get(Product, 1).stock, 7)
        self.assertEqual(Reception.query.filter_by(product_id=1).count(), 2)
        for quantity, received in [('0', '2026-01-01'), ('-1', '2026-01-01'), ('1.5', '2026-01-01'), ('2', 'invalid'), ('2', '2999-01-01')]:
            self.post('/inventory/1', {'quantity': quantity, 'received_on': received})
        self.assertEqual(db.session.get(Product, 1).stock, 7)

    def test_database_rejects_removing_product_with_inventory_history(self):
        with self.assertRaises(IntegrityError):
            db.session.delete(db.session.get(Product, 1))
            db.session.commit()
        db.session.rollback()
        self.assertEqual(Reception.query.filter_by(product_id=1).count(), 1)
        self.assertEqual(db.session.get(Product, 1).stock, 3)

    def test_cart_multiple_tags_repeat_removal_restore_and_owner_isolation(self):
        path = self.scanned_cart()
        data = self.post(path + '/poll').json
        self.assertEqual(data['total_cents'], 1100)
        self.assertTrue(all(item['quantity'] == 1 for item in data['items']))
        other = self.app.test_client()
        self.assertEqual(other.get(path).status_code, 404)
        self.assertEqual(self.post(path + '/poll', client=other).status_code, 404)
        self.post(path, {'action': 'remove', 'product_id': '1'})
        self.assertEqual(len(self.post(path + '/poll').json['items']), 3)
        self.post(path, {'action': 'restore', 'product_id': '1'})
        self.assertEqual(len(self.post(path + '/poll').json['items']), 4)
        self.assertEqual(db.session.get(Product, 1).stock, 3)
        self.post(path, {'action': 'review'})
        self.assertIsNone(self.runtime.reader.operation)
        self.assertEqual(self.post('/reader/fake', {'tags': self.tags[0]}).status_code, 409)
        new_path = self.scanned_cart()
        self.assertNotEqual(new_path, path)
        self.assertEqual(db.session.get(Checkout, path.rsplit('/', 1)[1]).status, 'cancelled')

    def test_guest_payment_fail_cancel_success_duplicate_and_reusable_tag(self):
        path = self.scanned_cart()
        for outcome in ('failure', 'cancel'):
            self.ready(path)
            self.post(path + '/payment', {'outcome': outcome})
            self.assertEqual(Purchase.query.count(), 0)
            self.assertEqual(db.session.get(Product, 1).stock, 3)
        self.ready(path)
        response = self.post(path + '/payment', {'outcome': 'success'})
        purchase = Purchase.query.one()
        self.assertEqual(response.location, '/receipts/' + purchase.id)
        self.assertEqual(purchase.points_earned, 0)
        self.assertEqual(db.session.get(Product, 1).stock, 2)
        self.post(path + '/payment', {'outcome': 'success'})
        self.assertEqual(Purchase.query.count(), 1)
        self.assertEqual(db.session.get(Product, 1).stock, 2)
        self.assertEqual(self.app.test_client().get(response.location).status_code, 404)
        self.assertEqual(self.client.get(response.location).status_code, 200)
        later = self.scanned_cart()
        self.ready(later)
        self.post(later + '/payment', {'outcome': 'success'})
        self.assertEqual(db.session.get(Product, 1).stock, 1)
        self.assertEqual(Purchase.query.count(), 2)

    def test_member_identification_explicit_confirmation_history_receipt_and_email(self):
        db.session.add(MembershipCard(uid='00010203', customer_email='member@example.com'))
        db.session.commit()
        path = self.scanned_cart()
        self.post(path, {'action': 'review'})
        self.post(path, {'action': 'member'})
        self.scan_card()
        cart = db.session.get(Checkout, path.rsplit('/', 1)[1])
        self.assertIsNone(cart.customer_email)
        self.post(path, {'action': 'confirm_member'})
        self.assertEqual(cart.customer_email, 'member@example.com')
        self.assertEqual(self.client.get('/account').status_code, 302)  # card is not login
        self.post(path, {'action': 'payment'})
        response = self.post(path + '/payment', {'outcome': 'success'})
        purchase = Purchase.query.one()
        self.assertEqual(purchase.receipt_status, 'failed')
        self.assertEqual(purchase.total_cents, 1100)
        self.assertEqual(db.session.get(Customer, 'member@example.com').points, 11)
        text_before = receipt_text(purchase)
        db.session.get(Product, 1).name = 'Changed name'
        db.session.get(Product, 1).price_cents = 999
        db.session.commit()
        self.assertEqual(receipt_text(purchase), text_before)
        sender = Mock(return_value=True)
        deliver(purchase.id, self.app.config, sender)
        self.assertEqual(sender.call_args.args[0], 'member@example.com')
        self.assertEqual(sender.call_args.args[1], text_before)
        deliver(purchase.id, self.app.config, sender)
        sender.assert_called_once()
        member = self.app.test_client()
        self.login(client=member)
        self.assertIn(purchase.id.encode(), member.get('/account').data)
        self.assertEqual(member.get(response.location).status_code, 200)
        other = self.app.test_client()
        self.login('other@example.com', other)
        self.assertEqual(other.get(response.location).status_code, 404)
        self.assertEqual(self.post(response.location + '/retry', client=other).status_code, 404)

    def test_unknown_membership_retry_guest_and_no_sale_until_success(self):
        path = self.scanned_cart()
        self.post(path, {'action': 'review'})
        self.post(path, {'action': 'member'})
        self.scan_card('FFFFFFFF')
        self.assertIn('Unknown membership card', self.post(path + '/poll').json['messages'])
        response = self.post(path, {'action': 'confirm_member'}, follow=True)
        self.assertIn(b'Unknown membership card', response.data)
        self.post(path, {'action': 'guest'})
        self.assertEqual(MembershipCard.query.count(), 0)
        self.assertEqual(Purchase.query.count(), 0)
        self.assertIsNone(self.reader.operation)

    def test_price_and_stock_revalidation_and_persistence_failure_roll_back(self):
        path = self.scanned_cart()
        self.ready(path)
        product = db.session.get(Product, 4)
        product.price_cents += 1
        db.session.commit()
        self.post(path + '/payment', {'outcome': 'success'})
        self.assertEqual(Purchase.query.count(), 0)
        self.assertEqual(db.session.get(Product, 1).stock, 3)
        self.ready(path)
        cart = db.session.get(Checkout, path.rsplit('/', 1)[1])
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('injected')):
            with self.assertRaises(SQLAlchemyError):
                finalize(cart)
        self.assertEqual(Purchase.query.count(), 0)
        self.assertEqual(db.session.get(Product, 1).stock, 3)
        self.assertEqual(cart.status, 'payment')
        product.stock = 0
        db.session.commit()
        with self.assertRaises(ValueError):
            finalize(cart)
        self.assertEqual(db.session.get(Product, 1).stock, 3)

    def test_enrollment_conflict_replacement_busy_cancel_logout_and_private_binding(self):
        self.assertEqual(self.client.get('/account/card').status_code, 302)
        self.login()
        self.post('/account/card', {'action': 'start'})
        rival = self.app.test_client()
        self.login('other@example.com', rival)
        response = self.post('/account/card', {'action': 'start'}, client=rival)
        self.assertIn(b'Reader busy', response.data)
        self.scan_card()
        self.assertEqual(MembershipCard.query.count(), 0)
        self.post('/account/card', {'action': 'confirm'})
        self.assertEqual(MembershipCard.query.one().customer_email, 'member@example.com')
        self.post('/account/card', {'action': 'start'}, client=rival)
        self.scan_card()
        self.assertIn(b'Card belongs to another customer', self.post('/account/card', {'action': 'confirm'}, client=rival).data)
        self.post('/account/card', {'action': 'cancel'}, client=rival)
        self.post('/account/card', {'action': 'start'})
        self.scan_card('11223344')
        self.assertIn(b'Confirm card replacement', self.post('/account/card', {'action': 'confirm'}).data)
        self.post('/account/card', {'action': 'cancel'})
        self.post('/account/card', {'action': 'start', 'replace': 'yes'})
        self.scan_card('11223344')
        self.post('/account/card', {'action': 'confirm'})
        self.assertIsNone(db.session.get(MembershipCard, '00010203'))
        self.assertEqual(MembershipCard.query.one().uid, '11223344')
        self.post('/account/card', {'action': 'start'})
        self.post('/auth/logout')
        self.assertIsNone(self.reader.operation)

    def test_all_pages_render_for_admin_and_bilingual_selection_persists(self):
        self.login('admin@example.com')
        for path in ('/products', '/products/new', '/products/1/edit', '/inventory/1', '/account', '/account/card'):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.post('/language', {'language': 'fr', 'next': '/products'})
        self.assertIn(b'<html lang="fr">', self.client.get('/products').data)
        self.assertIn('Produits'.encode(), self.client.get('/products').data)
        self.assertIn('Mon compte'.encode(), self.client.get('/account').data)
        self.assertEqual(self.post('/language', {'language': 'en', 'next': '//external.com'}).location, '/')

    def test_checkout_only_runtime_does_not_start_fridge_gmail_or_gpio(self):
        with patch.object(self.runtime.mqtt, 'start') as fridge, patch.object(self.runtime.replies, 'run') as gmail:
            self.runtime.start()
            self.runtime.stop()
            fridge.assert_not_called()
            gmail.assert_not_called()

    def test_cleanup_releases_remaining_resources_after_reader_failure(self):
        self.runtime.start()
        with patch.object(self.runtime.membership, 'stop', side_effect=OSError('injected')), \
             patch.object(self.runtime.reader, 'stop') as product_stop, \
             patch.object(self.runtime.fan, 'cleanup') as cleanup:
            with self.assertRaises(OSError):
                self.runtime.stop()
            product_stop.assert_called_once()
            cleanup.assert_called_once()
            self.assertFalse(self.runtime.started)
            self.assertIsNone(self.runtime._executor)

    def test_unknown_and_unavailable_tags_do_not_create_sales(self):
        path = self.new_cart()
        self.post(path, {'action': 'scan'})
        product = db.session.get(Product, 1)
        product.stock = 0
        db.session.commit()
        self.post('/reader/fake', {'tags': self.tags[0] + ' 00AA'})
        data = self.post(path + '/poll').json
        self.assertCountEqual(data['messages'], ['Unknown product tag', 'Product out of stock'])
        self.assertEqual(data['items'], [])
        self.assertEqual(Purchase.query.count(), 0)

    def test_receipt_delivery_failure_and_provider_payload_use_saved_recipient(self):
        path = self.scanned_cart()
        cart = db.session.get(Checkout, path.rsplit('/', 1)[1])
        cart.customer_email = 'member@example.com'
        db.session.commit()
        self.ready(path)
        purchase = finalize(cart, 'fr')
        deliver(purchase.id, self.app.config, Mock(side_effect=OSError('email unavailable')))
        self.assertEqual(purchase.receipt_status, 'failed')
        self.assertEqual(Purchase.query.count(), 1)
        self.assertIn('Points obtenus', receipt_text(purchase))
        config = {'RESEND_API_KEY': 'test-key', 'RECEIPT_FROM': 'receipt@example.test'}
        with patch('requests.post', return_value=Mock(ok=True)) as post:
            deliver(purchase.id, config)
        self.assertEqual(post.call_args.kwargs['json']['to'], ['member@example.com'])
        self.assertEqual(post.call_args.kwargs['headers']['Idempotency-Key'], 'receipt-' + purchase.id)
        self.assertEqual(purchase.receipt_status, 'sent')
        self.assertEqual(db.session.get(Product, 1).stock, 2)

    def test_expired_enrollment_cannot_link_and_csrf_errors_are_localized(self):
        self.login()
        self.post('/account/card', {'action': 'start'})
        self.scan_card()
        self.reader.operation['deadline'] = 0
        response = self.post('/account/card', {'action': 'confirm'})
        self.assertIn(b'Scan expired or cancelled', response.data)
        self.assertEqual(MembershipCard.query.count(), 0)
        self.post('/language', {'language': 'fr'})
        response = self.client.post('/account/card', data={'action': 'start', 'csrf_token': '\u00e9'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Jeton CSRF invalide'.encode(), response.data)

    def test_seed_rejects_unverified_and_is_repeatable(self):
        products = [dict(name=p.name, category=p.category, producer=p.producer, upc=p.upc, epc=p.epc, price=f'{p.price_cents / 100:.2f}') for p in Product.query.order_by(Product.id)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'products.json'
            path.write_text(json.dumps({'reader_verified': False, 'products': products}))
            with self.assertRaises(ValueError):
                seed_verified(path)
            path.write_text(json.dumps({'reader_verified': True, 'products': products}))
            seed_verified(path)
            seed_verified(path)
            self.assertEqual(Product.query.count(), 4)
            self.assertEqual(Reception.query.count(), 4)


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.clock = Mock(return_value=0)
        self.service = MembershipReader({}, self.clock)
        self.client = Mock()
        self.client.publish.return_value.rc = 0
        self.service.client = self.client
        self.service.on_connect(self.client, None, None, 0, None)
        self.send('/status', {'v': 1, 'online': True, 'reader_epoch': 'epoch'})

    def send(self, topic, payload, retain=False):
        self.service.on_message(None, None, SimpleNamespace(topic=self.service.topic + topic, payload=json.dumps(payload).encode(), retain=retain))

    def test_uid_lengths_preserve_zeroes_and_reject_epc_or_bad_input(self):
        for uid in ('00010203', '00010203040506', '00010203040506070809'):
            self.assertEqual(normalize_uid(uid.lower()), uid)
        for uid in ('01', '00 01 02 03', '0' * 24, None, 123):
            with self.assertRaises(ValueError):
                normalize_uid(uid)

    def test_retained_wrong_operation_epoch_malformed_and_duplicate_events(self):
        op = self.service.arm('owner', 'enroll')
        event = dict(v=1, reader_epoch='epoch', operation_id=op, event_id='event', uid='00010203')
        for change in ({'operation_id': 'old'}, {'reader_epoch': 'old'}, {'uid': 'BAD'}, {'event_id': None}, {'v': 2}):
            self.send('/event', event | change)
            self.assertIsNone(self.service.result('owner', op, 'enroll'))
        self.send('/event', event, retain=True)
        self.assertIsNone(self.service.result('owner', op, 'enroll'))
        self.service.on_message(None, None, SimpleNamespace(topic=self.service.topic + '/event', payload=b'{broken', retain=False))
        self.send('/event', event)
        self.send('/event', event | {'uid': 'FFFFFFFF'})
        self.assertEqual(self.service.result('owner', op, 'enroll'), '00010203')
        with self.assertRaises(ValueError):
            self.service.result('rival', op, 'enroll')
        self.assertFalse(self.client.publish.call_args.kwargs['retain'])

    def test_timeout_busy_cancel_disconnect_and_reconnect_need_rearm(self):
        op = self.service.arm('owner', 'checkout')
        with self.assertRaisesRegex(ValueError, 'busy'):
            self.service.arm('rival', 'enroll')
        self.service.cancel_owner('rival')
        self.assertIsNotNone(self.service.operation)
        self.clock.return_value = 60
        self.send('/status', {'v': 1, 'online': True, 'reader_epoch': 'epoch'})
        with self.assertRaises(ValueError):
            self.service.result('owner', op, 'checkout')
        op = self.service.arm('owner', 'checkout')
        self.service.on_disconnect()
        with self.assertRaises(ValueError):
            self.service.result('owner', op, 'checkout')
        self.service.on_connect(self.client, None, None, 0, None)
        with self.assertRaisesRegex(ValueError, 'disconnected'):
            self.service.arm('owner', 'checkout')
        self.send('/status', {'v': 1, 'online': True, 'reader_epoch': 'new'})
        self.assertNotEqual(self.service.arm('owner', 'checkout'), op)
        self.service.cancel_owner('owner')
        self.assertIsNone(self.service.operation)

    def test_lost_heartbeat_reader_lwt_and_new_epoch_invalidate(self):
        for trigger in ('heartbeat', 'lwt', 'epoch'):
            self.clock.return_value = 0
            self.send('/status', {'v': 1, 'online': True, 'reader_epoch': 'epoch'})
            op = self.service.arm('owner', 'enroll')
            if trigger == 'heartbeat':
                self.clock.return_value = 16
            elif trigger == 'lwt':
                self.send('/status', {'v': 1, 'online': False, 'reader_epoch': 'epoch'})
            else:
                self.send('/status', {'v': 1, 'online': True, 'reader_epoch': 'new'})
            with self.assertRaises(ValueError):
                self.service.result('owner', op, 'enroll')

    def test_product_reader_busy_expiry_dedup_registration_and_failure(self):
        adapter = FakeReader()
        reader = ProductReader(adapter, self.clock)
        op = reader.arm('owner', 'registration')
        adapter.reads = ['00aa', '00AA', '00BB']
        self.assertEqual(reader.poll('owner', op['id']), ['00AA', '00BB'])
        with self.assertRaisesRegex(ValueError, 'busy'):
            reader.arm('rival', 'checkout')
        with self.assertRaises(ValueError):
            reader.poll('rival', op['id'])
        self.clock.return_value = 60
        with self.assertRaises(ValueError):
            reader.poll('owner', op['id'])
        op = reader.arm('rival', 'checkout')
        self.assertEqual(reader.poll('rival', op['id']), [])
        adapter.poll = Mock(side_effect=OSError('disconnected'))
        with self.assertRaisesRegex(ValueError, 'failed'):
            reader.poll('rival', op['id'])
        self.assertIsNone(reader.operation)


class MigrationTests(unittest.TestCase):
    def test_legacy_customers_and_hash_survive_repeat_migration(self):
        app = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        with app.app_context():
            with db.engine.begin() as connection:
                connection.execute(text('CREATE TABLE customer (email VARCHAR(50) PRIMARY KEY, password VARCHAR(225) NOT NULL, name VARCHAR(50) NOT NULL, address VARCHAR(100) NOT NULL, phone VARCHAR(15))'))
                connection.execute(text("INSERT INTO customer VALUES ('old@example.com', 'unchanged-hash', 'Original', '123 Main', '00123')"))
            migrate()
            migrate()
            customer = db.session.get(Customer, 'old@example.com')
            self.assertEqual(customer.password, 'unchanged-hash')
            self.assertEqual(customer.phone, '00123')
            self.assertEqual(customer.points, 0)
            self.assertFalse(customer.is_admin)
            number = customer.membership_number
            migrate()
            self.assertEqual(customer.membership_number, number)
            self.assertEqual(db.session.execute(text('SELECT COUNT(*) FROM schema_version')).scalar(), 1)
            with self.assertRaises(IntegrityError):
                db.session.execute(text("UPDATE customer SET membership_number=NULL"))
                db.session.commit()
            db.session.rollback()
            db.session.remove()
            db.engine.dispose()

    def test_competing_carts_cannot_oversell(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(folder) / 'race.db')})
            with app.app_context():
                migrate()
                p = Product(name='One', category='Fixture', producer='Fixture', upc='001', epc='00AA', stock=1, price_cents=100)
                db.session.add(p)
                db.session.commit()
                cart_ids = []
                for owner in ('one', 'two'):
                    cart = Checkout(owner=owner)
                    db.session.add(cart)
                    db.session.commit()
                    add_tags(cart, ['00AA'])
                    review(cart)
                    cart.status = 'payment'
                    db.session.commit()
                    cart_ids.append(cart.id)
            barrier = Barrier(2)
            results = []
            def pay(cart_id):
                with app.app_context():
                    cart = db.session.get(Checkout, cart_id)
                    barrier.wait(timeout=5)
                    try:
                        finalize(cart)
                        results.append('success')
                    except (ValueError, SQLAlchemyError):
                        db.session.rollback()
                        results.append('rejected')
            threads = [Thread(target=pay, args=(cart_id,)) for cart_id in cart_ids]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
                self.assertFalse(thread.is_alive())
            self.assertCountEqual(results, ['success', 'rejected'])
            with app.app_context():
                self.assertEqual(Purchase.query.count(), 1)
                self.assertEqual(Product.query.one().stock, 0)
                db.session.remove()
                db.engine.dispose()
