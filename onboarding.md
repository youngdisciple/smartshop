# SmartShop codebase onboarding

SmartShop combines two business areas in one Flask application:

- **Inventory and self-checkout:** product registration, stock receptions,
  product-tag scanning, membership cards, simulated payment, points, and receipts.
- **Refrigerator monitoring:** ESP32 temperature/humidity telemetry, email
  alerts, Gmail reply commands, and Raspberry Pi fan control.

They share configuration, browser sessions, presentation helpers, and a runtime
that owns devices and background services.

## Repository map

```text
app.py                         Development entry point
smartshop/
  __init__.py                  Flask application factory
  config.py                    Environment-based configuration
  extensions.py                SQLAlchemy extension and SQLite foreign keys
  runtime.py                   Shared devices, workers, locks, and cleanup
  security.py                  Sessions, CSRF, login, and administrator checks
  routes/                      HTTP endpoints and browser workflows
  models/                      Persistent database records
  services/                    Business rules and external integrations
  hardware/                    GPIO and product-reader adapters
  presentation/                Translations, money formatting, gauge formatting
  templates/                   Server-rendered Jinja pages
  static/                      CSS and browser JavaScript
firmware/esp32/                Refrigerator and membership-reader firmware
scripts/                       Setup and diagnostic commands
tests/                         Unit, integration, and browser checks
docs/                          Design and verification documentation
requirements/                  Implementation checklist and requirements
requirements.txt               Python application dependencies
requirements-pi.txt            Additional Raspberry Pi GPIO dependency
package.json                   Frontend dependency declaration
.env.example                   Configuration template
```

## 1. Application construction and lifecycle

Start with [app.py](app.py), [the application factory](smartshop/__init__.py),
and [runtime.py](smartshop/runtime.py).

`create_app()` constructs Flask, loads configuration, initializes SQLAlchemy,
installs security and translation helpers, registers route blueprints, and
constructs a `Runtime`. Construction starts no network clients, workers,
database queries, or GPIO initialization.

`app.py` performs the operational steps: migrate the database, start the runtime,
run Flask, and stop services on shutdown. Its reloader check prevents the Flask
debug parent process from starting a second set of services.

Routes access the runtime through:

```python
runtime = current_app.extensions['smartshop']
```

`Runtime` owns the fan, refrigerator monitor, refrigerator MQTT client,
membership reader, product reader, checkout lock, alert executor, and worker
threads. Service switches independently control refrigerator, Gmail, and
membership startup. Shutdown releases devices and joins workers.

Another server entry point must explicitly run migrations in an application
context and manage `runtime.start()` and `runtime.stop()`.

## 2. Configuration and database access

[config.py](smartshop/config.py) loads the root `.env` file and environment
variables. Existing environment variables take precedence.

| Settings | Purpose |
| --- | --- |
| `DATABASE_URL` or `DB_*` | SQLite or MySQL database connection |
| `SECRET_KEY`, `COOKIE_SECURE` | Browser session signing and cookie policy |
| `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT` | Broker connection |
| `FRIDGE_SERVICES_ENABLED` | Refrigerator MQTT and fan cooldown worker |
| `GMAIL_SERVICE_ENABLED` | Gmail reply worker |
| `MEMBERSHIP_SERVICE_ENABLED` | Membership MQTT service |
| `MEMBERSHIP_TOPIC`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TLS` | Membership MQTT connection and protocol configuration |
| `FAKE_READERS_ENABLED` | Development product reader |
| `RESEND_API_KEY`, `ALERT_FROM`, `ALERT_TO` | Refrigerator alert delivery |
| `RECEIPT_FROM` | Separate sender for customer receipts |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` | Gmail reply access |

[extensions.py](smartshop/extensions.py) defines the shared `db` object and
enables foreign-key checks for SQLite connections. Models and services import
this extension rather than constructing their own database connections.

[migrations.py](smartshop/services/migrations.py) upgrades legacy customer tables,
preserves existing customer data and password hashes, and creates newer tables.
It supports SQLite and MySQL. `db.create_all()` alone does not upgrade an
existing schema. Back up an existing database before migration.

## 3. HTTP routes

The [route registry](smartshop/routes/__init__.py) installs four blueprints:

