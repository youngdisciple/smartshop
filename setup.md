# Phase 3 physical setup

This guide covers the hardware for Phase 3 product registration, inventory,
RFID self-checkout, and membership cards. Refrigerator sensors, refrigerator
ESP32 boards, fans, relays, and Raspberry Pi fan GPIO wiring are outside this
setup. Payment is simulated; no payment terminal is required.

Use [README.md](README.md) for application installation, database setup,
administrator provisioning, and receipt email configuration. The hardware
choices and four-tag mapping come from the
[Phase 3 implementation guide](requirements/PHASE-3-IMPLEMENTATION.md).

**Current integration status:** the membership firmware has compiled for the
generic `esp32dev` target, but the actual board, wiring, and live card reads
still need verification. The CF600 SDK and native application adapter are
missing. Connecting the CF600 alone will not enable physical product scans in
the current application.

## 1. Gather the equipment

- **Raspberry Pi, boot storage, and a suitable power supply.** Hosts the
  application and connects to the CF600. Use a power supply suitable for that
  Pi model. Record the actual Pi model and OS architecture before selecting
  the reader SDK.
- **CF600 UHF desktop reader/writer, its documented connection cable, and its
  specified power source.** Reads product EPCs. Confirm the actual unit's
  interface and power requirements from its documentation.
- **Four actual UHF product tags and four corresponding demonstration
  products.** One reusable tag per product. Reference tag suffixes: `4965`,
  `4970`, `4968`, `4951`.
- **Physical barcode scanner and its connection cable.** Reads the products'
  printed UPCs. The current browser input supports a scanner that acts as a
  keyboard.
- **One dedicated ESP32 development board and a USB data cable.** Runs the
  membership reader sketch; separate from any refrigerator ESP32.
- **One RC522 module, breadboard, and seven jumper connections.** Connects the
  membership reader to the ESP32 over SPI. Use jumper ends compatible with the
  actual headers.
- **At least one RC522-compatible membership card or key fob.** Customer
  enrollment and loyalty identification. A second card is useful for
  replacement checks. These are separate from the UHF product tags.
- **Local network with Wi-Fi for the ESP32.** Connects the ESP32 and Pi to the
  MQTT broker. The broker can run on the Pi or another reachable host.
- **Browser workstation.** Operates registration and checkout. This can be the
  Pi with a screen/keyboard/mouse, or another computer with browser access to
  the application.

Keep the barcode scanner attached to the machine running the browser. If the
browser runs on the Pi, attach it to the Pi; if the browser runs on a laptop,
attach it to that laptop. The CF600 remains connected to the Pi hosting the
reader integration.

## 2. Arrange the bench and network

```text
Printed product barcode --> barcode scanner --> browser workstation
                                                     |
                                                  web access
                                                     |
Four UHF product tags --> CF600 -- documented link --> Raspberry Pi / app
                                                     |
                                                    MQTT
                                                     |
                                                 MQTT broker
                                                     |
                                                Wi-Fi / MQTT
                                                     |
Membership card --> RC522 -- SPI jumper wires --> dedicated ESP32
```

1. Boot the Pi with its suitable power supply and connect it to the local
   network. Record its model, OS, CPU architecture, and network address.
2. Establish the MQTT broker's reachable hostname/address. If it runs on the
   Pi, the ESP32 must use the Pi's network address rather than `localhost`.
   A stable address or DHCP reservation makes repeat setup easier.
3. Place the CF600 in the intended checkout area and the membership reader
   beside it with clear product/card labels. Keep loose product tags outside
   the tested reading area until deliberately included in a scan.
4. Leave access to the ESP32's USB connector for upload and serial diagnosis.
   Secure the boards and route cables so presenting a card or moving products
   does not pull out the breadboard connections.

The ESP32 needs access to its configured Wi-Fi, MQTT broker, and `NTP_HOST`.
Its clock must synchronize before it accepts timed scan commands. The current
firmware uses plain MQTT, normally port `1883`, so use a trusted isolated LAN.
It requires a firmware TLS transport change before use on an untrusted network;
the backend's `MQTT_TLS` setting alone does not add TLS to the ESP32.

## 3. Connect and check the barcode scanner

