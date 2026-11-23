"""Development entry point: python app.py."""
import atexit
import os
from threading import Thread
import webbrowser
from werkzeug.serving import make_server

from smartshop import create_app
from smartshop.services.migrations import migrate


def main(debug=True, *, open_browser=False):
    app = create_app()
    runtime = app.extensions["smartshop"]
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        with app.app_context():
            migrate()
        atexit.register(runtime.stop)
        runtime.start()
    try:
        if open_browser:
            with make_server('127.0.0.1', 5000, app, threaded=True) as server:
                address = f'http://127.0.0.1:{server.server_port}'
                print(f'SmartShop is running at {address}. Press Ctrl+C to stop.', flush=True)
                Thread(target=webbrowser.open, args=(address,), daemon=True).start()
                server.serve_forever()
        else:
            app.run(debug=debug)
    finally:
        runtime.stop()


if __name__ == "__main__":
    main()
