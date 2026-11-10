"""Explicit migration, administrator provisioning and verified four-tag setup."""
import argparse
import json
from smartshop import create_app
from smartshop.extensions import db
from smartshop.models import Customer, Product
from smartshop.services.catalog import product_values
from smartshop.services.migrations import migrate

SUFFIXES = ['4965', '4970', '4968', '4951']


def seed_verified(path):
    """Input must attest reader verification; never guess EPCs from suffixes."""
    with open(path, encoding='utf-8') as source:
        data = json.load(source)
    if not isinstance(data, dict) or data.get('reader_verified') is not True or len(data.get('products', [])) != 4:
        raise ValueError('Supply four products and reader_verified=true after physical confirmation')
    values = [product_values(row) for row in data['products']]
    if any(not row['epc'].endswith(suffix) for row, suffix in zip(values, SUFFIXES)):
        raise ValueError('Product order must match suffixes 4965, 4970, 4968, 4951')
    if len({v['epc'] for v in values}) != 4 or len({v['upc'] for v in values}) != 4:
        raise ValueError('All four EPCs and UPCs must be unique')
    try:
        for row in values:
            existing = db.session.execute(db.select(Product).filter_by(epc=row['epc'])).scalar_one_or_none()
            if existing:
                if any(getattr(existing, key) != value for key, value in row.items()):
                    raise ValueError('Existing mapping differs; use product administration to edit')
            else:
                db.session.add(Product(**row))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admin-email', help='Promote an existing account; never changes its password')
    parser.add_argument('--verified-products', help='JSON with reader-verified EPCs and actual product metadata')
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        migrate()
        if args.admin_email:
            customer = db.session.get(Customer, args.admin_email.strip().lower())
            if customer is None:
                parser.error('Create this customer account first')
            customer.is_admin = True
            db.session.commit()
        if args.verified_products:
            seed_verified(args.verified_products)
    print('Schema/setup complete; no stock is added by tag registration.')


if __name__ == '__main__':
    main()