1. Confirm the scanner model and input mode. For the existing implementation,
   configure keyboard input mode and an Enter suffix using the scanner's own
   manual. A serial or vendor-specific scanner needs an additional integration.
2. Connect it to the browser workstation. Scan a real product barcode into a
   text editor first and compare every digit with the printed code, including
   leading zeros. Confirm that one scan produces one code followed by Enter.
3. In the application's product registration page (`/products`, administrator
   login required), focus the UPC field and scan again. Confirm the full value
   is entered and Enter moves focus to the EPC field.
4. Repeat for all four demonstration products. Record each printed UPC with
   its intended product; the application's UPC field accepts up to 13 digits.

Manual typing can help diagnose a field, but a physical scanner check requires
an actual scan of each printed barcode.

## 4. Connect the CF600 and identify the four product tags

Before connecting the reader, obtain its manual and the CF600 SDK/examples
provided through Omnivox. The repository has not established whether the
actual reader uses USB, serial, or a network connection, nor its supply or
connection settings. Use the actual unit's documented power source and
interface; those details determine the cable and host setup.

1. Connect and power the CF600 according to that documentation, with its host
   connection terminating at the Pi.
2. Verify that the supplied SDK supports the Pi's OS and CPU architecture.
   Run the vendor's inventory example on the Pi and record the SDK version,
   connection settings, sample command, and output. A successful scan on
   another computer does not establish Pi compatibility.
3. Present one UHF tag at a time and capture its **complete EPC**. Match it to
   the reference photograph and record the associated product and UPC below.
   Preserve all leading zeros. Confirm any SDK representation/normalization
   against the actual tag output.
4. Attach or label one tag for each demonstration product. Use placement and
   reader settings from the supplied reader/tag documentation, then test the
   arrangement with the actual products.
5. Place all four tagged products in the reading area together. Verify that
   one inventory session discovers all four complete EPCs. Repeated reads of
   a tag should resolve to the same identifier.

Record the tags in photograph order, from left to right:

| Reference tag | Full EPC (reader-confirmed) | Actual product / printed UPC |
| --- | --- | --- |
| Suffix `4965` | To capture | To record |
| Suffix `4970` | To capture | To record |
| Suffix `4968` | To capture | To record |
| Suffix `4951` | To capture | To record |

The suffixes identify the tags; they are not full EPCs. Register only the
reader-confirmed complete values. Each tag identifies one product and can be
reused in later purchases while stock remains. It is not a tag for each unit
of inventory, and selling a product does not require resetting its tag.

**Application integration dependency:** the supplied SDK must still be wired
into the adapter in
[product_reader.py](smartshop/hardware/product_reader.py). The default real
reader currently reports `CF600 SDK unavailable`.
`python -m scripts.scan_products --fake ...` only exercises synthetic input;
it is not a CF600 hardware diagnostic. After implementing the adapter, use
the verified product setup in the README and receive stock before testing
checkout. Product registration alone starts with zero stock.

## 5. Wire the dedicated ESP32 membership reader

Disconnect power before adding or changing jumper wires. Mount the ESP32 and
RC522 so their pins are accessible and different signals do not share a
breadboard connection. Check the breadboard's rail continuity before relying
on a power rail.

The current
[membership sketch](firmware/esp32/membershipReader/membershipReader.ino)
uses these connections, matching the local `requirements/ESP32-RFID.pdf`:

| RC522 pin | ESP32 connection |
| --- | --- |
| VCC / 3.3V | **3V3 (3.3 V)** |
| RST | GPIO 4 |
| GND | GND |
| IRQ | Leave unconnected |
| MISO | GPIO 19 |
| MOSI | GPIO 23 |
| SCK | GPIO 18 |
| SS / SDA | GPIO 5 |

Use ESP32 **GPIO numbers**, not header positions. Confirm the actual board's
pin labels before wiring; the generic target does not establish a pinout for
every ESP32 variant. The RC522's `SDA` label is used as SPI chip select in
this setup. Connect its supply to 3.3 V, not the ESP32's 5 V/VIN pin. Both
boards must share GND.

Inspect all seven connections, then power the ESP32 through its USB data cable.
The RC522 is powered from the ESP32's 3V3/GND connections; it has no separate
Pi GPIO connection. Keep the refrigerator sketches on their existing boards.

