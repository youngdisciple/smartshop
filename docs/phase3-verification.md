# Phase 3 verification and handoff — 2026-11-10

## Gmail receipt support — 2026-11-12

Added `RECEIPT_EMAIL_PROVIDER=gmail`, using the existing `GMAIL_ADDRESS` and
`GMAIL_APP_PASSWORD` settings. Local configuration selects Gmail; both credentials
are currently missing and must be entered locally by the operator. SMTP uses
certificate-validated TLS to smtp.gmail.com:465 with an app password. Gmail sends
from the authenticated address to the purchase's saved recipient; it does not
use the fridge alert destination or the Resend sender. Guest receipts do not send.
The incoming Gmail polling switch remains independent.

Full suite: 86 tests ran, 84 passed and two opt-in MySQL tests skipped. Five new
mock-SMTP tests check TLS verification, credentials, French quantity-aware
content, recipient isolation, login/network/recipient failures, retries without
repeating sales, successful-send suppression and guest behavior. Fake fixtures
explicitly select Resend with no key to isolate them from local Gmail credentials.
No live SMTP login or email was attempted. Gmail acceptance/inbox delivery remains
an operator check. SMTP retries can duplicate an ambiguously accepted message;
the stable Message-ID does not provide Resend-style provider idempotency.

## Checkout barcode and quantity verification — 2026-11-12

Checkout now accepts keyboard-wedge UPC input with Enter/Tab terminators and a
submit button, without requiring an RFID lease. Repeated UPC scans increment a
single product line. The operator selected +/− controls for deliberate RFID
quantity increases; repeated RFID observations remain deduplicated and preserve
edited quantities. Decreasing to zero removes/suppresses the product; explicit
barcode scanning or Add back restores it. Increases are capped at stock.

The current full unittest run completed 81 tests: 79 passed and two isolated
MySQL tests were skipped. Five new checkout tests cover mixed inputs, repeated
barcodes, removal/suppression, stock caps, ownership, validation, quantities
through payment/receipts/points, duplicate payment and full stock rollback.
Five registration UI Node tests also pass. Chromium regression passed UPC
Enter/Tab, +/−, mixed RFID polling without quantity resets, quantity-aware
payment/receipt, existing member checkout, French and mobile overflow checks.
The browser sequence stays within stock remaining from its earlier purchase.
Syntax/compile checks and `git diff --check` pass. No schema migration is needed.

## CF600 CDC-COM update — 2026-11-12

The teacher's guide specifies CDC-COM. Keyboard captures received no events;
the earlier HID assumption did not match the attached reader's output mode.
After the operator loaded `usbserial vendor=0x0483 product=0x5750`, Linux exposed
`/dev/serial/by-id/usb-CFUSB_HID_By_YLW28-if03-port0` (currently ttyUSB0).
A passive 57600-baud serial capture received 1539 bytes, including repeated
inventory frames with EPC **A00000000000000000004965**. CRC validation passed
on the recorded packet. No serial commands or tag writes were sent.

The new `cf600_serial` backend validates CF-header frames, length, inventory
command/status and CRC; it recovers from fragmented/coalesced/corrupt input.
Pyserial 3.5 is installed in the virtual environment. Local `.env` now selects
serial mode and the stable port. Restart the app to apply it. No permissions,
reader configuration or product database records were modified by this work.
The optional HID backend remains available but is not selected here.

Validation: the full Python suite ran 75 tests, with 73 passing and two opt-in
MySQL tests skipped. The Chromium browser regression also passed. Its reception
date fixture now uses the local calendar date, matching server validation after
UTC midnight. A subsequently added serial registration/checkout workflow
test also passed, including four synthetic tags, repeated observations,
remove/restore and two purchases with reusable tags. Three Node tests pass for
single-loop polling, visible waiting/capture states, stale-result cancellation,
multiple tags and retry after reader errors. Fake fixtures now explicitly disable
the physical backend so they remain isolated when the local `.env` enables serial.

A three-second and a later 20-second diagnostic using the new adapter armed and
released successfully but received no EPCs during those windows; the real EPC
above came from the earlier raw serial capture and is covered by a recorded-packet
decoder test. Other full EPCs, all four presented together and a physical web
checkout still require confirmation. Earlier verification below is historical.

## Observed software evidence

* Full unittest run with the isolated MySQL socket enabled: **54 tests pass**.
  Without that explicit setting, the two isolated database tests are skipped.
  Existing fridge monitoring, alert, Gmail, GPIO and lifecycle regression tests
  remain in the suite. No physical fan was activated.
* SQLite fresh schema and representative legacy-customer migration pass, including
  repeat migration, unchanged password hash/contact fields and uniqueness rules.
