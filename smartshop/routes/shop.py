"""Catalog administration, private accounts and browser-owned self-checkout."""
from functools import wraps
from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from smartshop.extensions import db
from smartshop.models import Checkout, Customer, MembershipCard, Product, Purchase, PurchaseItem, Reception
from smartshop.security import admin_required, login_required, owner
from smartshop.presentation.i18n import tr
from smartshop.services.catalog import product_values, receive, upc
from smartshop.services.checkout import add_tags, finalize, review
from smartshop.services.receipts import deliver

shop = Blueprint('shop', __name__)


def runtime():
    return current_app.extensions['smartshop']


def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with runtime().checkout_lock:
            return function(*args, **kwargs)
    return wrapped


def cart_for(cart_id):
    cart = db.get_or_404(Checkout, cart_id)
    if cart.owner != owner():
        abort(404)
    return cart


def notify(message):
    flash(tr(message), 'success')


@shop.post('/language')
def language():
    session['language'] = 'fr' if request.form.get('language') == 'fr' else 'en'
    # Only a local path, never an arbitrary redirect URL.
    target = request.form.get('next', '/')
    if not target.startswith('/') or target.startswith('//') or '\\' in target:
        target = '/'
    return redirect(target)


@shop.get('/products')
@admin_required
def products():
    products = db.session.execute(db.select(Product).order_by(Product.name)).scalars().all()
    return render_template('shop/products.html', products=products)


@shop.route('/products/new', methods=['GET', 'POST'])
@shop.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@admin_required
@serialized
def product_edit(product_id=None):
    product = db.get_or_404(Product, product_id) if product_id else None
    if request.method == 'POST':
        try:
            values = product_values(request.form)
            if product is None:
                product = Product(**values)
                db.session.add(product)
            else:
                for key, value in values.items():
                    setattr(product, key, value)
            db.session.commit()
            runtime().reader.cancel_owner(owner())
            notify('Product saved')
            return redirect(url_for('shop.products'))
        except (ValueError, IntegrityError) as error:
            db.session.rollback()
            flash(tr(str(error) if isinstance(error, ValueError) else 'UPC or EPC already exists'), 'error')
    return render_template('shop/product.html', product=product)


@shop.post('/products/<int:product_id>/delete')
@admin_required
@serialized
def product_delete(product_id):
    product = db.get_or_404(Product, product_id)
    used = db.session.execute(db.select(Reception.id).filter_by(product_id=product_id).limit(1)).first()
    sold = db.session.execute(db.select(PurchaseItem.id).filter_by(product_id=product_id).limit(1)).first()
    if used or sold:
        product.archived = True
        notify('Product archived')
    else:
        db.session.delete(product)
        notify('Product deleted')
    db.session.commit()
    return redirect(url_for('shop.products'))


@shop.route('/inventory/<int:product_id>', methods=['GET', 'POST'])
@admin_required
@serialized
def inventory(product_id):
    product = db.get_or_404(Product, product_id)
    if request.method == 'POST':
        try:
            receive(product_id, request.form.get('quantity'), request.form.get('received_on'))
            notify('Stock received')
            return redirect(url_for('shop.inventory', product_id=product_id))
        except ValueError as error:
            db.session.rollback()
            flash(tr(str(error)), 'error')
    receptions = db.session.execute(db.select(Reception).filter_by(product_id=product_id).order_by(Reception.received_on.desc())).scalars().all()
    return render_template('shop/inventory.html', product=product, receptions=receptions)


@shop.get('/products/lookup')
@admin_required
def lookup():
    try:
        code = upc(request.args.get('upc', ''))
    except ValueError as error:
        return jsonify(error=tr(str(error))), 400
    product = db.session.execute(db.select(Product).filter_by(upc=code, archived=False)).scalar_one_or_none()
    if not product:
        return jsonify(error=tr('Unknown UPC')), 404
    return jsonify(id=product.id, name=product.name, upc=product.upc, price_cents=product.price_cents)


@shop.get('/account')
@login_required
def account():
    purchases = db.session.execute(db.select(Purchase).filter_by(customer_email=g.customer.email).order_by(Purchase.created_at.desc())).scalars().all()
    card = db.session.execute(db.select(MembershipCard).filter_by(customer_email=g.customer.email)).scalar_one_or_none()
    return render_template('shop/account.html', purchases=purchases, card=card)