| Module | Responsibility | Main paths |
| --- | --- | --- |
| [auth.py](smartshop/routes/auth.py) | Signup, login, logout | `/auth/signup`, `/auth/login`, `/auth/logout` |
| [admin.py](smartshop/routes/admin.py) | Administrator customer directory | `/admin/` |
| [dashboard.py](smartshop/routes/dashboard.py) | Refrigerator display and threshold changes | `/dashboard`, `/thresholds/<fridge_id>` |
| [shop.py](smartshop/routes/shop.py) | Catalog, inventory, accounts, cards, checkout, receipts, reader endpoints | `/products`, `/inventory/<product_id>`, `/account`, `/checkout`, `/receipts/<purchase_id>` |

A request generally follows this path:

```text
Browser → security checks → route → service/database/device → HTML or JSON
```

Routes parse browser input, enforce access, coordinate operations, and choose a
response. Services hold reusable rules, although some queries and workflow
transitions remain in route handlers. `routes/shop.py` is the largest route module.

## 4. Authentication, authorization, and ownership

[security.py](smartshop/security.py) distinguishes three concepts:

- **Customer identity:** `session['email']` identifies the logged-in customer,
  loaded into `g.customer` before each request.
- **Administrator role:** `admin_required` protects catalog changes, stock
  reception, the customer directory, and threshold changes.
- **Browser ownership:** `owner()` creates a random session identifier used to
  own carts and reader operations, including guest operations.

Mutating HTTP requests require a CSRF token in a form field or the
`X-CSRF-Token` header. Templates receive a token helper. Responses also receive
security headers and, outside static assets, a `no-store` cache policy.

[Authentication routes](smartshop/routes/auth.py) validate signup input and use
Werkzeug password hashing. Signup cannot grant administrator rights. Login,
signup, and logout rotate the session and cancel the old owner's reader leases.

Signing in does not automatically attach an account to a purchase. A membership
card scan requires explicit confirmation and grants purchase loyalty association;
it does not authenticate the browser as the cardholder.

## 5. Database models

Models live in [customer.py](smartshop/models/customer.py) and
[shop.py](smartshop/models/shop.py).

| Model | Stored information |
| --- | --- |
| `Customer` | Email primary key, password hash, contact details, membership number, points, admin flag |
| `Product` | Name, category, producer, unique UPC/EPC, price, stock, archive flag |
| `Reception` | Product, positive received quantity, reception date |
| `MembershipCard` | Unique card UID linked to one customer; one card per customer |
| `Checkout` | Browser owner, status, JSON cart items, suppressed products, optional member |
| `Purchase` | Completed checkout, member, totals, points, language, receipt delivery state |
| `PurchaseItem` | Product reference plus saved name, unit price, and quantity |

Money is stored as integer cents. Product input uses `Decimal` before conversion
to cents. UPCs and EPCs are strings, preserving leading zeros.

Purchase items are historical snapshots: editing or archiving a product does
not change an existing receipt.

The current model assigns one EPC to each product. A cart contains at most one
unit of each product; repeated scans do not increase quantity. Supporting
multiple individually tagged units of the same product would require a model
and checkout change.

## 6. Catalog and inventory

[catalog.py](smartshop/services/catalog.py) validates product fields, normalizes
EPCs, validates UPCs and prices, and receives stock.

Product registration starts with zero stock. Receiving stock increments
`Product.stock` and adds a dated `Reception` in the same transaction. Reception
history is retained.

The product deletion route archives products with reception or purchase history.
Products without that history can be deleted. Archived products are unavailable
for sale and stock reception.

## 7. Checkout and simulated payment

Read [checkout.py](smartshop/services/checkout.py) alongside the checkout
handlers in [routes/shop.py](smartshop/routes/shop.py).

The main successful workflow is:

```text
Start cart → scanning → review → payment → complete → receipt
```

The browser can also cancel, return from review/payment to scanning, or return
to review after a simulated failed/cancelled payment.

Three service functions contain the central rules:

| Function | Responsibility |
| --- | --- |
| `add_tags()` | Resolve EPCs, reject unknown/archived/out-of-stock products, deduplicate cart entries |
| `review()` | Refresh product names/prices and verify availability |
| `finalize()` | Save the sale, deduct stock, and award points atomically |

Removing a product adds it to the checkout's `suppressed` list, so continued
reader observations do not immediately restore it. Explicit restoration removes
that suppression.

