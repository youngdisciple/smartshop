# SmartShop

Flask inventory and self-checkout with reusable UHF product tags, ESP32/RC522
membership cards over MQTT, customer accounts, simulated payment, loyalty points,
receipts, and English/French screens. The refrigerator dashboard, MQTT telemetry,
Resend alerts, Gmail reply control and Raspberry Pi fan remain available.

## Setup

```sh
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Use `requirements-pi.txt` on the fan-controlling Pi. Set a persistent random
`SECRET_KEY`. Set `DATABASE_URL` to an absolute SQLite URL for local development,
or configure `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` for MySQL/MariaDB.
Create the MySQL database before migration. Environment variables override `.env`.
Never commit local credentials or firmware `secrets.h`.

For checkout development without devices, configure:

```dotenv
DATABASE_URL=sqlite:////absolute/path/to/smartshop.db
FRIDGE_SERVICES_ENABLED=false
GMAIL_SERVICE_ENABLED=false
MEMBERSHIP_SERVICE_ENABLED=false
FAKE_READERS_ENABLED=true
```

Then migrate explicitly and launch:

```sh
python -m scripts.setup_shop
python app.py
```

Startup also runs the repeatable migration. Existing customer email keys,
fields and password hashes are preserved; membership numbers, points and admin
flags are added. **Back up an existing database first.** MySQL DDL is not atomic;
rerunning a failed additive migration is supported. `create_all()` alone is not
an upgrade procedure. SQLite uses validation triggers for the new constraints
on legacy customer tables; new tables use normal schema constraints.

Sign up at `/auth/signup`, then deliberately promote an existing account:

```sh
python -m scripts.setup_shop --admin-email your-account@example.com
```

Public signup never grants administrative rights. `/products`, receptions,
customer directory and threshold mutations require an administrator. Accounts
and receipts enforce ownership; a membership scan grants loyalty association
only. Forms and polling mutations require CSRF tokens. Use HTTPS and
`COOKIE_SECURE=true` for a deployed browser session.

## Inventory and checkout

1. Register products with name, category, CAD price, producer, UPC and full EPC.
   UPC is a string of up to 13 digits, EPC up to 24 hex characters; leading
   zeros survive. A keyboard-wedge barcode scanner can fill the UPC field,
   with Enter handled as a field terminator. Its actual device remains unverified.
2. Receive positive stock quantities with a date, repeatedly if needed.
   Registration alone never adds stock. Receptions are preserved in history.
3. Open `/checkout`, start a cart and arm the product reader. Fake mode exposes
   a clearly labeled development EPC input; it is disabled by default.
4. Review the list. Each distinct reusable product tag adds one unit. Removing
   a product suppresses subsequent observations until explicitly added back.
5. Optionally scan a linked membership card, refresh the result and explicitly
   confirm the membership. Otherwise continue as a guest. A signed-in browser
   does not automatically attach its account to a purchase.
6. Review and simulate success, failure or cancellation. No real payment
   credentials are requested. Success atomically saves snapshots, deducts stock
   and awards floor(total CAD) points to a confirmed member. Guests earn zero.
   If price/stock changes, refresh the review before trying payment again.
7. View the saved receipt. Members see their purchase history and points in
   `/account`. Archived or edited products do not change historical receipts.

The same physical tag can be used in a later checkout while stock remains.
Sales never permanently disable tags. Four products are the intended physical
demo dataset; CRUD and repeated receptions also support later products.

### Verified product setup

No guessed physical EPCs or commercial product metadata are included. Obtain
reader-confirmed values for suffixes **4965, 4970, 4968, 4951**, in that order.
Supply a local JSON file:

```json
{
  "reader_verified": true,
  "products": [
    {"name": "ACTUAL_NAME", "category": "ACTUAL_CATEGORY", "price": "1.25",
     "upc": "ACTUAL_UPC", "epc": "READER_CONFIRMED_FULL_EPC", "producer": "ACTUAL_PRODUCER"}
  ]
}
```

The file must contain all four actual product entries. The example is a format
illustration and intentionally fails validation. After physical confirmation:

```sh
python -m scripts.setup_shop --verified-products /path/to/products.json
```

Repeated setup never duplicates products or adds stock. Conflicting existing
metadata requires an explicit product edit. Test fixtures use **synthetic DE…
EPCs**, not the photographed production tag values.

## Reader and email deployment

The CF600 SDK is absent. `smartshop/hardware/product_reader.py` provides an
adapter boundary, exclusive owned scans, expiration and a fake reader. The real
transport is deliberately unavailable until the Omnivox sample is supplied and
run on the target Pi. Record its OS/architecture, transport and all-four-tag
output, then implement the adapter's `start`, `poll`, `stop` methods. Do not
claim simultaneous physical scanning from the fake-reader demonstration.

Membership firmware is in `firmware/esp32/membershipReader/`. Copy its
`secrets.example.h` to ignored `secrets.h`. Wiring: RC522 3.3V/GND, RST4,
SS5, MISO19, MOSI23, SCK18, IRQ unconnected. With PlatformIO:

```sh
pio run -d firmware/esp32/membershipReader
# After confirming board and serial port, upload deliberately:
pio run -d firmware/esp32/membershipReader -t upload --upload-port /dev/YOUR_PORT
```

Pinned target: esp32dev, espressif32 6.12.0 (Arduino core 2.0.17), MFRC522
1.4.12, PubSubClient 2.8.0, ArduinoJson 7.4.2. Generic target compilation passes;
actual board identity and physical operation remain unverified. The PDF's
historical library patch was unnecessary. The dedicated sketch preserves the
refrigerator sketch folders. It needs Wi-Fi, a trusted MQTT broker and NTP;
all commands/events are non-retained, and a fresh presentation is required.

Set `MEMBERSHIP_SERVICE_ENABLED=true` independently of refrigerator/Gmail
switches. Configure broker host/port, dedicated backend MQTT credentials, TLS
when needed, and topic prefix. Reader firmware currently uses LAN MQTT on
1883; deploy it on an isolated trusted LAN or add a CA-validated TLS transport
before using an untrusted network. Broker ACLs must restrict command publishing
to the backend and event/status publishing to the single reader. See the exact
[MQTT contract and ER diagram](docs/phase3-design.md). Enrollment from `/account/card`
requires login, an unassigned card and explicit confirmation; replacing a card
requires the replacement checkbox. One reader serves one operation at a time.
Remove a card already on the reader, then present it after arming.

Receipts use `RESEND_API_KEY` and a separate verified `RECEIPT_FROM`. They go to
the confirmed member's saved email, never `ALERT_TO`. Delivery occurs after
committing the sale. Failures leave the purchase intact and mark delivery
`failed`; the receipt page offers retry. A `sending` attempt can be reclaimed
after five minutes. Provider requests use a stable purchase idempotency key;
check provider logs before retrying an ambiguous timeout outside its retention
window. No live customer emails were sent during automated tests.

## Service lifecycle and refrigerator hardware

Application construction/imports start no network clients, workers, DB I/O or
GPIO. `app.py` migrates and starts `app.extensions['smartshop']` only in the
serving reloader child; shutdown releases every service. Another entry point
must explicitly call `migrate()` inside an app context, `runtime.start()` and
`runtime.stop()`. Use **one serving process** for the physical fan and reader
leases. Cart/purchase data persists; in-memory leases require rearming after a
restart. Do not run multiple processes against the same readers.

Fridge MQTT consumes `Frig1/#` and `Frig2/#`, retries offline connections and
clears stale readings on disconnect. Thresholds default to 5 °C / 4 °C;
readings, alert suppression and thresholds are in memory. Error sample `999`
retains its meaning. Resend alerts retry on later readings. Gmail polls every
15 seconds; a new matching YES reply from the configured owner enables the fan.
The fan uses BCM 22/27/17 and stops after both fridges remain below thresholds
for five seconds. GPIO loads lazily. Optional LEDs (18/23) are not enabled by
signup. Refrigerator sketches are preserved.

