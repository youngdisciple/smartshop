from .admin import admin
from .auth import auth
from .dashboard import dashboard


def register_routes(app):
    for blueprint in (admin, auth, dashboard):
        app.register_blueprint(blueprint)
