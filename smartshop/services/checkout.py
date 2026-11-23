"""Transactional checkout; no device or email operations inside a sale."""
from sqlalchemy import update
from smartshop.extensions import db
from smartshop.models import Checkout, Customer, Product, ProductTag, Purchase, PurchaseItem, SoldProductUnit
from smartshop.services.catalog import removed_rfid_serials, sold_rfid_serials, upc


def cart_total(cart):
    return sum(item['unit_cents'] * item['quantity'] for item in cart.items)


def remove_product(cart, product_id):
    prefix = f'removed:{product_id}:'
    removed_units = [prefix + str(serial) for item in cart.items if item['product_id'] == product_id
                     for serial in item.get('rfid_serials', [])]
    cart.items = [item for item in cart.items if item['product_id'] != product_id]
    cart.suppressed = list(dict.fromkeys([*cart.suppressed, product_id, *removed_units]))
    db.session.commit()


def restore_product(cart, product):
    product_id = product.id
    prefix = f'removed:{product_id}:'
    markers = [value for value in cart.suppressed if isinstance(value, str) and value.startswith(prefix)]
    serials = [int(value.removeprefix(prefix)) for value in markers]
    cart.suppressed = [value for value in cart.suppressed if value != product_id and value not in markers]
    if serials:
        epcs = {1: product.primary_epc, **{unit.serial: unit.epc for unit in product.rfid_units}}
        if any(not epcs.get(serial) for serial in serials):
            raise ValueError('RFID unit was removed from stock')
        return add_tags(cart, [epcs[serial] for serial in serials])
    add_barcode(cart, product.upc)
    return []


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
        remove_product(cart, product_id)
        return
    serials = item.get('rfid_serials', [])
    if quantity < len(serials):
        cart.suppressed = [*cart.suppressed, f'{product_id}:{serials[-1]}']
        item['rfid_serials'] = serials[:-1]
    if delta > 0:
        product = db.session.get(Product, product_id, populate_existing=True)
        if not product or product.archived or product.stock < quantity:
            raise ValueError('Product out of stock')
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
    prefix = f'removed:{product.id}:'
    cart.suppressed = [value for value in cart.suppressed
                       if value != product.id and not (isinstance(value, str) and value.startswith(prefix))]
    db.session.commit()


def add_tags(cart, tags):
    if cart.status != 'scanning':
        raise ValueError('Checkout is not scanning')
    items = {item['product_id']: item for item in cart.items}
    notices = []
    for tag in dict.fromkeys(tags):
        unit = db.session.get(ProductTag, tag)
        product = (db.session.get(Product, unit.product_id) if unit else
                   db.session.execute(db.select(Product).filter_by(epc=tag)).scalar_one_or_none())
        if product is None or product.archived:
            notices.append('Unknown product tag')
        elif product.id in cart.suppressed:
            continue
        elif product.stock < 1:
            notices.append('Product out of stock')
        else:
            item = items.get(product.id, dict(product_id=product.id, name=product.name,
                                              unit_cents=product.price_cents, quantity=0))
            serial = unit.serial if unit else 1
            if db.session.get(SoldProductUnit, (product.id, serial)) is not None:
                notices.append('RFID unit already sold')
                continue
            serials = item.get('rfid_serials', [])
            if serial in serials or f'{product.id}:{serial}' in cart.suppressed:
                continue
            if len(serials) >= product.stock:
                notices.append('Product out of stock')
                continue
            serials = sorted([*serials, serial])
            items[product.id] = dict(item, rfid_serials=serials, quantity=max(item['quantity'], len(serials)))
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
        scanned = set(item.get('rfid_serials', []))
        if scanned:
            if scanned & removed_rfid_serials(product.id):
                raise ValueError('RFID unit was removed from stock')
            if scanned & sold_rfid_serials(product.id):
                raise ValueError('RFID unit already sold')
        items.append(dict(item, name=product.name, unit_cents=product.price_cents))
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
        sold_units = []
        for item in sorted(items, key=lambda i: i['product_id']):
            product_id = item['product_id']
            quantity = item['quantity']
            if type(quantity) is not int or quantity < 1:
                raise ValueError('Invalid quantity')
            changed = db.session.execute(update(Product).where(
                Product.id == product_id, Product.archived.is_(False),
                Product.stock >= quantity, Product.price_cents == item['unit_cents'],
                Product.name == item['name'],
            ).values(stock=Product.stock - quantity))
            if changed.rowcount != 1:
                raise ValueError('Stock or price changed; review again')
            tags = db.session.scalars(db.select(ProductTag.serial).filter_by(product_id=product_id)
                                      .order_by(ProductTag.serial).with_for_update()).all()
            sold = sold_rfid_serials(product_id, lock=True)
            removed = removed_rfid_serials(product_id, lock=True)
            unavailable = sold | removed
            available = [serial for serial in (1, *tags) if serial not in unavailable]
            scanned = item.get('rfid_serials', [])
            if removed.intersection(scanned):
                raise ValueError('RFID unit was removed from stock')
            if not set(scanned).issubset(available):
                raise ValueError('RFID unit already sold')
            chosen = scanned + [serial for serial in available if serial not in scanned][:quantity - len(scanned)]
            if len(chosen) != quantity:
                raise ValueError('Stock or price changed; review again')
            sold_units.extend((product_id, serial) for serial in chosen)
        total = cart_total(cart)
        points = total // 100 if member else 0
        customer = db.session.get(Customer, member) if member else None
        purchase = Purchase(checkout_id=cart_id, customer_email=member,
                            recipient=customer.email if customer else None,
                            language=language, total_cents=total, points_earned=points,
                            receipt_status='pending' if customer else 'not_required')
        purchase.items = [PurchaseItem(product_id=item['product_id'], name=item['name'],
                                       unit_cents=item['unit_cents'], quantity=item['quantity'])
                          for item in items]
        db.session.add(purchase)
        db.session.flush()
        db.session.add_all(SoldProductUnit(product_id=product_id, serial=serial, purchase_id=purchase.id)
                           for product_id, serial in sold_units)
        if customer:
            db.session.execute(update(Customer).where(Customer.email == member).values(points=Customer.points + points))
        db.session.commit()
        return purchase
    except Exception:
        db.session.rollback()
        raise
