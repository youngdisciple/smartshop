# SmartShop project index

Inspected 2026-11-12, including the local `requirements/Phase-3.pdf`.

| Area | Entry points and responsibility |
| --- | --- |
| Application | `app.py` serves; `smartshop/__init__.py` constructs Flask without external I/O; `config.py` loads settings; `runtime.py` owns shared services and shutdown. |
| Persistence | `smartshop/models/` defines customers, products, receptions, carts, purchases and membership cards. `services/migrations.py` upgrades SQLite/MySQL schemas. |
| Catalog | `services/catalog.py` validates UPC/EPC, money and receptions; `routes/shop.py` protects administrative product/inventory operations. |
| Checkout | `services/checkout.py` deduplicates reusable tags, reviews prices and atomically saves purchases/stock/points. Shop routes own browser carts, accept UPC scans and quantity edits, and poll RFID scans. |
| Product reader | `hardware/product_reader.py` selects adapters and owns exclusive 60-second operations; `hardware/cf600_serial.py` decodes checksum-validated binary CDC-COM inventory; `hardware/cf600.py` retains optional keyboard capture. |
| Membership | `services/membership.py` implements the MQTT reader protocol; `firmware/esp32/membershipReader/` contains RC522 firmware. Membership UIDs remain distinct from product EPCs. |
| Presentation | `templates/`, `static/` and `presentation/i18n.py` provide English/French registration, live cart, account, payment and receipt screens. |
| Security | `security.py`, authentication routes and shop guards provide CSRF, roles, browser ownership and account isolation. |
| Receipts | `services/receipts.py` sends saved receipt snapshots through Gmail SMTP or Resend after purchase commit, with persisted retry state. |
| Refrigerators | Dashboard routes, MQTT, fridge monitor, alerts, Gmail reply reader and fan/LED adapters preserve earlier hardware functionality. |
| Diagnostics/setup | `scripts/setup_shop.py` migrates/promotes admins/imports verified products; `scripts/scan_products.py` runs fake or bounded CF600 HID scans. Other scripts diagnose membership, MQTT and email. |
| Tests | `tests/test_cf600.py` covers input decoding and device lifecycle; existing app/service/phase3 tests cover commerce and integrations; MySQL tests are opt-in. Browser fixture/scripts exercise responsive flows. |

## Requirements and current integration

The Phase 3 PDF requires product CRUD, repeated dated receptions, UPC and EPC
capture, simultaneous multi-product RFID checkout, live cart editing, simulated
payment, accounts, points, history and emailed receipts. English/French UI is a
bonus. Existing commerce software implements these workflows; the HID adapter
connects real EPC observations through the existing scan API without schema or
HTTP changes.

Observed target: Raspberry Pi 5 Model B Rev 1.1, Debian 13, Linux aarch64.
The reader identifies as `CFUSB_HID By YLW28`, USB vendor/product `0483:5750`.
Its stable keyboard path is
`/dev/input/by-id/usb-CFUSB_HID_By_YLW28-if01-event-kbd`.
The separate serial interface does not establish SDK compatibility.

The teacher guide specifies **CDC-COM mode**, confirmed by receiving binary
inventory frames after loading `usbserial vendor=0x0483 product=0x5750`.
The stable port is `/dev/serial/by-id/usb-CFUSB_HID_By_YLW28-if03-port0`.
Set `PRODUCT_READER_BACKEND=cf600_serial`, `CF600_BAUDRATE=57600` and
`FAKE_READERS_ENABLED=false`; install `requirements-pi.txt`. The user needs
`dialout` device access. The adapter opens an exclusive serial connection only
while armed; it sends no commands. Independent scan expiry closes it after 60
seconds. Keep one serving process. See [README](../README.md#reader-and-email-deployment).

A real CRC-valid frame contained EPC `A00000000000000000004965`. Other tags,
all-four inventory and physical checkout remain unverified. The earlier keyboard
assumption was rejected after zero keyboard events were observed; the optional
HID backend is not selected for this reader.

`CF-RU5114+SDK.rar` contains Windows x32/x64 DLLs, C#/Delphi demos and a CF-RU5100
serial protocol manual. Its contents were inspected in memory; the observed CF-header protocol differs
from that older SDK protocol. Serial capture requires no Windows runtime. No SDK binaries are bundled.

## Physical acceptance still required

1. Run the bounded hardware diagnostic; capture each complete EPC, preserving zeros.
2. Present all four tags together and confirm four distinct outputs. Keyboard
   capture cannot create multi-tag capability if the reader emits only one.
3. Register verified products and receive stock; exercise EPC capture and live
   checkout, remove/restore, guest/member purchase and subsequent tag reuse.
4. Verify cancel/expiry/disconnect release the device and rearming works.

Synthetic tests do not establish physical inventory capability or real EPC values.