* An isolated **MariaDB 13.0.2** instance, InnoDB, Unix socket under `/tmp`, no
  TCP listener, passes legacy migration and competing-payment/duplicate tests.
  This is real database evidence for the MySQL dialect, not evidence about the
  deployed Pi's server, privileges, database contents or exact MySQL version.
* Tests cover four clearly synthetic DE-prefixed EPCs with the reference suffix
  order, multiple tags, repeat reads, suppression/restore, unknown/out-of-stock
  products, reader failure, separate browser ownership, payment cancellation/
  failure, rollback, duplicate submissions and two successive purchases with a
  reusable tag. Physical EPC mappings remain unseeded.
* Membership fake-MQTT tests cover invalid UID lengths, leading zero bytes,
  malformed/retained/stale/wrong-operation/wrong-epoch/duplicate events, heartbeat
  loss, disconnect/reconnect, busy readers, timeout, cancellation, authenticated
  linking/replacement and conflicts. Scanning a card never logs a customer in.
* Receipt tests check saved item names/prices, customer ownership, saved recipient,
  French receipt text, provider payload/idempotency, failure and retry without
  repeating the sale. Requests are mocked; no live customer emails were sent.
* Firmware compiled successfully with PlatformIO 6.1.18, espressif32 6.12.0,
  Arduino core 2.0.17, esp32dev target, MFRC522 1.4.12, PubSubClient 2.8.0,
  ArduinoJson 7.4.2. Result: 45,284 bytes RAM, 786,289 bytes flash. No historical
  MFRC522 patch needed. This is a generic ESP32 Dev Module build, not a confirmed
  actual-board build or upload.
* Headless Chromium 141 / Playwright 1.56.1 exercised the visible flow: admin
  product registration → receptions → customer signup → card enrollment → four
  simultaneous fake tag observations plus duplicate → remove → card identification
  and explicit confirmation → failed payment → successful payment → receipt →
  account history → French. No JavaScript errors. Desktop 1440px and mobile
  390px pages checked; no page-wide horizontal overflow. Narrow cart/receipt rows
  are stacked so action buttons remain visible. Product/history tables have
  keyboard-focusable scrolling regions. Screenshots were inspected locally.
* `compileall`, JavaScript syntax checks and `git diff --check` pass. App/module
  construction remains free of device connections, worker startup and database I/O.

Reproduce the automated flow using README commands. Browser test data and
credentials exist only in the explicitly invoked disposable fixture server;
never run it as a deployment entry point. No changes were committed; existing
user changes to `.gitignore`, requirements and `.codex` were preserved.

## Remaining evidence required from the operator

| Dependency | Owner and exact next step | Tasks affected |
| --- | --- | --- |
| CF600 physical serial verification | CDC-COM driver/port and one real CRC-valid EPC confirmed; serial adapter implemented. Capture the other tags, all four together and verify physical registration/checkout. The older SDK protocol is not used. | 0, 7, 13 |
| Full four-product mapping | Operator captures each complete EPC and all four together, reconciles with photograph suffix order 4965/4970/4968/4951, supplies actual names/categories/prices/UPCs/producers and initial quantities, runs verified setup and receptions. Never derive full EPC zero counts from suffixes. | 0, 2, 7, 8, 13 |
| Physical barcode scanner | Operator records model and input method, scans real printed UPCs into registration/lookup, checks terminator/leading zeros/unknown/repeated scans. A different transport may need an additional adapter. | 0, 6, 13 |
| Actual ESP32/RC522/card | Operator confirms board/FQBN and wiring, compiles for that board, configures ignored secrets and broker ACLs, uploads, captures normalized real UID via serial and MQTT on the Pi. Test removal/presentation after arm, enrollment, replacement, two browsers, expiry, disconnect/reconnect and replay. | 0, 8A, 8B, 13 |
| Target database and broker | Operator records actual database/broker host, verifies Pi reachability and DB backups/privileges, rehearses migration against a copy of deployed data. Enable membership independently of fridge/Gmail, verify ACLs, then full hardware mode. | 0, 13 |
| Receipt sender | Operator verifies sender domain and customer-recipient permissions, runs one deliberate member checkout to an authorized test email, verifies saved receipt and mailbox agree, then tests failed delivery and retry. | 0, 11 live check, 13 |
| Physical regression/demo | Operator verifies dashboard and fan on the configured Pi, all four actual tags together, two successive purchases of the same tag without reset, stock ledger/points/account/receipt, guest checkout and cancellation. | 13 |

None of these physical checks has been marked complete based on mocks or the
firmware build. Reader identification and transport remain separate for CF600
product tags and RC522 membership UIDs. The SDK is not redistributed.
