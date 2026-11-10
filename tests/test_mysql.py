"""Opt-in isolated MariaDB/MySQL evidence. Never uses the application database."""
import os
from pathlib import Path
from threading import Barrier, Thread
import unittest
from uuid import uuid4
import pymysql
from sqlalchemy import URL, text
from sqlalchemy.exc import SQLAlchemyError
from smartshop import create_app
from smartshop.extensions import db
from smartshop.models import Checkout, Customer, Product, Purchase
from smartshop.services.checkout import add_tags, finalize, review
from smartshop.services.migrations import migrate


@unittest.skipUnless(os.getenv('SMARTSHOP_TEST_MYSQL_SOCKET'), 'Set an isolated /tmp MySQL test socket to enable')
class MySQLTests(unittest.TestCase):
    def setUp(self):
        socket = os.environ['SMARTSHOP_TEST_MYSQL_SOCKET']
        if not Path(socket).resolve().is_relative_to('/tmp'):
            self.fail('Only isolated /tmp sockets are supported by this test')
        self.connection = pymysql.connect(user='root', unix_socket=socket, autocommit=True)
        self.database = 'smartshop_test_' + uuid4().hex
        with self.connection.cursor() as cursor:
            cursor.execute('CREATE DATABASE ' + self.database)
        self.app = create_app({'SQLALCHEMY_DATABASE_URI': URL.create('mysql+pymysql', username='root', database=self.database, query={'unix_socket': socket})})

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        with self.connection.cursor() as cursor:
            cursor.execute('DROP DATABASE ' + self.database)
        self.connection.close()

    def test_existing_customer_migration_is_repeatable_and_preserves_fields(self):
        with self.app.app_context():
            with db.engine.begin() as connection:
                connection.execute(text('CREATE TABLE customer (email VARCHAR(50) PRIMARY KEY, password VARCHAR(225) NOT NULL, name VARCHAR(50) NOT NULL, address VARCHAR(100) NOT NULL, phone VARCHAR(15)) ENGINE=InnoDB'))
                connection.execute(text("INSERT INTO customer VALUES ('legacy@example.com', 'original-hash', 'Legacy', '1 Main', '00123')"))
            migrate()
            migrate()
            customer = db.session.get(Customer, 'legacy@example.com')
            self.assertEqual(customer.password, 'original-hash')
            self.assertEqual(customer.phone, '00123')
            self.assertEqual(customer.points, 0)
            self.assertEqual(len(customer.membership_number), 32)
            self.assertEqual(db.session.execute(text('SELECT COUNT(*) FROM schema_version')).scalar(), 1)

    def test_innodb_competing_payments_and_duplicate_submission(self):
        with self.app.app_context():
            migrate()
            db.session.add(Product(name='Fixture', category='Development', producer='Fixture', epc='00AA', upc='001', price_cents=100, stock=1))
            db.session.commit()
            ids = []
            for owner in ('one', 'two'):
                cart = Checkout(owner=owner)
                db.session.add(cart)
                db.session.commit()
                add_tags(cart, ['00AA'])
                review(cart)
                cart.status = 'payment'
                db.session.commit()
                ids.append(cart.id)
        barrier = Barrier(2)
        results = []
        def pay(cart_id):
            with self.app.app_context():
                cart = db.session.get(Checkout, cart_id)
                barrier.wait(timeout=5)
                try:
                    purchase = finalize(cart)
                    self.assertEqual(finalize(cart).id, purchase.id)
                    results.append('success')
                except (ValueError, SQLAlchemyError):
                    db.session.rollback()
                    results.append('rejected')
        threads = [Thread(target=pay, args=(cart_id,)) for cart_id in ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
            self.assertFalse(thread.is_alive())
        self.assertCountEqual(results, ['success', 'rejected'])
        with self.app.app_context():
            self.assertEqual(Purchase.query.count(), 1)
            self.assertEqual(Product.query.one().stock, 0)