`finalize()` first returns an existing purchase if one already exists. Otherwise,
it conditionally claims a checkout in `payment` state, conditionally deducts
stock in product-ID order, creates purchase snapshots, updates member points,
and commits. Product name and price must still match the reviewed values.
Failures roll back the sale. Duplicate success submissions reuse the purchase.

Confirmed members earn `total_cents // 100` points; guests earn zero. Payment
is simulated and does not collect real payment credentials.

## 8. Product-reader boundary

[hardware/product_reader.py](smartshop/hardware/product_reader.py) separates
reader transport from exclusive scan ownership:

- `ProductReader` manages browser-owned, purpose-specific, 60-second operations.
- `FakeReader` accepts development EPC input.
- `UnavailableReader` reports that the physical CF600 adapter is unavailable.

An adapter implements `start()`, `poll()`, and `stop()`. The wrapper checks
ownership, expires operations, normalizes EPCs, and deduplicates observations.

The real CF600 transport is not implemented. Fake mode exercises the application
workflow without demonstrating physical reader operation.

## 9. Membership cards and MQTT

[services/membership.py](smartshop/services/membership.py) coordinates the
membership reader independently of refrigerator telemetry. Its firmware is in
[firmware/esp32/membershipReader/](firmware/esp32/membershipReader/).

The default topic namespace is:

```text
SmartShop/membership/command   Backend arms or cancels an operation
SmartShop/membership/status    Reader identity and heartbeat
SmartShop/membership/event     Card UID for an armed operation
```

Operations last 60 seconds and are exclusive. The backend validates browser
ownership, purpose, operation ID, reader boot identity, heartbeat freshness, and
UID format. Retained messages are ignored; disconnects and reader restarts
invalidate operations.

Enrollment requires login and explicit confirmation. Replacing an existing card
requires the replacement choice. Checkout card confirmation associates the
linked customer with that purchase.

See [phase3-design.md](docs/phase3-design.md) for the protocol and data design.

## 10. Refrigerators, alerts, and fan control

| Module | Responsibility |
| --- | --- |
| [services/mqtt.py](smartshop/services/mqtt.py) | Subscribe to `Frig1/#` and `Frig2/#`, parse telemetry, track broker connection |
| [services/fridge_monitor.py](smartshop/services/fridge_monitor.py) | Store readings/thresholds, decide alerts, evaluate fan cooldown |
| [services/alerts.py](smartshop/services/alerts.py) | Send refrigerator alert emails through Resend |
| [services/reply_reader.py](smartshop/services/reply_reader.py) | Poll Gmail for qualifying replies |
| [hardware/fan.py](smartshop/hardware/fan.py) | Drive the Raspberry Pi fan through GPIO |
| [hardware/leds.py](smartshop/hardware/leds.py) | Optional status LEDs; unused by web routes |

The two refrigerator sketches live in `firmware/esp32/frig1Arduino/` and
`firmware/esp32/frig2Arduino/`. They publish temperature and humidity telemetry.

The control flow is:

```text
ESP32 reading → MQTT → FridgeMonitor → background email alert
Gmail YES reply → ReplyReader → FanController.fan_on()
Both fridges cool for five seconds → FridgeMonitor → fan_off()
```

Default temperature thresholds are 5 °C and 4 °C. A reading of `999` means
unavailable/error. Broker disconnects clear readings, preventing those previous
samples from satisfying cooldown.

An excessive temperature triggers an alert. Successful alerts are suppressed
until temperature recovers; failed delivery permits a later reading to retry.
The alert itself does not turn on the fan.

Gmail is polled every 15 seconds. A qualifying new message has a matching alert
subject, the configured sender address, and `YES` as its first nonempty line.
The reply reader establishes an initial UID baseline to ignore existing mail.

Fan GPIO loads lazily. The controller uses BCM pins 22, 27, and 17. Once on,
the fan stops after both valid temperatures stay at or below their thresholds
for five seconds.

## 11. Receipts and email delivery

[receipts.py](smartshop/services/receipts.py) renders saved purchase data and
sends receipts to the confirmed member's saved email address.

Delivery occurs after the sale commits, so email failure leaves the purchase
intact. Delivery status and attempt counts are stored in the database. Failed
attempts can be retried; a `sending` attempt older than five minutes can be
reclaimed. Requests use a purchase-specific provider idempotency key.

Guest purchases have no email recipient and use `not_required` delivery status.
Receipt pages are accessible to the checkout's browser owner or the associated
logged-in customer.

## 12. Templates, formatting, and JavaScript

