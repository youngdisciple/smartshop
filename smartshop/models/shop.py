"""Checkout and inventory records. Money is always integer cents."""
from datetime import datetime, timezone
from uuid import uuid4
from smartshop.extensions import db


def identifier():
    return uuid4().hex


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(60), nullable=False)
    producer = db.Column(db.String(100), nullable=False)
    upc = db.Column(db.String(13), unique=True, nullable=False)
    epc = db.Column(db.String(24), unique=True, nullable=False)
    price_cents = db.Column(db.Integer, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    archived = db.Column(db.Boolean, nullable=False, default=False)
    __table_args__ = (
        db.CheckConstraint('stock >= 0'), db.CheckConstraint('price_cents > 0'),
    )


class Reception(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    received_on = db.Column(db.Date, nullable=False)
    product = db.relationship(Product)
    __table_args__ = (db.CheckConstraint('quantity > 0'),)


class MembershipCard(db.Model):
    uid = db.Column(db.String(20), primary_key=True)
    customer_email = db.Column(db.String(50), db.ForeignKey('customer.email'), unique=True, nullable=False)
    customer = db.relationship('Customer')


class Checkout(db.Model):
    id = db.Column(db.String(32), primary_key=True, default=identifier)
    owner = db.Column(db.String(32), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='scanning')
    items = db.Column(db.JSON, nullable=False, default=list)
    suppressed = db.Column(db.JSON, nullable=False, default=list)
    customer_email = db.Column(db.String(50), db.ForeignKey('customer.email'))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class Purchase(db.Model):
    id = db.Column(db.String(32), primary_key=True, default=identifier)
    checkout_id = db.Column(db.String(32), db.ForeignKey('checkout.id'), nullable=False, unique=True)
    customer_email = db.Column(db.String(50), db.ForeignKey('customer.email'))
    recipient = db.Column(db.String(50))
    language = db.Column(db.String(2), nullable=False, default='en')
    total_cents = db.Column(db.Integer, nullable=False)
    points_earned = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    receipt_status = db.Column(db.String(20), nullable=False, default='pending')
    receipt_attempts = db.Column(db.Integer, nullable=False, default=0)
    receipt_claimed_at = db.Column(db.DateTime)
    items = db.relationship('PurchaseItem', cascade='all, delete-orphan', order_by='PurchaseItem.id')


class PurchaseItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.String(32), db.ForeignKey('purchase.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    unit_cents = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    __table_args__ = (db.CheckConstraint('quantity > 0'),)