## Verification and diagnostics

```sh
python -m unittest discover -v
python -m scripts.scan_products --fake 00AA 00AA 00BB
python -m scripts.check_membership
python -m scripts.check_gmail
python -m scripts.monitor_mqtt
python -m scripts.read_replies
```

`check_membership` explicitly arms a card read and prints the UID without
linking it. `read_replies` can activate the physical fan; use the full app for
cooldown and avoid competing reply readers.

The regular suite uses SQLite, fake readers/MQTT/email/GPIO and needs no live
credentials. Opt-in tests create and drop only random test schemas on an
isolated `/tmp` MySQL socket:

```sh
SMARTSHOP_TEST_MYSQL_SOCKET=/tmp/smartshop-mariadb.sock python -m unittest tests.test_mysql -v
```

Optional browser regression checks use a disposable localhost fixture:

```sh
python -m tests.browser_server
# In a second terminal with Playwright and Chromium installed:
NODE_PATH=/path/to/node_modules node tests/browser_phase3.cjs
```

The fixture has explicit development credentials and test-only scan injection;
never deploy it. See [verification and hardware handoff](docs/phase3-verification.md)
and [the implementation checklist](requirements/PHASE-3-IMPLEMENTATION.md) for
observed results and the remaining physical checks. Reference PDFs/photo remain
local ignored files and must be supplied separately in another checkout.
