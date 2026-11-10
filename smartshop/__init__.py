from flask import Flask, render_template
from werkzeug.exceptions import HTTPException
from .config import load_config
from .extensions import db
from .routes import register_routes
from .runtime import Runtime
from .security import install_security
from .presentation.i18n import install_i18n


def create_app(config_overrides=None):
    """Build an application without starting devices, workers, or database I/O."""
    app = Flask(__name__)
    app.config.update(load_config())
    if config_overrides:
        app.config.update(config_overrides)
    db.init_app(app)
    install_security(app)
    install_i18n(app)
    register_routes(app)
    app.extensions["smartshop"] = Runtime(app.config)

    @app.errorhandler(HTTPException)
    def request_error(error):
        return render_template('error.html', error=error), error.code

    return app
