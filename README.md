# SmartShop

Flask customer signup and refrigerator dashboard, with ESP32 MQTT readings,
Resend temperature alerts, Gmail reply control, and a Raspberry Pi fan.

## Layout

```text
app.py                  Development server and explicit service startup
smartshop/
  config.py             Environment loading and application settings
  extensions.py         SQLAlchemy instance, independent of the Flask app
  runtime.py            Shared services and worker lifecycle
  models/               Customer database model
  routes/               Admin, signup, and dashboard blueprints
  services/             MQTT transport, fridge monitoring, alerts, Gmail replies
  hardware/             Fan and optional status LED drivers
  presentation/         Dashboard gauge formatting
  templates/            Existing Jinja templates
scripts/                Explicit diagnostic commands
firmware/esp32/          Arduino sketches, one folder per refrigerator
tests/                  Automated tests with fake devices and services
```

## Setup and launch

Use a virtual environment and install `requirements.txt` for the web application
and diagnostics. On the Raspberry Pi that controls the fan, install
`requirements-pi.txt` instead; it includes `RPi.GPIO` and the application dependencies.

```sh
python3 -m venv venv
. venv/bin/activate
pip install -r requirements-pi.txt
cp .env.example .env
python app.py
```

Set the database credentials, MQTT broker host, Resend settings, and Gmail address
and app password in `.env`. MySQL must have a `smartshop` database accessible on
localhost; startup creates missing tables but does not migrate existing tables.
The `.env` file is resolved from the repository root. Existing environment
variables take precedence. Use an appropriate `SECRET_KEY` for your deployment.

`python app.py` launches Flask in debug mode. Database initialization and MQTT,
Gmail polling, and fan cooldown workers start only in the serving process, not
in the reloader parent. Workers stop and the fan is released when the server exits.

The URLs remain `/auth/signup`, `/admin/`, `/dashboard`, and
`POST /thresholds/<fridge_id>`. The admin route retains its existing `ok` response.
The dashboard refreshes every three seconds.

## Services and hardware

`smartshop.create_app(config_overrides=None)` builds an application without
starting workers, connecting to external services, or initializing GPIO. Its
shared runtime is available as `app.extensions["smartshop"]`. Routes, MQTT, and
Gmail share that runtime's monitor and fan controller. For another server entry
point, explicitly call `db.create_all()` inside an app context if needed, call
`runtime.start()` once in the serving process, and arrange `runtime.stop()` at
shutdown. Use one serving process for the shared physical fan and in-memory state.

MQTT subscribes to `Frig1/#` and `Frig2/#`, consuming temperature and humidity
readings. The broker may be offline during testing: Flask continues serving,
and MQTT retries in the background with a delay increasing from one to 30 seconds.
The dashboard shows the offline connection status. Disconnection clears old readings
to `999` and resets cooldown so stale samples cannot turn the fan off. Once the
broker returns, the client resubscribes and new readings populate the dashboard.
`MQTT_BROKER_HOST` must still specify the broker hostname or IP, even while it is
offline; an absent setting is a configuration error.

Thresholds default to 5 °C and 4 °C; readings and thresholds remain
in memory. Error reading `999` retains its existing meaning. Temperature alerts
are sent once per excursion above the threshold, with failed sends retried on
later readings. A valid new Gmail reply from the configured Gmail address whose
first nonblank line is `YES` enables the shared fan. The reader ignores existing
matching mail on its initial scan and polls every 15 seconds. Its existing UID
baseline behavior is retained, including waiting for a matching message when
starting with no matches.

The fan uses BCM pins 22 (enable), 27 (input 1), and 17 (input 2). It turns off
after both fridges continuously remain at or below their thresholds for five
seconds. GPIO loads only when hardware is first used; a machine without GPIO can
import the app and render the dashboard, but cannot operate the physical fan.
Optional status LEDs use BCM pins 18 and 23 and are not enabled by signup routes.

Arduino sketches live in `firmware/esp32/frig1Arduino/` and
`firmware/esp32/frig2Arduino/`; sketch contents and Arduino folder names are
unchanged. Configure Wi-Fi and broker values in the sketches before uploading.

## Diagnostics and tests

Run diagnostics from the repository root after activating the environment:

```sh
python -m scripts.check_gmail
python -m scripts.monitor_mqtt
python -m scripts.read_replies
python -m unittest discover -v
```

The reply-only diagnostic can activate the physical fan; run the full application
for automatic cooldown. Avoid running it alongside the application's reply reader.
The diagnostics have guarded entry points, so importing them does not connect to
services. The tests use SQLite and fake network services and GPIO; no credentials
or attached hardware are needed. Live MySQL, MQTT, email delivery, and device
operation require verification on the configured Raspberry Pi.
