from .admin import admin
from .auth import auth
from .dashboard import dashboard
from .shop import shop
from .ble import ble


def register_routes(app):
    for blueprint in (admin, auth, dashboard, shop, ble):
        app.register_blueprint(blueprint)
