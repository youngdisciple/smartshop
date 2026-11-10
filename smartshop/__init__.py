from flask import Flask
from .config import load_config
from .extensions import db
from .routes import register_routes
from .runtime import Runtime


def create_app(config_overrides=None):
    """Build an application without starting devices, workers, or database I/O."""
    app = Flask(__name__)
    app.config.update(load_config())
    if config_overrides:
        app.config.update(config_overrides)
    db.init_app(app)
    register_routes(app)
    app.extensions["smartshop"] = Runtime(app.config)
    return app
