# Phase 3 verification and handoff — 2026-11-10

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
| CF600 SDK and Pi compatibility | Operator obtains Omnivox SDK/examples and records Pi model, OS, architecture, USB/serial/network transport, runtime/library ABI and a successful sample command/output. Then implement the transport behind ProductReader. Settle another integration approach with the user if it cannot run on the Pi. | 0, 7, 13 |
| Full four-product mapping | Operator captures each complete EPC and all four together, reconciles with photograph suffix order 4965/4970/4968/4951, supplies actual names/categories/prices/UPCs/producers and initial quantities, runs verified setup and receptions. Never derive full EPC zero counts from suffixes. | 0, 2, 7, 8, 13 |
| Physical barcode scanner | Operator records model and input method, scans real printed UPCs into registration/lookup, checks terminator/leading zeros/unknown/repeated scans. A different transport may need an additional adapter. | 0, 6, 13 |
| Actual ESP32/RC522/card | Operator confirms board/FQBN and wiring, compiles for that board, configures ignored secrets and broker ACLs, uploads, captures normalized real UID via serial and MQTT on the Pi. Test removal/presentation after arm, enrollment, replacement, two browsers, expiry, disconnect/reconnect and replay. | 0, 8A, 8B, 13 |
| Target database and broker | Operator records actual database/broker host, verifies Pi reachability and DB backups/privileges, rehearses migration against a copy of deployed data. Enable membership independently of fridge/Gmail, verify ACLs, then full hardware mode. | 0, 13 |
| Receipt sender | Operator verifies sender domain and customer-recipient permissions, runs one deliberate member checkout to an authorized test email, verifies saved receipt and mailbox agree, then tests failed delivery and retry. | 0, 11 live check, 13 |
| Physical regression/demo | Operator verifies dashboard and fan on the configured Pi, all four actual tags together, two successive purchases of the same tag without reset, stock ledger/points/account/receipt, guest checkout and cancellation. | 13 |

None of these physical checks has been marked complete based on mocks or the
firmware build. Reader identification and transport remain separate for CF600
product tags and RC522 membership UIDs. The SDK is not redistributed.