### Load the membership firmware

1. Confirm the ESP32 model, matching PlatformIO board target, and USB serial
   port. The checked-in target is `esp32dev`; adjust it locally if the actual
   board requires another target and confirm the GPIO mapping above.
2. Copy
   [secrets.example.h](firmware/esp32/membershipReader/secrets.example.h) to
   `secrets.h` in the same directory. Set Wi-Fi credentials, `MQTT_HOST`,
   `MQTT_PORT`, the reader's broker credentials, `MEMBERSHIP_TOPIC`, and a
   reachable `NTP_HOST`. Keep `secrets.h` local and uncommitted.
3. With PlatformIO installed, build and upload from the repository root,
   replacing `/dev/YOUR_PORT` with the confirmed serial port:

   ```sh
   pio run -d firmware/esp32/membershipReader
   pio run -d firmware/esp32/membershipReader -t upload \
     --upload-port /dev/YOUR_PORT
   pio device monitor --port /dev/YOUR_PORT --baud 115200
   ```

The current firmware prints a UID only after the backend arms a scan. Merely
holding a card over a powered reader is not a complete test.

## 6. Check membership communication on the Pi

Configure broker permissions for one backend and one membership reader:

| Topic (default prefix) | Publisher | Subscriber |
| --- | --- | --- |
| `SmartShop/membership/command` | Backend | ESP32 |
| `SmartShop/membership/event` | ESP32 | Backend |
| `SmartShop/membership/status` | ESP32 | Backend |

Use separate broker identities for these roles and restrict access accordingly.
The prefix must agree in the Pi's `.env` and the ESP32's `secrets.h`. Commands
and events are non-retained. The full contract is in
[phase3-design.md](docs/phase3-design.md).

For a Phase 3 hardware run, set these switches in `.env` after completing the
README's application setup, and supply the real broker address/credentials:

```dotenv
FRIDGE_SERVICES_ENABLED=false
GMAIL_SERVICE_ENABLED=false
MEMBERSHIP_SERVICE_ENABLED=true
FAKE_READERS_ENABLED=false
```

These switches matter because the example configuration enables refrigerator
and Gmail services by default. Keep one application process responsible for the
physical readers. Run the membership diagnostic separately while the app is
stopped, using the configured Python environment on the Pi:

```sh
python -m scripts.check_membership
```

Wait for the prompt, remove any card already resting on the RC522, then present
one card within 60 seconds. Check that the diagnostic and the ESP32 serial
monitor show the same UID, including leading zero bytes. The diagnostic does
not link a customer account. After it exits, start the app and enroll the card
from `/account/card` while logged in, explicitly confirm it, then test loyalty
identification during checkout. One reader serves one operation at a time.

## 7. Physical acceptance checklist

Record actual device models, connection details, scan output, and outcomes;
the checks below are pending until performed on the assembled hardware.

- [ ] Each printed UPC reaches the correct browser field through the physical
  barcode scanner, including leading zeros and scan termination.
- [ ] The CF600 vendor sample runs on the target Pi and captures each full EPC
  plus all four tags together in the intended product arrangement.
- [ ] After SDK adapter integration and verified catalog/stock setup, a live
  application scan adds all four products once each despite repeated reads.
- [ ] The actual ESP32/RC522 returns matching UIDs over serial and MQTT, and a
  real card can be enrolled and explicitly selected for a purchase.
- [ ] A card left on the RC522 before arming requires removal and a fresh
  presentation. A disconnect/reconnect requires a newly armed operation.
- [ ] Two successive physical checkouts can reuse the same tag without
  resetting it while stock remains.
- [ ] A member checkout produces the expected receipt, points, and stock
  change, and a deliberate test receipt reaches the authorized test mailbox.

If the scanner produces no text, check its host, field focus, and input mode.
If membership is disconnected, check power, GPIO wiring, Wi-Fi, broker address,
credentials, and topic permissions. If it connects but will not scan, check
clock synchronization and remove/re-present the card after arming. For CF600
errors, establish successful vendor-sample output on the Pi before debugging
the application adapter.

See [phase3-verification.md](docs/phase3-verification.md) for the remaining
integration dependencies. Fake-reader tests and generic firmware compilation
do not establish that this physical setup works.