[templates/base.html](smartshop/templates/base.html) supplies navigation,
language selection, CSRF metadata, flash messages, and the shared page layout.
Templates are grouped into `auth/`, `admin/`, `dashboard/`, and `shop/`.

| File | Purpose |
| --- | --- |
| [presentation/gauges.py](smartshop/presentation/gauges.py) | Convert readings into gauge labels and geometry |
| [presentation/i18n.py](smartshop/presentation/i18n.py) | English/French translation and money formatting |
| [static/dashboard.css](smartshop/static/dashboard.css) | Shared styling and responsive layout |
| [static/cart.js](smartshop/static/cart.js) | Poll cart updates and submit development tags |
| [static/product.js](smartshop/static/product.js) | UPC lookup, barcode Enter handling, EPC capture |
| [static/membership.js](smartshop/static/membership.js) | Poll enrollment readiness |

The UI is primarily server-rendered. JavaScript adds polling and scanner
interaction; the server validates ownership, workflow state, stock, and prices.

## 13. Persistent versus in-memory state

| Stored in the database | Held in process memory |
| --- | --- |
| Customers and membership-card links | Active product and membership operations |
| Products, stock, reception history | Refrigerator readings and thresholds |
| Carts, purchases, item snapshots | Alert suppression and cooldown timer |
| Points and receipt delivery state | Fan state, connections, locks, workers |

Restarting preserves sales and stock, but reader operations require rearming and
refrigerator thresholds return to defaults. Use one serving process for shared
hardware and reader leases. Database transaction protection does not replace
the runtime's single-process hardware ownership.

## 14. Local development and verification

Run commands from the repository root:

```sh
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

For development without devices, configure a persistent random `SECRET_KEY`,
an absolute SQLite `DATABASE_URL`, and these switches in `.env`:

```dotenv
FRIDGE_SERVICES_ENABLED=false
GMAIL_SERVICE_ENABLED=false
MEMBERSHIP_SERVICE_ENABLED=false
FAKE_READERS_ENABLED=true
```

Then initialize and run:

```sh
python -m scripts.setup_shop
python app.py
```

Create an account through signup. To deliberately grant administrator access:

```sh
python -m scripts.setup_shop --admin-email your-account@example.com
```

The standard verification command is:

```sh
python -m unittest discover -v
```

| Test module | Main coverage |
| --- | --- |
| `tests/test_app.py` | Application construction, authentication, dashboard, permissions |
| `tests/test_services.py` | Monitoring, MQTT, email replies, GPIO, lifecycle |
| `tests/test_phase3.py` | Catalog, checkout, cards, receipts, migrations, competing sales |
| `tests/test_mysql.py` | Opt-in isolated MySQL migration and payment checks |
| `tests/test_scripts.py` | Diagnostic command behavior |
| `tests/browser_phase3.cjs` | Browser workflow checks using a disposable fixture |

The regular suite uses fake integrations and SQLite. Physical hardware and live
delivery require separate verification.

Diagnostic entry points include `scripts.scan_products`,
`scripts.check_membership`, `scripts.check_gmail`, and `scripts.monitor_mqtt`.
`scripts.read_replies` can activate the physical fan; the full application owns
the cooldown worker.

See [README.md](README.md) for deployment commands and
[phase3-verification.md](docs/phase3-verification.md) for verification details and
remaining physical checks. Keep credentials in ignored local configuration and
membership firmware `secrets.h`.

## Suggested reading order

1. `smartshop/__init__.py`, `app.py`, and `runtime.py` for construction and ownership.
2. `config.py`, `extensions.py`, and `models/` for configuration and persisted data.
3. `security.py` and `routes/auth.py` for identity and browser ownership.
4. `services/catalog.py` and `services/checkout.py` for inventory and sale rules.
5. `routes/shop.py` to follow those rules through browser workflows.
6. `hardware/product_reader.py` and `services/membership.py` for reader boundaries.
7. Refrigerator MQTT, monitor, alert, reply, and fan modules for the control loop.
8. Templates, presentation helpers, and JavaScript for rendering and interaction.
9. The matching test modules for concrete examples and edge cases.

When extending the project, place HTTP handling in `routes/`, persisted records
in `models/`, reusable rules/integrations in `services/`, device adapters in
`hardware/`, and display formatting in `presentation/`. Keep imports free of
network connections, worker startup, and GPIO initialization.
