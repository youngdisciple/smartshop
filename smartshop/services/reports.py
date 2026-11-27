"""Read-only reports built from committed inventory and purchase records."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from flask import abort, request

from smartshop.extensions import db
from smartshop.models import Product, Purchase, PurchaseItem, Reception


def period():
    today = datetime.now(timezone.utc).date()
    try:
        start = date.fromisoformat(request.args.get('start', today.replace(day=1).isoformat()))
        end = date.fromisoformat(request.args.get('end', today.isoformat()))
        if not 0 <= (end - start).days <= 365 or end == date.max:
            raise ValueError
    except ValueError:
        abort(400, description='Choose an ordered date range of up to 366 days.')
    return start, end


def bounds(start, end):
    return (
        Purchase.created_at >= datetime.combine(start, time.min),
        Purchase.created_at < datetime.combine(end + timedelta(days=1), time.min),
    )


def inventory(category):
    last_restock = (
        db.select(Reception.product_id, db.func.max(Reception.received_on).label('restocked'))
        .group_by(Reception.product_id).subquery()
    )
    query = (
        db.select(Product, last_restock.c.restocked)
        .outerjoin(last_restock, Product.id == last_restock.c.product_id)
        .where(Product.archived.is_(False)).order_by(Product.name, Product.id)
    )
    if category:
        query = query.where(Product.category == category)
    return db.session.execute(query).all()


def categories(include_archived=False):
    query = db.select(Product.category).distinct().order_by(Product.category)
    if not include_archived:
        query = query.where(Product.archived.is_(False))
    return db.session.scalars(query).all()


def product_sales(start, end, category='', email=None):
    quantity = db.func.sum(PurchaseItem.quantity).label('quantity')
    revenue = db.func.sum(PurchaseItem.quantity * PurchaseItem.unit_cents).label('revenue')
    query = (
        db.select(Product.id, Product.name, Product.category, quantity, revenue)
        .select_from(PurchaseItem).join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .join(Product, Product.id == PurchaseItem.product_id)
        .where(*bounds(start, end))
        .group_by(Product.id, Product.name, Product.category)
        .order_by(quantity.desc(), Product.name, Product.id)
    )
    if category:
        query = query.where(Product.category == category)
    if email is not None:
        query = query.where(Purchase.customer_email == email)
    return db.session.execute(query).all()


def customer_activity(start, end):
    first_purchase = (
        db.select(Purchase.customer_email, db.func.min(Purchase.created_at).label('first_at'))
        .where(Purchase.customer_email.is_not(None)).group_by(Purchase.customer_email).subquery()
    )
    query = (
        db.select(Purchase.customer_email, db.func.date(Purchase.created_at), first_purchase.c.first_at)
        .join(first_purchase, Purchase.customer_email == first_purchase.c.customer_email)
        .where(*bounds(start, end)).distinct()
    )
    daily = defaultdict(int)
    customers = {}
    for email, day, first_at in db.session.execute(query):
        daily[str(day)] += 1
        customers[email] = first_at.date() >= start
    days = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        days.append((day, daily[day.isoformat()]))
    return days, len(customers), sum(customers.values())
