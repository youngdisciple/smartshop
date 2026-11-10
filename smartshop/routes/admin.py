from flask import Blueprint, render_template
from smartshop.extensions import db
from smartshop.models import Customer

admin = Blueprint("admin", __name__, url_prefix="/admin")


@admin.route("/")
def index_customer():
    customers = db.session.execute(db.select(Customer).order_by(Customer.name)).scalars().all()
    return render_template("admin/index.html", customers=customers)