@shop.route('/account/card', methods=['GET', 'POST'])
@login_required
@serialized
def enrollment():
    operation_id = session.get('enrollment')
    uid = None
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'start':
                operation_id = runtime().membership.arm(owner(), 'enroll')
                session['enrollment'] = operation_id
                session['replace_card'] = request.form.get('replace') == 'yes'
                notify('Present a membership card')
            elif action == 'cancel':
                runtime().membership.cancel_owner(owner())
                session.pop('enrollment', None)
                notify('Operation cancelled')
                return redirect(url_for('shop.account'))
            elif action == 'confirm':
                uid = runtime().membership.result(owner(), operation_id, 'enroll')
                if not uid:
                    raise ValueError('Present a membership card')
                assigned = db.session.get(MembershipCard, uid)
                if assigned and assigned.customer_email != g.customer.email:
                    raise ValueError('Card belongs to another customer')
                old = db.session.execute(db.select(MembershipCard).filter_by(customer_email=g.customer.email)).scalar_one_or_none()
                if old and old.uid != uid:
                    if not session.get('replace_card'):
                        raise ValueError('Confirm card replacement')
                    db.session.delete(old)
                    db.session.flush()
                if not assigned:
                    db.session.add(MembershipCard(uid=uid, customer_email=g.customer.email))
                db.session.commit()
                runtime().membership.cancel_owner(owner())
                session.pop('enrollment', None)
                notify('Membership card linked')
                return redirect(url_for('shop.account'))
            else:
                abort(400)
        except (ValueError, IntegrityError) as error:
            db.session.rollback()
            flash(tr(str(error) if isinstance(error, ValueError) else 'Card belongs to another customer'), 'error')
    if operation_id:
        try:
            uid = runtime().membership.result(owner(), operation_id, 'enroll')
        except ValueError as error:
            flash(tr(str(error)), 'error')
            session.pop('enrollment', None)
            operation_id = None
    return render_template('shop/enrollment.html', operation_id=operation_id, uid=uid)


@shop.get('/account/card/status')
@login_required
def enrollment_status():
    try:
        uid = runtime().membership.result(owner(), session.get('enrollment'), 'enroll')
        return jsonify(ready=bool(uid), message=tr('Card ready to confirm' if uid else 'Present a membership card'))
    except ValueError as error:
        return jsonify(ready=False, message=tr(str(error))), 409


@shop.route('/checkout', methods=['GET', 'POST'])
@serialized
def checkout_start():
    if request.method == 'POST':
        runtime().reader.cancel_owner(owner())
        runtime().membership.cancel_owner(owner())
        # Abandon prior open carts for this browser.
        db.session.execute(db.update(Checkout).where(Checkout.owner == owner(), Checkout.status.in_(['scanning', 'review', 'payment'])).values(status='cancelled'))
        cart = Checkout(owner=owner())
        db.session.add(cart)
        db.session.commit()
        return redirect(url_for('shop.cart', cart_id=cart.id))
    return render_template('shop/start.html')


@shop.route('/checkout/<cart_id>', methods=['GET', 'POST'])
@serialized
def cart(cart_id):
    cart = cart_for(cart_id)
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'scan' and cart.status == 'scanning':
                operation = runtime().reader.arm(owner(), 'checkout:' + cart.id)
                session['product_operation'] = operation['id']
                notify('Product scan started')
            elif action in ('remove', 'restore') and cart.status == 'scanning':
                product_id = int(request.form.get('product_id', '0'))
                if action == 'remove':
                    cart.items = [item for item in cart.items if item['product_id'] != product_id]
                    cart.suppressed = list(set(cart.suppressed + [product_id]))
                else:
                    product = db.get_or_404(Product, product_id)
                    cart.suppressed = [value for value in cart.suppressed if value != product_id]
                    add_tags(cart, [product.epc])
                db.session.commit()
                notify('Cart updated')
            elif action == 'review':
                review(cart)
                runtime().reader.cancel_owner(owner())
                notify('Review your purchase')
            elif action == 'back' and cart.status in ('review', 'payment'):
                cart.status = 'scanning'
                cart.customer_email = None
                runtime().membership.cancel_owner(owner())
                db.session.commit()
                notify('Cart updated')
            elif action == 'cancel':
                if cart.status != 'complete':
                    cart.status = 'cancelled'
                    db.session.commit()
                runtime().reader.cancel_owner(owner())
                runtime().membership.cancel_owner(owner())
                notify('Operation cancelled')
            elif action == 'member' and cart.status == 'review':
                session['checkout_membership'] = runtime().membership.arm(owner(), 'checkout')
                session['membership_cart'] = cart.id
                notify('Present a membership card')
            elif action == 'confirm_member' and cart.status == 'review':
                uid = selected_uid(cart)
                card = db.session.get(MembershipCard, uid) if uid else None
                if not card:
                    raise ValueError('Unknown membership card')
                cart.customer_email = card.customer_email
                db.session.commit()
                runtime().membership.cancel_owner(owner())
                notify('Membership confirmed')
            elif action == 'guest' and cart.status == 'review':
                cart.customer_email = None
                runtime().membership.cancel_owner(owner())
                db.session.commit()
                notify('Guest checkout selected')
            elif action == 'payment' and cart.status == 'review':
                runtime().reader.cancel_owner(owner())
                runtime().membership.cancel_owner(owner())
                cart.status = 'payment'
                db.session.commit()
                return redirect(url_for('shop.payment', cart_id=cart.id))
            else:
                raise ValueError('Invalid operation')
        except ValueError as error:
            db.session.rollback()
            flash(tr(str(error)), 'error')
        return redirect(url_for('shop.cart', cart_id=cart.id))
    if cart.status == 'complete':
        purchase = db.session.execute(db.select(Purchase).filter_by(checkout_id=cart.id)).scalar_one()
        return redirect(url_for('shop.receipt', purchase_id=purchase.id))
    member = db.session.get(Customer, cart.customer_email) if cart.customer_email else None
    candidate = None
    try:
        uid = selected_uid(cart)
        card = db.session.get(MembershipCard, uid) if uid else None
        candidate = card.customer.membership_number if card else None
    except ValueError:
        pass
    suppressed = db.session.execute(db.select(Product).where(Product.id.in_(cart.suppressed))).scalars().all() if cart.suppressed else []
    return render_template('shop/cart.html', cart=cart, total=sum(item['unit_cents'] for item in cart.items),
                           member=member, candidate=candidate, suppressed=suppressed)


