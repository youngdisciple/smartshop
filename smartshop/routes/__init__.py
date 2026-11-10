from .admin import admin
from .auth import auth
from .dashboard import dashboard
from .shop import shop


def register_routes(app):
    for blueprint in (admin, auth, dashboard, shop):
        app.register_blueprint(blueprint)
