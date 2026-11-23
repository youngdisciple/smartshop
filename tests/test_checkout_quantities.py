"""Barcode checkout, deliberate quantity edits and transactional stock checks."""
import unittest
from smartshop.extensions import db
from smartshop.models import Checkout, Customer, MembershipCard, Product, Purchase


class QuantityCheckoutTests(unittest.TestCase):
    def setUp(self):
        from tests.test_phase3 import ShopTests
        self.shop = ShopTests()
        self.shop.setUp()
        self.addCleanup(self.shop.tearDown)
        self.addCleanup(self.shop.runtime.reader.stop)
        self.post = self.shop.post
        self.path = self.shop.new_cart()
        self.cart = db.session.get(Checkout, self.path.rsplit('/', 1)[1])
        self.code = db.session.get(Product, 1).upc

    def barcode(self, code=None, **kwargs):
        return self.post(self.path, {'action': 'barcode', 'upc': self.code if code is None else code}, **kwargs)

    def edit(self, action, product_id='1', **kwargs):
        return self.post(self.path, {'action': action, 'product_id': product_id}, **kwargs)

    def test_barcode_only_repeated_scans_and_mixed_rfid_preserve_quantity(self):
        self.barcode()
        self.barcode('\t' + self.code + '\r\n')
        data = self.post(self.path + '/poll').json
        self.assertEqual(data['items'][0]['quantity'], 2)
        self.assertEqual(data['total_cents'], 250)
        self.assertEqual(data['messages'], [])
        self.assertIsNone(self.shop.runtime.reader.operation)
        self.edit('increase')
        self.assertEqual(self.cart.items[0]['quantity'], 3)
        self.edit('decrease')
        self.post(self.path, {'action': 'scan'})
        self.post('/reader/fake', {'tags': self.shop.tags[0]})
        for _ in range(3):
            data = self.post(self.path + '/poll').json
            self.assertEqual(data['items'][0]['quantity'], 2)
            self.assertEqual(data['total_cents'], 250)

    def test_decrease_to_zero_suppresses_rfid_until_deliberate_add_back(self):
        self.barcode()
        self.post(self.path, {'action': 'scan'})
        self.post('/reader/fake', {'tags': self.shop.tags[0]})
        self.edit('decrease')
        self.assertEqual(self.post(self.path + '/poll').json['items'], [])
        self.assertIn(1, self.cart.suppressed)
        self.barcode()
        self.assertNotIn(1, self.cart.suppressed)
        self.assertEqual(self.post(self.path + '/poll').json['items'][0]['quantity'], 1)
        self.edit('remove')
        self.edit('restore')
        self.assertEqual(self.cart.items[0]['quantity'], 1)

    def test_validation_stock_limits_archived_and_owner_guards(self):
        for code, message in (('', b'Invalid UPC'), ('ABC123', b'Invalid UPC'),
                              ('1' * 14, b'Invalid UPC'), ('999', b'Unknown UPC')):
            self.assertIn(message, self.barcode(code, follow=True).data)
            self.assertEqual(self.cart.items, [])
        for _ in range(3):
            self.barcode()
        self.assertIn(b'Product out of stock', self.barcode(follow=True).data)
        self.assertIn(b'Product out of stock', self.edit('increase', follow=True).data)
        self.assertEqual(self.cart.items[0]['quantity'], 3)
        self.assertEqual(db.session.get(Product, 1).stock, 3)
        other = self.shop.app.test_client()
        self.assertEqual(self.barcode(client=other).status_code, 404)
        self.assertEqual(self.edit('increase', client=other).status_code, 404)
        self.assertIn(b'Invalid operation', self.edit('increase', 'bad', follow=True).data)
        product = db.session.get(Product, 1)
        product.stock = 1
        db.session.commit()
        # Reductions remain possible when stock has fallen below the cart quantity.
        self.edit('decrease')
        self.edit('decrease')
        self.assertEqual(self.cart.items[0]['quantity'], 1)
        product.archived = True
        db.session.commit()
        self.assertIn(b'Unknown UPC', self.barcode(follow=True).data)
        self.assertIn(b'Product out of stock', self.edit('increase', follow=True).data)

    def test_multiquantity_payment_receipt_points_and_duplicate_success(self):
        for _ in range(3):
            self.barcode()
        for _ in range(2):
            self.barcode(db.session.get(Product, 2).upc)
        db.session.add(MembershipCard(uid='00010203', customer_email='member@example.com'))
        db.session.commit()
        self.post(self.path, {'action': 'review'})
        self.post(self.path, {'action': 'member'})
        self.shop.scan_card()
        self.post(self.path, {'action': 'confirm_member'})
        self.post(self.path, {'action': 'payment'})
        self.assertIn(b'8.25 CAD', self.shop.client.get(self.path + '/payment').data)
        self.post(self.path + '/payment', {'outcome': 'failure'})
        self.assertEqual(Purchase.query.count(), 0)
        self.assertEqual(db.session.get(Product, 1).stock, 3)
        self.post(self.path, {'action': 'payment'})
        response = self.post(self.path + '/payment', {'outcome': 'success'})
        purchase = Purchase.query.one()
        self.assertEqual(purchase.total_cents, 825)
        self.assertEqual(purchase.points_earned, 8)
        self.assertEqual(db.session.get(Customer, 'member@example.com').points, 8)
        self.assertEqual(sorted(item.quantity for item in purchase.items), [2, 3])
        self.assertEqual(db.session.get(Product, 1).stock, 0)
        self.assertEqual(db.session.get(Product, 2).stock, 1)
        receipt = self.shop.client.get(response.location).data
        self.assertIn(b'8.25 CAD', receipt)
        self.assertIn(b'3.75 CAD', receipt)
        self.post(self.path + '/payment', {'outcome': 'success'})
        self.assertEqual(Purchase.query.count(), 1)
        self.assertEqual(db.session.get(Customer, 'member@example.com').points, 8)

    def test_one_membership_scan_before_products_or_at_review_survives_edits_and_retry(self):
        db.session.add(MembershipCard(uid='00010203', customer_email='member@example.com'))
        db.session.commit()
        for stage in ('scanning', 'review'):
            with self.subTest(stage=stage):
                path = self.shop.new_cart()
                cart = db.session.get(Checkout, path.rsplit('/', 1)[1])
                if stage == 'review':
                    self.post(path, {'action': 'barcode', 'upc': self.code})
                    self.post(path, {'action': 'review'})
                self.assertIn(b'value="member"', self.shop.client.get(path).data)
                self.post(path, {'action': 'member'})
                self.shop.scan_card()
                poll = self.post(path + '/poll').json
                member = db.session.get(Customer, 'member@example.com')
                self.assertEqual(poll['membership_candidate'], member.membership_number)
                self.assertIsNone(cart.customer_email)
                self.post(path, {'action': 'confirm_member'})
                self.assertEqual(cart.customer_email, member.email)
                self.assertIsNone(self.shop.reader.operation)
                if stage == 'scanning':
                    self.post(path, {'action': 'barcode', 'upc': self.code})
                    self.post(path, {'action': 'review'})
                self.post(path, {'action': 'back'})
                self.assertEqual(cart.customer_email, member.email)
                self.assertNotIn(b'value="member"', self.shop.client.get(path).data)
                # A confirmed member no longer depends on a live reader lease.
                self.shop.reader.connected = False
                self.post(path, {'action': 'review'})
                self.post(path, {'action': 'payment'})
                self.post(path + '/payment', {'outcome': 'failure'})
                self.assertEqual(cart.customer_email, member.email)
                self.post(path, {'action': 'payment'})
                self.post(path + '/payment', {'outcome': 'success'})
                purchase = Purchase.query.filter_by(checkout_id=cart.id).one()
                self.assertEqual(purchase.customer_email, member.email)
                self.assertEqual(purchase.points_earned, 1)
                self.shop.reader.connected = True
        self.assertEqual(db.session.get(Customer, 'member@example.com').points, 2)

    def test_guest_and_new_checkout_clear_confirmed_membership(self):
        db.session.add(MembershipCard(uid='00010203', customer_email='member@example.com'))
        db.session.commit()
        self.post(self.path, {'action': 'member'})
        self.shop.scan_card()
        self.post(self.path, {'action': 'confirm_member'})
        self.post(self.path, {'action': 'guest'})
        self.assertIsNone(self.cart.customer_email)
        self.post(self.path, {'action': 'member'})
        self.shop.scan_card()
        self.post(self.path, {'action': 'confirm_member'})
        new_path = self.shop.new_cart()
        new_cart = db.session.get(Checkout, new_path.rsplit('/', 1)[1])
        self.assertIsNone(new_cart.customer_email)
        self.assertEqual(self.cart.status, 'cancelled')
        self.assertIsNone(self.shop.reader.operation)

    def test_stock_drop_after_review_rolls_back_entire_sale_and_scanning_edits_are_blocked(self):
        for code in (self.code, self.code, db.session.get(Product, 2).upc, db.session.get(Product, 2).upc):
            self.barcode(code)
        self.shop.ready(self.path)
        self.barcode()
        self.edit('increase')
        self.assertEqual([item['quantity'] for item in self.cart.items], [2, 2])
        db.session.get(Product, 2).stock = 1
        db.session.commit()
        self.post(self.path + '/payment', {'outcome': 'success'})
        self.assertEqual(Purchase.query.count(), 0)
        self.assertEqual(db.session.get(Product, 1).stock, 3)
        self.assertEqual(db.session.get(Product, 2).stock, 1)
        self.assertEqual(self.cart.status, 'review')
        self.assertIn(b'Product out of stock', self.post(self.path, {'action': 'review'}, follow=True).data)
