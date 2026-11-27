"""Report access, purchase boundaries, inventory refresh and CSV downloads."""
import csv
from datetime import datetime
from io import StringIO
import unittest

from smartshop.extensions import db
from smartshop.models import Checkout, Product, Purchase, PurchaseItem
from tests import test_phase3


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.shop = test_phase3.ShopTests()
        self.shop.setUp()
        self.addCleanup(self.shop.tearDown)
        self.client = self.shop.client

    def purchase(self, email, day, quantity):
        checkout = Checkout(owner='fixture')
        db.session.add(checkout)
        db.session.flush()
        purchase = Purchase(
            checkout_id=checkout.id, customer_email=email, total_cents=quantity * 125,
            points_earned=0, created_at=datetime(2025, 1, day, 23, 59),
            items=[PurchaseItem(product_id=1, name='Development product 1', quantity=quantity, unit_cents=125)],
        )
        db.session.add(purchase)
        db.session.commit()
        return purchase.id

    def test_date_boundaries_and_customer_access(self):
        member = 'member@example.com'
        self.purchase(member, 1, 1)
        own_receipt = self.purchase(member, 2, 2)
        other_receipt = self.purchase('other@example.com', 2, 3)
        self.purchase(member, 4, 4)
        period = '?start=2025-01-02&end=2025-01-03'

        self.assertEqual(self.client.get('/admin/reports').status_code, 302)
        self.shop.login(member)
        self.assertEqual(self.client.get('/admin/reports/sales' + period).status_code, 403)
        private = self.client.get('/account/reports' + period).get_data(as_text=True)
        self.assertIn(own_receipt, private)
        self.assertNotIn(other_receipt, private)

        self.shop.login('admin@example.com')
        sales = self.client.get('/admin/reports/sales' + period).get_data(as_text=True)
        self.assertIn('6.25', sales)
        self.assertIn('<dd>5</dd>', sales)
        activity = self.client.get('/admin/reports/activity' + period).get_data(as_text=True)
        self.assertIn('<dt>Total customers</dt><dd>2</dd>', activity)
        self.assertIn('<dt>New customers</dt><dd>1</dd>', activity)
        self.assertIn('<dt>Returning customers</dt><dd>1</dd>', activity)
        self.assertIn('Quietest', activity)

    def test_inventory_reads_current_stock(self):
        self.shop.login('admin@example.com')
        self.assertEqual(self.client.get('/admin/reports').status_code, 200)
        endpoint = '/admin/reports?fragment=1&category=Development'
        self.assertIn(b'<td>3</td>', self.client.get(endpoint).data)
        db.session.get(Product, 1).stock = 2
        db.session.commit()
        self.assertIn(b'<td>2</td>', self.client.get(endpoint).data)

    def download(self, url, filename):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        self.assertEqual(response.headers['Content-Disposition'], f'attachment; filename="{filename}.csv"')
        return list(csv.DictReader(StringIO(response.data.decode('utf-8-sig'))))

    def test_csv_downloads_preserve_report_filters_and_access(self):
        member = 'member@example.com'
        own_receipt = self.purchase(member, 2, 2)
        self.purchase('other@example.com', 2, 3)
        self.purchase(member, 4, 4)
        period = '?format=csv&start=2025-01-02&end=2025-01-03'

        self.assertEqual(self.client.get('/account/reports' + period).status_code, 302)
        self.shop.login(member)
        for endpoint in ('/admin/reports', '/admin/reports/sales', '/admin/reports/activity'):
            self.assertEqual(self.client.get(endpoint + period).status_code, 403)
        customer = self.download('/account/reports' + period, 'my-purchase-report')
        self.assertEqual([row['Row Type'] for row in customer], ['Total', 'Purchase', 'Product'])
        self.assertEqual(customer[0]['Amount (CAD)'], '2.50')
        self.assertEqual(customer[1]['Receipt ID'], own_receipt)

        self.shop.login('admin@example.com')
        product = db.session.get(Product, 1)
        product.name = '=SUM(1,2)'
        product.category = 'Export fixture'
        db.session.commit()
        inventory = self.download('/admin/reports?format=csv&category=Export+fixture', 'inventory-report')
        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]['Product'], "'=SUM(1,2)")
        self.assertEqual(inventory[0]['Available Quantity'], '3')

        sales = self.download('/admin/reports/sales' + period + '&category=Export+fixture&limit=1', 'sales-report')
        self.assertEqual(sales[0]['Sales (CAD)'], '6.25')
        self.assertEqual(sales[1]['Units Sold'], '5')
        self.assertEqual(sales[1]['Most Sold Rank'], '1')
        self.assertEqual(sales[1]['Least Sold Rank'], '1')

        activity = self.download('/admin/reports/activity' + period, 'customer-activity-report')
        self.assertEqual(activity[0]['New Customers'], '2')
        self.assertEqual(activity[1]['Busiest'], 'True')
        self.assertEqual(activity[2]['Quietest'], 'True')
