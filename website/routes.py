from website import app, db
from website.models import Customer

def init_routes():
    @app.route("/customers")
    def customerIndex():
        users = db.session.execute(db.select(Customer).order_by(Customer.name)).scalars().all()
        return f"{users}"
