"""Additive migrations for customer records and RFID inventory."""
from uuid import uuid4
from sqlalchemy import inspect, text
from smartshop.extensions import db
from smartshop import models  # register every table


def migrate():
    engine = db.engine
    if engine.dialect.name not in ('sqlite', 'mysql'):
        raise ValueError('Migration supports SQLite and MySQL')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)'))
        if inspect(connection).has_table('customer'):
            columns = {column['name'] for column in inspect(connection).get_columns('customer')}
            for name, definition in (
                ('membership_number', 'VARCHAR(32)'),
                ('points', 'INTEGER NOT NULL DEFAULT 0'),
                ('is_admin', 'BOOLEAN NOT NULL DEFAULT 0'),
            ):
                if name not in columns:
                    connection.execute(text(f'ALTER TABLE customer ADD COLUMN {name} {definition}'))
            rows = connection.execute(text('SELECT email FROM customer WHERE membership_number IS NULL')).all()
            for row in rows:
                connection.execute(text('UPDATE customer SET membership_number=:number WHERE email=:email'),
                                   {'number': uuid4().hex.upper(), 'email': row.email})
            indexes = inspect(connection).get_indexes('customer')
            constraints = inspect(connection).get_unique_constraints('customer')
            if not any(i['column_names'] == ['membership_number'] for i in indexes + constraints):
                connection.execute(text('CREATE UNIQUE INDEX uq_customer_membership ON customer (membership_number)'))
            if engine.dialect.name == 'mysql':
                membership = next(c for c in inspect(connection).get_columns('customer') if c['name'] == 'membership_number')
                if membership['nullable']:
                    connection.execute(text('ALTER TABLE customer MODIFY membership_number VARCHAR(32) NOT NULL'))
            else:
                # SQLite cannot add NOT NULL to a populated column. Triggers
                # enforce equivalent behavior without rebuilding legacy data.
                for action in ('INSERT', 'UPDATE'):
                    connection.execute(text(f'''CREATE TRIGGER IF NOT EXISTS customer_valid_{action.lower()}
                        BEFORE {action} ON customer
                        WHEN NEW.membership_number IS NULL OR NEW.points < 0
                        BEGIN SELECT RAISE(ABORT, 'Invalid membership or points'); END'''))
    db.create_all()
    with engine.begin() as connection:
        if not connection.execute(text('SELECT version FROM schema_version WHERE version=1')).first():
            connection.execute(text('INSERT INTO schema_version (version) VALUES (1)'))
        if not connection.execute(text('SELECT version FROM schema_version WHERE version=2')).first():
            connection.execute(text('''
                UPDATE product SET stock = 1 + (
                    SELECT COUNT(*) FROM product_tag WHERE product_tag.product_id = product.id
                )
            '''))
            connection.execute(text('INSERT INTO schema_version (version) VALUES (2)'))
        if not connection.execute(text('SELECT version FROM schema_version WHERE version=3')).first():
            primary_removals = connection.execute(text(
                'SELECT product_id FROM removed_product_unit WHERE serial = 1'
            )).scalars().all()
            if primary_removals:
                connection.execute(text('UPDATE product SET epc = :epc WHERE id = :id'), [
                    {'epc': models.Product.vacant_primary_key(product_id), 'id': product_id}
                    for product_id in primary_removals
                ])
            connection.execute(text('''
                DELETE FROM product_tag WHERE EXISTS (
                    SELECT 1 FROM removed_product_unit
                    WHERE removed_product_unit.product_id = product_tag.product_id
                      AND removed_product_unit.serial = product_tag.serial
                )
            '''))
            connection.execute(text('INSERT INTO schema_version (version) VALUES (3)'))
        if not connection.execute(text('SELECT version FROM schema_version WHERE version=4')).first():
            columns = {column['name'] for column in inspect(connection).get_columns('product')}
            if 'added_on' not in columns:
                connection.execute(text('ALTER TABLE product ADD COLUMN added_on DATE'))
            connection.execute(text('INSERT INTO schema_version (version) VALUES (4)'))
        if not connection.execute(text('SELECT version FROM schema_version WHERE version=5')).first():
            columns = {column['name'] for column in inspect(connection).get_columns('product_tag')}
            if 'added_on' not in columns:
                connection.execute(text('ALTER TABLE product_tag ADD COLUMN added_on DATE'))
            connection.execute(text('INSERT INTO schema_version (version) VALUES (5)'))
