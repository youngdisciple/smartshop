from decimal import Decimal, InvalidOperation
import re
from sqlalchemy import update
from smartshop.extensions import db
from smartshop.models import Product, ProductTag, RemovedProductUnit, SoldProductUnit


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


def product_values(form, *, include_epc=True):
    result = {}
    for field, limit in (('name', 100), ('category', 60), ('producer', 100)):
        value = form.get(field, '').strip()
        if not value or len(value) > limit:
            raise ValueError('Invalid product details')
        result[field] = value
    result['upc'] = upc(form.get('upc', ''))
    if include_epc:
        result['epc'] = epc(form.get('epc', ''))
    try:
        price = Decimal(form.get('price', ''))
        if not price.is_finite() or not 0 < price <= Decimal('999999.99') or price * 100 != (price * 100).to_integral_value():
            raise ValueError('Invalid price')
        result['price_cents'] = int(price * 100)
    except (InvalidOperation, TypeError):
        raise ValueError('Invalid price') from None
    return result


def validate_catalog_epc(code):
    if db.session.get(ProductTag, code) is not None:
        raise ValueError('UPC or EPC already exists')


def register_rfid_unit(product, value):
    code = epc(value)
    validate_catalog_epc(code)
    if db.session.execute(db.select(Product.id).filter_by(epc=code)).first():
        raise ValueError('UPC or EPC already exists')
    product_id = product.id
    changed = db.session.execute(update(Product).where(
        Product.id == product_id, Product.archived.is_(False),
    ).values(stock=Product.stock + 1))
    if changed.rowcount != 1:
        raise ValueError('Product unavailable')
    last = db.session.execute(db.select(ProductTag.serial).filter_by(product_id=product_id)
                              .order_by(ProductTag.serial.desc()).limit(1).with_for_update()).scalar_one_or_none()
    removed = removed_rfid_serials(product_id, lock=True)
    serial = max(last or 1, max(removed, default=1)) + 1
    db.session.add(ProductTag(epc=code, product_id=product_id, serial=serial))
    db.session.commit()


def sold_rfid_serials(product_id, *, lock=False):
    query = db.select(SoldProductUnit.serial).filter_by(product_id=product_id)
    return set(db.session.scalars(query.with_for_update() if lock else query))


def removed_rfid_serials(product_id, *, lock=False):
    query = db.select(RemovedProductUnit.serial).filter_by(product_id=product_id)
    return set(db.session.scalars(query.with_for_update() if lock else query))


def remove_rfid_unit(product_id, serial):
    changed = db.session.execute(update(Product).where(
        Product.id == product_id, Product.archived.is_(False), Product.stock > 0,
    ).values(stock=Product.stock - 1))
    if changed.rowcount != 1:
        raise ValueError('RFID unit is not in stock')
    unit = None
    if serial != 1:
        unit = db.session.scalars(db.select(ProductTag).filter_by(
            product_id=product_id, serial=serial).with_for_update()).one_or_none()
        if unit is None:
            raise ValueError('Unknown product tag')
    if serial in sold_rfid_serials(product_id, lock=True) or serial in removed_rfid_serials(product_id, lock=True):
        raise ValueError('RFID unit is not in stock')
    if unit is None:
        db.session.execute(update(Product).where(Product.id == product_id).values(epc=Product.vacant_primary_key(product_id)))
    else:
        db.session.delete(unit)
    db.session.add(RemovedProductUnit(product_id=product_id, serial=serial))
    db.session.commit()
