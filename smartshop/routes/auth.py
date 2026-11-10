import re
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from smartshop.extensions import db
from smartshop.models import Customer
from smartshop.security import login_required, owner
from smartshop.presentation.i18n import tr

auth = Blueprint('auth', __name__, url_prefix='/auth')


def rotate_session(email=None):
    runtime = current_app.extensions['smartshop']
    runtime.membership.cancel_owner(owner())
    runtime.reader.cancel_owner(owner())
    language = session.get('language', 'en')
    session.clear()
    session['language'] = language
    if email:
        session['email'] = email
    owner()


@auth.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        name = request.form.get('name', '').strip()
        address = request.form.get('address', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        error = None
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or not 8 <= len(email) <= 50:
            error = 'Invalid email'
        elif not 1 <= len(name) <= 50 or not 1 <= len(address) <= 100 or len(phone) > 15:
            error = 'Invalid customer details'
        elif password != request.form.get('confirm_password'):
            error = 'Passwords do not match'
        elif not 6 <= len(password) <= 128:
            error = 'Use 6 to 128 password characters'
        elif db.session.get(Customer, email):
            error = 'Email already exists'
        if not error:
            try:
                db.session.add(Customer(email, generate_password_hash(password), name, address, phone))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                error = 'Email already exists'
        if error:
            flash(tr(error), 'error')
        else:
            rotate_session(email)
            flash(tr('Account created'), 'success')
            return redirect(url_for('shop.account'))
    return render_template('auth/signup.html')


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        customer = db.session.get(Customer, request.form.get('email', '').strip().lower())
        if customer and check_password_hash(customer.password, request.form.get('password', '')):
            rotate_session(customer.email)
            flash(tr('Signed in'), 'success')
            return redirect(url_for('shop.account'))
        flash(tr('Invalid email or password'), 'error')
    return render_template('auth/login.html')


@auth.post('/logout')
@login_required
def logout():
    rotate_session()
    flash(tr('Signed out'), 'success')
    return redirect(url_for('auth.login'))
