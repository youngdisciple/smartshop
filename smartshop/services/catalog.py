from datetime import date
from decimal import Decimal, InvalidOperation
import re
from sqlalchemy import update
from smartshop.extensions import db
from smartshop.models import Product, Reception


def epc(value):
    value = str(value).strip().upper()
    if not re.fullmatch(r'(?:[0-9A-F]{2}){1,12}', value):
        raise ValueError('Invalid EPC')
    return value


def upc(value):
    value = str(value).strip()  # keyboard scanner CR/LF terminator
    if not re.fullmatch(r'[0-9]{1,13}', value):
        raise ValueError('Invalid UPC')
    return value


def product_values(form):
    result = {}
    for field, limit in (('name', 100), ('category', 60), ('producer', 100)):
        value = form.get(field, '').strip()
        if not value or len(value) > limit:
            raise ValueError('Invalid product details')
        result[field] = value
    result['epc'], result['upc'] = epc(form.get('epc', '')), upc(form.get('upc', ''))
    try:
        price = Decimal(form.get('price', ''))
        if not price.is_finite() or not 0 < price <= Decimal('999999.99') or price * 100 != (price * 100).to_integral_value():
            raise ValueError('Invalid price')
        result['price_cents'] = int(price * 100)
    except (InvalidOperation, TypeError):
        raise ValueError('Invalid price') from None
    return result


def receive(product_id, quantity, received_on):
    if not re.fullmatch(r'[0-9]{1,7}', str(quantity)) or not 0 < int(quantity) <= 1000000:
        raise ValueError('Invalid quantity')
    try:
        received = date.fromisoformat(received_on)
        if received > date.today():
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Invalid date') from None
    changed = db.session.execute(update(Product).where(
        Product.id == product_id, Product.archived.is_(False),
        Product.stock <= 2000000000 - int(quantity),
    ).values(stock=Product.stock + int(quantity)))
    if changed.rowcount != 1:
        raise ValueError('Product unavailable')
    db.session.add(Reception(product_id=product_id, quantity=int(quantity), received_on=received))
    db.session.commit()
