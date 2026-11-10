"""Explicit additive v1 migration, preserving original customer rows/hashes."""
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
