"""Disposable browser fixture; start only with python -m tests.browser_server."""
import json
from types import SimpleNamespace
from flask import jsonify
from werkzeug.security import generate_password_hash
from smartshop import create_app
from smartshop.extensions import db
from smartshop.models import Customer


def main():
    app = create_app({'TESTING': True, 'SECRET_KEY': 'disposable-browser-fixture',
                      'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'FAKE_READERS_ENABLED': True, 'PRODUCT_READER_BACKEND': 'disabled',
                      'FRIDGE_SERVICES_ENABLED': False, 'GMAIL_SERVICE_ENABLED': False,
                      'MEMBERSHIP_SERVICE_ENABLED': False, 'RESEND_API_KEY': None})
    reader = app.extensions['smartshop'].membership
    def send(kind, value):
        reader.on_message(None, None, SimpleNamespace(topic=reader.topic + kind, payload=json.dumps(value).encode(), retain=False))
    @app.before_request
    def heartbeat():
        reader.connected = True
        send('/status', {'v': 1, 'reader_epoch': 'browser-fixture', 'online': True})
    @app.post('/__test/card')
    def fake_card():
        send('/event', {'v': 1, 'reader_epoch': 'browser-fixture', 'operation_id': reader.operation['id'],
                        'event_id': 'browser-event', 'uid': '00010203'})
        return jsonify(ok=True)
    with app.app_context():
        db.create_all()
        admin = Customer('admin@example.test', generate_password_hash('fixture12'), 'Development admin', '1 Test', '')
        admin.is_admin = True
        db.session.add(admin)
        db.session.commit()
    app.run(host='127.0.0.1', port=5093, debug=False, threaded=False)


if __name__ == '__main__':
    main()
