from flask import Blueprint, redirect, render_template, request, flash, url_for
from werkzeug.security import generate_password_hash, check_password_hash
# from scripts.phase1 import printToLed

from website import app, db
from website.esp32Controller import set_threshold, start, get_fridges, thresholds
from website.models import Customer
import fan_controller
#start
start()

# Blueprints
admin = Blueprint('admin', __name__, url_prefix='/admin')
auth = Blueprint('auth', __name__, url_prefix='/auth')

# admin
@admin.route("/")
def indexCustomer():
    customers = db.session.execute(db.select(Customer).order_by(Customer.name)).scalars().all()
    data = {"customers":  customers}
    return "ok"

# auth
@auth.route("/signup", methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        name = request.form['name']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        address = request.form['address']
        phone = request.form['phone']

        customer = Customer.query.filter_by(email=email).first()
        if customer:
            flash('Email Already Exists')
        elif len(email) < 8:
            flash('Email must be greater than 8 characters.')
        elif len(name) < 1:
            flash('First name must be greater than 1 characters.')
        elif password != confirm_password:
            flash('Password don\'t match')
        elif len(password) < 6:
            flash('Password must be atleast 6 characters.')
        else:
            customer = Customer(email=email, name=name, password=generate_password_hash(password=password), address=address, phone=phone)
            db.session.add(customer)
            db.session.commit()
            flash('Account created!', category='success')
            # printToLed(1)
            return render_template("auth/signup.html")

        # printToLed(2)
        return render_template("auth/signup.html")

    return render_template("auth/signup.html")

@app.route("/dashboard")
def dashboard():
    return render_template(
        "dashboard/dashboard.html",
        fridges=get_fridges(),
        thresholds=thresholds,
        motor_on=fan_controller.fan_is_on
    )

@app.route("/thresholds/<int:fridge_id>", methods=['POST'])
def save_threshold(fridge_id):
    threshold = float(request.form['threshold'])
 
    if -10 <= threshold <= 50:
        set_threshold(fridge_id, threshold)
 
    return redirect(url_for('dashboard'))