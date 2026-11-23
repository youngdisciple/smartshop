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
3. Open `/` or `/checkout` and start a cart. Checkout is public and requires no sign-in. Scan a barcode into the UPC field; Enter
   or Tab submits it, or click Add barcode. Each deliberate barcode scan adds
   one unit. Barcode checkout works without arming the RFID reader. Alternatively,
   arm the product reader to collect multiple RFID tags. Fake mode exposes a
   development EPC input; it is disabled by default.
4. Each distinct reusable RFID tag adds one unit once. Repeated RFID reports
   preserve the current quantity. Use +/− to adjust units up to available stock;
   decreasing to zero removes the line. Removing a product suppresses RFID
   reappearance until Add back or an explicit barcode scan. Barcode and RFID
   observations of the same product share one cart line.
5. Optionally scan a linked membership card, refresh the result and explicitly
   confirm the membership. Otherwise continue as a guest. A signed-in browser
   does not automatically attach its account to a purchase.
6. Review and simulate success, failure or cancellation. No real payment
   credentials are requested. Success atomically saves quantities and price snapshots, deducts the purchased stock
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

The attached CF600 uses **CDC-COM serial mode**, as specified by the teacher.
Select that mode in the reader configuration software. On this Pi, load the
USB serial driver (requires local administrator access):

```sh
sudo modprobe usbserial vendor=0x0483 product=0x5750
ls -l /dev/ttyUSB* /dev/serial/by-id/
```

Install `requirements-pi.txt` in the application environment and configure:

```dotenv
FAKE_READERS_ENABLED=false
PRODUCT_READER_BACKEND=cf600_serial
CF600_SERIAL_DEVICE=/dev/serial/by-id/usb-CFUSB_HID_By_YLW28-if03-port0
CF600_BAUDRATE=57600
```

Use the stable path rather than `/dev/ttyUSB0`, whose number can change. The
service user needs serial access, normally through the `dialout` group. The
current user already has it. Restart the app after changing `.env`. A module
loaded manually may need loading again after reboot; check the port first.

