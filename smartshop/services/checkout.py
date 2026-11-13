"""Transactional checkout; no device or email operations inside a sale."""
from sqlalchemy import update
from smartshop.extensions import db
from smartshop.models import Checkout, Customer, Product, Purchase, PurchaseItem
from smartshop.services.catalog import upc


def cart_total(cart):
    return sum(item['unit_cents'] * item['quantity'] for item in cart.items)


def change_quantity(cart, product_id, delta):
    if cart.status != 'scanning':
        raise ValueError('Checkout is not scanning')
    if delta not in (-1, 1):
        raise ValueError('Invalid quantity')
    items = {item['product_id']: dict(item) for item in cart.items}
    item = items.get(product_id)
    if item is None:
        raise ValueError('Product unavailable')
    quantity = item['quantity'] + delta
    if quantity == 0:
        del items[product_id]
        cart.suppressed = list(set(cart.suppressed + [product_id]))
    elif delta > 0:
        product = db.session.get(Product, product_id, populate_existing=True)
        if not product or product.archived or product.stock < quantity:
            raise ValueError('Product out of stock')
    if quantity > 0:
        item['quantity'] = quantity
    cart.items = list(items.values())
    db.session.commit()


def add_barcode(cart, code):
    if cart.status != 'scanning':
        raise ValueError('Checkout is not scanning')
    code = upc(code)
    product = db.session.execute(db.select(Product).filter_by(upc=code, archived=False)).scalar_one_or_none()
    if product is None:
        raise ValueError('Unknown UPC')
    items = {item['product_id']: dict(item) for item in cart.items}
    quantity = items.get(product.id, {}).get('quantity', 0) + 1
    if product.stock < quantity:
        raise ValueError('Product out of stock')
    if product.id in items:
        items[product.id]['quantity'] = quantity
    else:
        items[product.id] = dict(product_id=product.id, name=product.name,
                                 unit_cents=product.price_cents, quantity=1)
    cart.items = list(items.values())
    # A deliberate barcode scan adds a previously removed product back.
    cart.suppressed = [value for value in cart.suppressed if value != product.id]
    db.session.commit()


def add_tags(cart, tags):
    if cart.status != 'scanning':
        raise ValueError('Checkout is not scanning')
    items = {item['product_id']: item for item in cart.items}
    notices = []
    for tag in set(tags):
        product = db.session.execute(db.select(Product).filter_by(epc=tag)).scalar_one_or_none()
        if product is None or product.archived:
            notices.append('Unknown product tag')
        elif product.id in cart.suppressed:
            continue
        elif product.stock < 1:
            notices.append('Product out of stock')
        elif product.id not in items:
            items[product.id] = dict(product_id=product.id, name=product.name,
                                     unit_cents=product.price_cents, quantity=1)
    cart.items = list(items.values())
    db.session.commit()
    return notices


def review(cart):
    if cart.status not in ('scanning', 'review') or not cart.items:
        raise ValueError('Cart is empty or unavailable')
    items = []
    for item in cart.items:
        product = db.session.get(Product, item['product_id'], populate_existing=True)
        quantity = item['quantity']
        if type(quantity) is not int or quantity < 1:
            raise ValueError('Invalid quantity')
        if not product or product.archived or product.stock < quantity:
            raise ValueError('Product out of stock')
        items.append(dict(product_id=product.id, name=product.name,
                          unit_cents=product.price_cents, quantity=quantity))
    cart.items = items
    cart.status = 'review'
    db.session.commit()


def finalize(cart, language='en'):
    """CAS checkout first, then conditional stock updates in a fixed order."""
    existing = db.session.execute(db.select(Purchase).filter_by(checkout_id=cart.id)).scalar_one_or_none()
    if existing:
        return existing
    cart_id, items, member = cart.id, list(cart.items), cart.customer_email
    if not items:
        raise ValueError('Cart is empty or unavailable')
    try:
        claimed = db.session.execute(update(Checkout).where(
            Checkout.id == cart_id, Checkout.status == 'payment',
        ).values(status='complete'))
        if claimed.rowcount != 1:
            db.session.rollback()
            existing = db.session.execute(db.select(Purchase).filter_by(checkout_id=cart_id)).scalar_one_or_none()
            if existing:
                return existing
            raise ValueError('Checkout is not ready for payment')
        for item in sorted(items, key=lambda i: i['product_id']):
            quantity = item['quantity']
            if type(quantity) is not int or quantity < 1:
                raise ValueError('Invalid quantity')
            changed = db.session.execute(update(Product).where(
                Product.id == item['product_id'], Product.archived.is_(False),
                Product.stock >= quantity, Product.price_cents == item['unit_cents'],
                Product.name == item['name'],
            ).values(stock=Product.stock - quantity))
            if changed.rowcount != 1:
                raise ValueError('Stock or price changed; review again')
        total = cart_total(cart)
        points = total // 100 if member else 0
        customer = db.session.get(Customer, member) if member else None
        purchase = Purchase(checkout_id=cart_id, customer_email=member,
                            recipient=customer.email if customer else None,
                            language=language, total_cents=total, points_earned=points,
                            receipt_status='pending' if customer else 'not_required')
        purchase.items = [PurchaseItem(**item) for item in items]
        db.session.add(purchase)
        if customer:
            db.session.execute(update(Customer).where(Customer.email == member).values(points=Customer.points + points))
        db.session.commit()
        return purchase
    except Exception:
        db.session.rollback()
        raise