def selected_uid(cart):
    if session.get('membership_cart') != cart.id:
        raise ValueError('Scan expired or cancelled')
    return runtime().membership.result(owner(), session.get('checkout_membership'), 'checkout')


@shop.post('/checkout/<cart_id>/poll')
@serialized
def cart_poll(cart_id):
    cart = cart_for(cart_id)
    messages = []
    if cart.status == 'scanning':
        try:
            tags = runtime().reader.poll(owner(), session.get('product_operation'))
            messages = add_tags(cart, tags)
        except ValueError as error:
            messages = [str(error)]
    else:
        try:
            uid = selected_uid(cart)
            if uid:
                card = db.session.get(MembershipCard, uid)
                messages = ['Card ready to confirm' if card else 'Unknown membership card']
        except ValueError as error:
            messages = [str(error)]
    return jsonify(items=cart.items, total_cents=sum(item['unit_cents'] for item in cart.items), messages=[tr(m) for m in messages])


@shop.route('/checkout/<cart_id>/payment', methods=['GET', 'POST'])
@serialized
def payment(cart_id):
    cart = cart_for(cart_id)
    if request.method == 'POST':
        outcome = request.form.get('outcome')
        if outcome == 'success':
            try:
                purchase = finalize(cart, session.get('language', 'en'))
                deliver(purchase.id, current_app.config)
                notify('Purchase completed')
                return redirect(url_for('shop.receipt', purchase_id=purchase.id))
            except (ValueError, SQLAlchemyError) as error:
                db.session.rollback()
                if cart.status == 'payment':
                    cart.status = 'review'
                    db.session.commit()
                flash(tr(str(error) if isinstance(error, ValueError) else 'Purchase could not be saved'), 'error')
        elif outcome in ('failure', 'cancel') and cart.status == 'payment':
            cart.status = 'review'
            db.session.commit()
            notify('Payment failed' if outcome == 'failure' else 'Payment cancelled')
        else:
            abort(400)
        return redirect(url_for('shop.cart', cart_id=cart.id))
    if cart.status != 'payment':
        return redirect(url_for('shop.cart', cart_id=cart.id))
    return render_template('shop/payment.html', cart=cart, total=sum(i['unit_cents'] for i in cart.items))


def authorized_receipt(purchase_id):
    purchase = db.get_or_404(Purchase, purchase_id)
    checkout = db.session.get(Checkout, purchase.checkout_id)
    if checkout.owner != owner() and (not g.customer or purchase.customer_email != g.customer.email):
        abort(404)
    return purchase


@shop.get('/receipts/<purchase_id>')
def receipt(purchase_id):
    return render_template('shop/receipt.html', purchase=authorized_receipt(purchase_id))


@shop.post('/receipts/<purchase_id>/retry')
def receipt_retry(purchase_id):
    purchase = authorized_receipt(purchase_id)
    deliver(purchase.id, current_app.config)
    notify('Receipt delivery updated')
    return redirect(url_for('shop.receipt', purchase_id=purchase.id))


@shop.post('/reader/product/start')
@admin_required
def capture_start():
    try:
        operation = runtime().reader.arm(owner(), 'registration')
        session['capture_operation'] = operation['id']
        return jsonify(operation_id=operation['id'])
    except ValueError as error:
        return jsonify(error=tr(str(error))), 409


@shop.post('/reader/product/result')
@admin_required
def capture_result():
    try:
        tags = runtime().reader.poll(owner(), session.get('capture_operation'))
        return jsonify(tags=tags)
    except ValueError as error:
        return jsonify(error=tr(str(error))), 409


@shop.post('/reader/product/cancel')
@admin_required
def capture_cancel():
    runtime().reader.cancel_owner(owner())
    return jsonify(message=tr('Operation cancelled'))


@shop.post('/reader/fake')
@serialized
def fake_input():
    if not current_app.config.get('FAKE_READERS_ENABLED'):
        abort(404)
    operation = runtime().reader.operation
    if not operation or operation['owner'] != owner():
        abort(409)
    tags = request.form.get('tags', '').split()
    if len(tags) > 50:
        abort(400)
    runtime().reader.adapter.reads.extend(tags)
    return jsonify(message=tr('Development tags queued'))