The attached reader emits binary inventory frames in its configured scanning
mode. The adapter passively reads them, validates framing/CRC/status/EPC length,
and preserves leading zeros. It sends **no commands or tag writes**. Observed
framing matches the [CF-header inventory protocol](https://electron.id/protocol/el-uhf-rc4-protocol/),
including CRC-16 (preset FFFF, reflected polynomial 8408, high byte first).
This is distinct from the older UHFReader18 protocol in the local SDK archive.
57600 is the baud setting used during the successful capture on this device;
it is configurable for readers with different settings.

Only an armed scan opens the serial port, with an exclusive process lock.
Cancellation, independent 60-second expiry, disconnect, overflow and application
shutdown close it. A disconnected or expired scan requires rearming. Keep one
serving process. Stop a web scan before using the diagnostic:

```sh
python -m scripts.scan_products --hardware --seconds 15
# Override a different deployment's serial path if necessary:
python -m scripts.scan_products --hardware --device /dev/serial/by-id/YOUR_READER --seconds 15
```

Present each tag separately, then all four together. Capture one EPC in product
registration, save actual metadata and receive stock. In checkout, start a scan
and present the tags; the browser updates automatically and repeated EPCs add no
quantity. The registration screen shows its waiting state and prevents duplicate
polling loops. Multiple tags require stopping and restarting capture with only
the intended tag present; an ambiguous capture clears the EPC field.

A real, checksum-valid serial capture identified `A00000000000000000004965`.
Other full EPCs, all-four simultaneous inventory and physical checkout still
need verification; no production product records are seeded from this capture.
See the [project index](docs/project-index.md) and [verification notes](docs/phase3-verification.md).

The optional `cf600_hid` backend remains for readers explicitly configured to
emit keyboard events, separated by Tab, using `CF600_INPUT_DEVICE`. The attached
reader emitted no keyboard events during testing, so use `cf600_serial` here.
The diagnostic selects serial by default; use `--backend cf600_hid` only for a
verified keyboard-mode reader.

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

Checkout receipts support Gmail SMTP and Resend. Both send to the confirmed
member's saved email, never `ALERT_TO`; guests receive an on-screen receipt only.
Delivery occurs after the sale commits. No network connection starts during
application construction.

For Gmail, enable Google 2-Step Verification and create an app password at
[Google App Passwords](https://myaccount.google.com/apppasswords). Some managed
accounts, Advanced Protection and security-key-only setups do not offer app
passwords; see [Google's account guide](https://support.google.com/accounts/answer/185833).
Set these in local `.env`, replacing existing entries rather than duplicating:

```dotenv
RECEIPT_EMAIL_PROVIDER=gmail
GMAIL_ADDRESS=your-sender@gmail.com
GMAIL_APP_PASSWORD=your_16_character_app_password
```

Use the generated app password, not your normal Google password. Formatting
spaces in the app password are removed for SMTP login. Restart the app, then
complete a purchase with a linked membership card and explicitly confirm it at
checkout. Check the receipt status and recipient inbox/spam folder. A successful
SMTP submission means Gmail accepted the message, not that inbox delivery has
been independently verified. Gmail sends from the authenticated `GMAIL_ADDRESS`
over certificate-validated TLS to `smtp.gmail.com:465`. Gmail receipts do not use
`RECEIPT_FROM` or `RESEND_API_KEY`. `GMAIL_SERVICE_ENABLED` controls incoming
fridge reply polling independently; it need not be enabled to send receipts.
These credentials are shared with the reply reader if that service is enabled.
No additional Python dependency is required.

For Resend, select `RECEIPT_EMAIL_PROVIDER=resend` (the default) and provide
`RESEND_API_KEY` plus a verified `RECEIPT_FROM`. Existing fridge alerts continue
to use their own Resend configuration regardless of the receipt provider.

Failures preserve the purchase and mark delivery `failed`; the receipt page
provides retry. A `sending` attempt can be reclaimed after five minutes. Resend
uses a stable provider idempotency key; Gmail uses a stable Message-ID but SMTP
has no equivalent deduplication guarantee. Check Gmail Sent mail before retrying
an ambiguous timeout, which could otherwise duplicate the email. Successful
receipts are not resent. No live customer emails were sent during tests.

## Minew MSP01 BLE sensors

Administrators can open **BLE** in the sidebar (`/admin/ble`) to discover and
save Minew sensors using the Raspberry Pi's Bluetooth radio. Install the BLE
dependency in the same environment that runs SmartShop, then enable Bluetooth:

```sh
source venv/bin/activate
python -m pip install 'bleak>=3.0,<4'
sudo systemctl enable --now bluetooth
sudo rfkill unblock bluetooth
```

`requirements-pi.txt` also includes Bleak. If BlueZ is missing, install the
`bluez` package with your system package manager. Run SmartShop as the regular
user; that user must have access to BlueZ on the system D-Bus. Restart SmartShop
after installing dependencies. BLE connections and readings use memory only.

1. Turn on the MSP01 and place it within range of the Pi. Minew's guide says to
   hold the side button until the blue light flashes three times.
2. In BeaconSET+, enable the **HT**, **PIR**, and **PS Sensor** advertising slots.
   Configure the PIR detection periods as needed, and close the phone's sensor
   connection before scanning from SmartShop.
3. Sign in as an administrator, open **BLE**, and click **Scan for sensors**.
   Match the device's Bluetooth address before choosing **Connect**. Other Minew
   BeaconPlus devices may also appear; discovery alone does not verify the model.
4. After connecting, readings update automatically while the BLE tab is visible.
   Use **Pause updates** / **Resume updates** to control reception. **Disconnect**
   removes a sensor from the current runtime without changing its firmware settings.

The MSP01 broadcasts data; Connect selects the device for this runtime rather than
establishing a GATT pairing. A visible BLE page with connected sensors starts one
shared continuous radio receiver. A server-sent events connection pushes new
readings to the cards, at most once per second, without reloading the page.
Actual update frequency depends on the sensor’s advertising settings. Multiple
viewers share the same radio; pausing, hiding or leaving a page closes its stream.
The receiver stops after the last viewer disconnects unless motion monitoring is armed.
Streams reconnect periodically to recheck authorization and retry Bluetooth
failures. The page displays reception/reconnection status and keeps old values
with their timestamps while unavailable. Manual refresh remains available when
the browser does not support streaming.

Discovery without a live viewer takes eight seconds by default. Set
`BLE_ADAPTER=hci0` and `BLE_SCAN_SECONDS=8` in `.env` to choose the server
adapter and manual scan duration (1–30 seconds). Discovery reuses an active live
receiver instead of starting a competing scan. Use one serving process so live
viewers, discovery and Connect share the same device state.

BLE never stores device connections, measurements, receipt timestamps, RSSI or
raw packets in the database. Everything stays in runtime memory. Restarting the
server clears both connections and readings, so scan and reconnect afterward.
BLE creates no database tables and leaves any legacy BLE table untouched.
The receiver combines
separate BeaconPlus `0xFFE1` / `0xA1` HT, PIR, PS and light-lux frames. Each
reading retains its own receipt timestamp; missing packets never reset values
to zero or imply that motion stopped. Old readings remain visible as historical
values, so refresh and check timestamps before interpreting them. The PS level
is displayed separately from lux; lux appears only for a light-lux frame.
The light bar rises from zero to twice its brightness cutoff. Its **Dim/Bright**
label uses a configurable display cutoff, defaulting to 300 PS or 300 lux;
these are display settings rather than a calibration of the raw PS sensor.
Set `BLE_LIGHT_BRIGHT_PS` or `BLE_LIGHT_BRIGHT_LUX` in `.env` and restart to
adjust the cutoff. The cutoff is also shown beneath the bar. Values above the
display range fill the bar while keeping the actual numeric reading visible.
Unsupported firmware frames leave readings unavailable rather than inventing
values. Actual radio reception and firmware compatibility require a physical
MSP01 test; automated tests use synthetic packets and a simulated scanner.

Motion monitoring is off by default. **Enable motion monitoring** starts a
background receiver and enables emails to the administrator who clicks the
button. It continues while the page is hidden or closed, as long as SmartShop
is running. **Disable motion monitoring** stops processing motion and prevents
queued alerts from sending. These controls affect SmartShop monitoring; they
do not physically power off the MSP01 or change its PIR firmware settings.

Motion emails use `BLE_MOTION_EMAIL_PROVIDER` when set, otherwise the existing
`RECEIPT_EMAIL_PROVIDER` (`gmail` or `resend`). Gmail uses `GMAIL_ADDRESS` and
`GMAIL_APP_PASSWORD`; Resend uses `RESEND_API_KEY` and `ALERT_FROM`. The page
shows the recipient and the latest sending/sent/failed status. A new detection
means a transition into detected motion; repeated detected packets do not send
more emails. `BLE_MOTION_ALERT_COOLDOWN` defaults to 60 seconds between alerts
per sensor. All monitoring flags, recipients, cooldowns and delivery statuses
stay in RAM, with no database tables or alert logs. After a server restart,
reconnect the device and explicitly enable monitoring again. Automated tests
mock mail delivery; they never send a live test email.

References: [Minew MSP01 guide](https://www.minew.com/wp-content/uploads/2023/12/MSP01-Bluetooth%C2%AE-PIR-Sensor.pdf),
[reelyActive MSP01 configuration](https://reelyactive.github.io/diy/minew-msp01-config/),
[BeaconPlus frame decoder reference](https://github.com/reelyactive/advlib-ble-services/blob/master/lib/minew.js),
[Bleak scanner API](https://bleak.readthedocs.io/en/latest/api/scanner.html).

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
