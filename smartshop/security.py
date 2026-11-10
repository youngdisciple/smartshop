"""Session ownership, CSRF and role checks shared by all routes."""
from functools import wraps
import secrets
from flask import abort, g, redirect, request, session, url_for
from smartshop.extensions import db
from smartshop.models import Customer


def owner():
    if 'sid' not in session:
        session['sid'] = secrets.token_hex(16)
    return session['sid']


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(32)
    return session['csrf']


def login_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if g.customer is None:
            return redirect(url_for('auth.login'))
        return function(*args, **kwargs)
    return wrapped


def admin_required(function):
    @wraps(function)
    @login_required
    def wrapped(*args, **kwargs):
        if not g.customer.is_admin:
            abort(403)
        return function(*args, **kwargs)
    return wrapped


def install_security(app):
    @app.before_request
    def protect():
        g.customer = db.session.get(Customer, session['email']) if session.get('email') else None
        owner()
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            expected = session.get('csrf', '')
            supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            if not expected or not secrets.compare_digest(expected.encode(), supplied.encode()):
                abort(400, description='Invalid CSRF token')

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response

    app.jinja_env.globals['csrf_token'] = csrf_token
