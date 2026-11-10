"""Development entry point: python app.py."""
import atexit
import os
from smartshop import create_app
from smartshop.extensions import db


def main(debug=True):
    app = create_app()
    runtime = app.extensions["smartshop"]
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        with app.app_context():
            db.create_all()
        atexit.register(runtime.stop)
        runtime.start()
    try:
        app.run(debug=debug)
    finally:
        runtime.stop()


if __name__ == "__main__":
    main()
