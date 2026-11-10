# Phase 3 implementation guide

Source: [Phase-3.pdf](Phase-3.pdf). This guide breaks the assignment into
tasks that can be implemented individually in the existing SmartShop
repository.

## Confirmed scope: four products and four physical RFID tags

The user has confirmed that this implementation will use **four products,
each mapped to one of four actual UHF RFID tags**. The database product
records must correspond to those physical tags.

The identifier reference is [RFID_TAGS.jpeg](RFID_TAGS.jpeg) in this
repository's `requirements/` directory. From left to right, the printed tag
identifiers end in:

| Product mapping | Physical tag identifier suffix |
| --- | --- |
| Product 1 | `4965` |
| Product 2 | `4970` |
| Product 3 | `4968` |
| Product 4 | `4951` |

These suffixes identify the tags in the photograph; they are **not complete
EPC values**. Read the full identifiers from the image and confirm them with
the reader before persisting the mapping. Preserve the complete EPC as a
string, including all leading characters and zeros. Do not guess the number
of zeros, generate replacement EPCs, or use only the suffix for lookup.
If the SDK returns a different representation, document and verify its
normalization against the physical tags.

Product names, categories, prices, UPCs, and producers have not yet been
specified by this notice. Do not treat the labels Product 1–4 as confirmed
commercial product names. Make any development placeholder metadata explicit.

Use this four-product mapping for seed/setup data, fake-reader fixtures,
checkout demonstrations, and physical verification. Re-running setup must
not create duplicate products or tag mappings. Keep the PDF's product CRUD
and repeated stock reception features; four is the confirmed demonstration
dataset, not a reason to remove those features.

### Confirmed tag behavior

Each UHF tag is a **reusable product identifier**, not an individually sold
physical unit. In one checkout, each distinct tag adds one unit of its mapped
product; repeated reads add nothing. A successful purchase deducts one unit
from that product's stock. The same tag may be used in another checkout while
stock remains, without resetting the tag or receiving stock after every sale.
Multiple stock receptions are independent of the number of physical tags.
Do not implement permanently sold tags or require tag reactivation after sale.

## Confirmed membership hardware and enrollment

Reference: [ESP32-RFID.pdf](ESP32-RFID.pdf). The user confirmed a separate
ESP32 + RC522 reader mounted on a breadboard for membership cards, using
**Wi-Fi + MQTT** and **customer self-enrollment**. The CF600 handles the four
product tags; the ESP32/RC522 handles membership cards. Keep these identifiers
and their scan workflows separate.

The PDF's sample reads card UIDs and prints them over USB serial at 115200
baud. It does not implement MQTT, customer association, or checkout delivery.
Its wiring is:

| RC522 pin | ESP32 connection |
| --- | --- |
| Vcc | 3.3 V |
| RST | GPIO 4 |
| GND | GND |
| IRQ | Not connected |
| MISO | GPIO 19 |
| MOSI | GPIO 23 |
| SCK | GPIO 18 |
| SS/SDA | GPIO 5 |

Use SPI and the MFRC522 library as the starting point. Verify the actual
library version and build rather than blindly applying the PDF's historical
library patch. This is a dedicated membership ESP32 sketch; do not overwrite
the refrigerator sketches or assume their pin assignments apply to this board.

The following are planning defaults established during the blind-spot pass,
not extra PDF requirements:

- A logged-in customer starts enrollment from their account, presents an
  unassigned card, and explicitly confirms linking it to their account.
- Store the generated membership number separately from the physical card
  UID. Normalize UID bytes to uppercase hexadecimal, two characters per byte,
  without spaces; preserve leading zero bytes and support the reader's actual
  UID lengths. Do not apply product EPC limits to membership UIDs.
- Allow one active card per customer. Explicit authenticated replacement
  unlinks the previous card; reject a UID already assigned to another customer.
- At checkout, a card identifies the loyalty account only. It does not log
  the user in or expose private account history. Unknown cards allow retry or
  guest checkout; they do not silently create or enroll an account.
- Use dedicated membership MQTT topics, outside `Frig1/#` and `Frig2/#`.
  Keep credentials in local configuration, with placeholder examples only.
- One physical membership reader serves one operation at a time: enrollment
  or checkout identification. Bind it to the requesting session and show busy
  feedback to competing sessions.
- Arm the reader with a unique operation identifier and purpose; events must
  echo that identifier. Accept only the matching active operation. Use
  non-retained commands/events, deduplicate event delivery, and expire an
  operation after 60 seconds. Invalidate on cancellation, logout, completion,
  or disconnect; reconnect requires a newly armed operation.
- Require a fresh card presentation after arming. Previously observed or
  replayed cards must not identify the next customer. Confirm the selected
  membership before associating it with a checkout.

Document the exact MQTT topics and message contract in the design task before
implementing firmware and backend consumers. Keep UID handling out of product
lookup and keep enrollment separate from payment.

## How to use this guide

Start a session with:

> Implement Task N from `requirements/PHASE-3-IMPLEMENTATION.md`. Read
> `AGENTS.md`, inspect the current implementation and progress notes, and
> complete the task with the relevant tests and documentation. Update this
> guide with the outcome and any remaining blockers.

Work in the order below. A task is complete when its acceptance criteria are
met and its relevant automated checks pass. Record hardware verification
separately; mocked tests do not establish that a physical reader works. If an
SDK, device, or configuration is missing, implement and test the independent
work, then document the exact remaining dependency instead of marking the task
complete.

Keep changes focused. Follow the repository's conventional commit guidance and
split work into small logical commits when committing. Do not commit
credentials or local configuration.

The user plans to select xhigh reasoning for implementation sessions; this
document does not change the model's reasoning setting.

A prompt cannot automatically open a new session or clear context after each
task. The user may start a fresh session manually, or continue in one session
with context compaction. This guide and its handoff notes carry progress
between sessions. Start with **Task 0**, then Task 1; Tasks 8A and 8B are new
insertions that preserve the original task numbers.

## Existing foundation

At the time this guide was created:

- Flask uses an application factory and separate routes, models, services,
  hardware adapters, and templates.
- Customer signup stores hashed passwords, but customer login, memberships,
  points, and purchase history are not implemented.
- The admin page lists customers; product administration is not
  implemented.
- Email delivery exists for refrigerator alerts and can inform receipt
  delivery implementation.
- Startup creates missing tables but does not migrate existing tables.
- Refrigerator monitoring and fan control must continue to work. Imports
  and application construction must remain free of network connections, worker
  startup, and GPIO initialization.

Inspect the current code before each task; this baseline will become outdated
as work progresses.

## Decisions to settle in Task 1

- Design around the confirmed four products, each mapped to its own physical
  tag as described above. A separate tag table is optional if justified by the
  design; multiple tags per product are not required for this dataset. The
  product registration flow must support EPC entry as required by the PDF.
- Use the confirmed reusable-product-tag behavior above. Deduplicate within
  each checkout and protect against duplicate payment submissions, while
  permitting legitimate later purchases with the same tag.
- Define whether tags are registered during product creation, stock
  reception, or both, and how tag counts relate to received quantities. Do not
  count registration itself as additional stock.
- Define stock calculation, including receipts and completed sales. Cart
  scans and failed payments must not reduce stock.
- Choose a points formula, rounding rule, and policy for guest purchases.
  The PDF leaves the strategy to the students.
- Design membership UID associations, self-enrollment, replacement, and the
  MQTT operation contract using the confirmed hardware and defaults above.
  Membership identification must not grant access to private account history.
- Use exact decimal arithmetic or integer minor units for money. Decide
  whether totals include taxes; the PDF does not require tax calculation.
- Preserve historical purchase names and prices when products change.
  Prefer archiving sold products if physical deletion would break history.
- Define administrator access without allowing ordinary signup to grant
  administrative privileges.
- Obtain the CF600 UHF desktop reader SDK and examples from Omnivox early.
  Confirm host OS, connection method, and SDK compatibility before choosing an
  integration approach.

These are implementation decisions, not additional requirements from the PDF.
Record chosen policies below so later tasks use them consistently.

## Blind-spot findings and unresolved prerequisites

These findings were inspected in the repository; recheck them before making
changes because future tasks may resolve them.

- The CF600 will connect to the Raspberry Pi. The user has seen the four UHF
  tags detected, but SDK availability, Pi compatibility, transport, and
  application integration have not been checked. No SDK was found in the
  inspected repository. Do not claim working Pi integration from tag detection.
- A physical barcode scanner and the products' printed UPCs are unverified.
  UHF detection does not establish barcode support. Manual input is a
  development aid, not evidence that the barcode requirement is complete.
- Full EPCs still need reader confirmation. Product metadata and initial
  quantities are not confirmed. Never invent production seed data silently.
- Physical membership cards, actual UID values, breadboard operation, Wi-Fi
  configuration, and MQTT communication still require verification.
- MySQL is configured on `localhost`; establish that it runs on the Pi or
  make database host configuration explicit. SQLite test success alone does
  not verify MySQL migration and transaction behavior.
- `requirements-pi.txt` is referenced by repository instructions but absent.
  Reconcile Pi dependency installation and document the firmware toolchain.
- Normal application startup starts fridge MQTT/Gmail workers and requires
  an MQTT host. Provide explicit service switches for checkout development:
  membership MQTT must be usable without starting fridge/Gmail/fan services.
  Preserve the full existing hardware mode and side-effect-free app creation.
- The existing sender targets a configured alert recipient. Verify receipt
  delivery to customer addresses and provide separate receipt status/retry
  handling; alert delivery alone does not establish receipt delivery.
- Define administrator provisioning; public signup must not grant admin
  privileges. Signup currently redirects to the admin customer list, so update
  that redirect, navigation, and tests when access control is introduced.
- The original `.gitignore` excluded all of `requirements/`. This guide now
  has an exception, but the PDF/image references remain local, ignored assets.
  They must be supplied in a new checkout or deliberately included if sharing
  is appropriate. Do not mark reference availability verified in a new clone
  without checking. No SDK redistribution permission has been established.

Do not reopen confirmed user choices as unresolved preferences. Distinguish
confirmed choices, planning defaults, missing facts, mocked checks, and actual
hardware evidence in every handoff. Resolve architecture-changing unknowns
before implementing dependent components; complete independent work and record
blockers when hardware is unavailable.

## Task checklist

- [ ] Task 0 — Hardware, reference, and deployment discovery
- [x] Task 1 — Database design and business rules
- [ ] Task 2 — Models and database migrations
- [x] Task 3 — Product administration
- [x] Task 4 — Stock reception and inventory dashboard
- [x] Task 5 — Customer authentication and access control
- [ ] Task 6 — Barcode scanner integration
- [ ] Task 7 — CF600 RFID integration
- [ ] Task 8 — Live shopping cart
- [ ] Task 8A — ESP32 membership firmware and MQTT service
- [ ] Task 8B — Customer membership-card self-enrollment
- [x] Task 9 — Membership identification and simulated payment
- [x] Task 10 — Purchase finalization and loyalty points
- [x] Task 11 — Receipts and receipt email
- [x] Task 12 — Customer account and purchase history
- [ ] Task 13 — End-to-end verification and submission documentation
- [x] Task 14 — English/French interface (included bonus deliverable)
- [x] Task 15 — Responsive UI polish (included bonus deliverable)

## Task 0 — Hardware, reference, and deployment discovery

**Deliverable:** a prerequisite report with evidence, missing dependencies,
and architecture constraints. Do this before selecting the reader integration.

Directions:

- Verify availability of all three local reference files linked above.
- Obtain the CF600 SDK/sample from Omnivox; record Pi model, OS, architecture,
  reader connection, supported runtime, and a reproducible sample command.
- Capture full EPC output for each reference tag and all four together.
  Establish the product-to-tag mapping and collect product metadata, UPCs,
  initial stock quantities, and actual barcode-scanner details.
- Verify ESP32/RC522 and membership card availability; test the supplied UID
  example and record toolchain/library versions and sample UID output.
- Establish database and MQTT broker locations, network connectivity, and
  receipt sender readiness. Do not record passwords or API keys in reports.
- Inspect the deployment/documentation issues listed above. Resolve or propose
  a concrete resolution for each in the Task 1 design.

**Acceptance:** facts have supporting evidence; missing facts have explicit
owners/next steps. If the SDK cannot run on the Pi, settle a viable approach
with the user before reader integration. A report may be written while blocked,
but hardware compatibility must not be marked verified without a live check.

## Task 1 — Database design and business rules

**Depends on:** Task 0 findings. Independent design may proceed while physical
verification is blocked, with the affected decisions explicitly deferred.

**Deliverable:** a short design document and ER diagram, with no need to
implement checkout yet.

Directions:

- Inspect existing customer data, configuration, routes, and startup
  behavior.
- Define entities, fields, keys, relationships, validation constraints, and
  deletion policies for products, stock receptions, RFID tags, customers,
  purchases, and purchase items.
- Resolve and document the decisions listed above. Explicitly identify
  decisions that depend on the supplied SDK or hardware.
- Include membership uniqueness, authentication, receipt ownership, price
  snapshots, stock consistency, and duplicate checkout protection in the
  design.
- Define a migration approach that preserves existing customers.
- Include membership-card associations, operation ownership/expiration, MQTT
  topics and messages, reader lifecycle, admin provisioning, and independent
  service switches. Keep reader transport behind an adapter for mocked tests.

**Acceptance:** the schema supports every required PDF workflow, the ER diagram
matches the proposed schema, and later tasks can use the documented rules
without inventing conflicting policies.

## Task 2 — Models and database migrations

**Depends on:** Task 1.

Directions:

- Implement the approved models and relationships in `smartshop/models/`.
- Provide repeatable setup/seed data for the four confirmed product-to-tag
  mappings, using verified full EPCs and clearly identified product metadata.
- Add unique, automatically generated customer membership numbers and
  points initialized according to the chosen policy.
- Add a repeatable migration process for existing databases. Do not rely on
  `create_all()` to alter existing tables.
- Document setup for both a new database and an existing installation.

**Acceptance:** a fresh database and a representative existing database reach
the intended schema; existing customer fields and password hashes survive;
constraints and relationships have relevant regression coverage.

## Task 3 — Product administration

**Depends on:** Task 2. Apply Task 5 access controls once available.

Directions:

- Add product list, registration, edit, and delete/archive operations.
- Support name, category, unit price, UPC (maximum 13 characters), EPC
  (maximum 24 characters), and producer company through the designed
  product/tag relationship.
- Treat UPC and EPC as strings so leading zeros survive.
- Validate identifiers, prices, required fields, and duplicate entries on
  the server.
- Preserve historical sales when deleting or archiving a product.
- Delete unused products where safe; archive products referenced by sales.
- Show informative success and error notifications.

**Acceptance:** valid operations persist correctly; invalid input is rejected;
editing or deleting a product cannot corrupt past purchases. Cover changed
routes with tests.

## Task 4 — Stock reception and inventory dashboard

**Depends on:** Tasks 2–3.

Directions:

- Record multiple receptions per product, each with quantity and date
  received.
- Validate positive quantities and valid dates.
- Display total current stock clearly and provide reception history.
- Implement the selected tag registration policy without double-counting
  inventory.
- Show notifications for reception operations.

**Acceptance:** receiving the same product twice preserves both receptions and
produces the correct stock total; invalid receptions do not change stock.
Completed sales will integrate with this stock model in Task 10.

## Task 5 — Customer authentication and access control

**Depends on:** Task 2.

Directions:

- Extend existing signup as needed; preserve secure password hashing.
- Implement login, logout, session handling, and protected account routes.
- Implement the chosen administrator access policy and protect
  product/inventory mutations from unauthorized users.
- Apply appropriate request protections to state-changing forms and routes.
- Keep authentication errors useful without exposing credentials.
- Provide deliberate administrator provisioning and redirect customer signup
  to an appropriate customer page rather than the protected admin list.

**Acceptance:** customers can sign up, log in, and log out; unauthorized
requests cannot access private account data or administer products and stock.
Relevant access-control and authentication tests pass.

## Task 6 — Barcode scanner integration

**Depends on:** Task 3.

Directions:

- Confirm the actual scanner's input method; support its UPC input in
  product registration and lookup.
- Handle scan termination, leading zeros, invalid lengths, unknown UPCs,
  and repeated input appropriately.
- Keep manual input available for development and diagnostics.

**Acceptance:** a known barcode resolves to the correct product, an unknown
code produces a clear message, and the input path has automated coverage.
Record a separate physical scanner check.

## Task 7 — CF600 RFID integration

**Depends on:** Tasks 2–4 and the SDK from Omnivox.

Directions:

- Inspect the supplied SDK and implement a reader adapter under
  `smartshop/hardware/`, with orchestration in services as needed.
- Support inventory scans that discover multiple tags in a single scan
  session; do not require scanning products one by one.
- Also support capturing a product EPC during product registration/editing.
- Give the CF600 one active scan operation at a time, with ownership bound to
  the requesting session. Isolate registration scans from checkout scans and
  show busy feedback to other sessions. Clear stale observations between
  operations; stop accepting product reads during payment and after completion.
- Normalize EPC input consistently, deduplicate repeated reads of the same
  physical tag, and resolve each of the four physical tags to its corresponding
  database product using its full EPC.
- Report unknown tags and reader connection/read failures clearly.
- Provide fake-reader input for automated testing and a guarded diagnostic
  entry point in `scripts/`.
- Manage reader startup and shutdown explicitly; do not connect during
  imports or application construction.

**Acceptance:** fake-reader tests cover multiple tags, repeated reads, unknown
tags, and failures. A physical CF600 scan verifies multiple tagged products
together, including all four reference tags and their correct product mappings.
If hardware or SDK access is missing, record this task as incomplete
with the remaining verification steps.

## Task 8 — Live shopping cart

**Depends on:** Tasks 4 and 7; fake-reader input can support development.

Directions:

- Connect scan results to an isolated checkout cart.
- Update the product list, quantities, unit prices, line totals, and
  overall total automatically.
- Allow customers to remove unwanted items before confirmation.
- Define how continued reader observations interact with manually removed
  items: suppress them for the rest of that checkout unless the customer
  explicitly adds them back. A new checkout starts with fresh scan state.
- Handle unknown tags and unavailable stock with clear feedback; cart
  changes must not commit a sale.

**Acceptance:** scanning the four reference tags produces four corresponding
product entries, each with quantity one; repeated observations of one tag do
not inflate quantity; removed items behave consistently; separate checkout
sessions do not share carts.

## Task 8A — ESP32 membership firmware and MQTT service

**Depends on:** Tasks 0–2 and the documented MQTT contract. May proceed before
Task 8; complete before Task 8B and Task 9.

Directions:

- Add a dedicated membership sketch under `firmware/esp32/`, preserving the
  matching folder/file naming. Implement the documented RC522 wiring and UID
  normalization, Wi-Fi/MQTT connectivity, explicit arming, operation identifiers,
  fresh presentations, and non-retained scan events.
- Add the backend membership-reader service using separate topics and an
  explicit lifecycle; do not route these events through fridge telemetry.
- Implement operation ownership, 60-second expiry, deduplication, busy state,
  cancellation, disconnect invalidation, and reconnect handling as specified.
- Add local configuration placeholders and a guarded diagnostic script.
  Make the service usable independently of fridge/Gmail/fan workers.

**Acceptance:** fake-MQTT tests cover malformed, stale, duplicated, retained,
wrong-operation, and disconnected events; firmware compiles for the actual
board/library versions; a physical card UID reaches the Pi service through
MQTT. Record physical checks separately from software tests.

## Task 8B — Customer membership-card self-enrollment

**Depends on:** Tasks 5 and 8A.

Directions:

- Add authenticated start, scan-result, confirm, cancel, and replacement
  flows in the customer account. A customer can modify only their own binding.
- Associate the card UID with the generated membership number, preserving
  the distinction between these fields and product EPCs.
- Enforce one active card per customer and unique UID assignment. Linking
  requires explicit confirmation; reject a card assigned to another account.
- Show clear pending, busy, timeout, disconnected, unknown, and success states.

**Acceptance:** authentication/ownership, conflicts, replacement, expiry,
replayed events, competing browser sessions, and cancellation have regression
coverage. A physical card can be enrolled and subsequently recognized, without
granting account access solely from scanning it.

## Task 9 — Membership identification and simulated payment

**Depends on:** Tasks 5, 8, 8A, and 8B.

Directions:

- After product scanning, prompt for an optional membership card through the
  ESP32/RC522 reader and MQTT operation flow. Confirm the selected membership
  before associating it; unknown cards allow retry or guest checkout.
- Associate a valid membership with the purchase or allow guest checkout.
- Let the customer review and confirm the list before entering payment
  simulation.
- Implement explicit simulated success, failure, and cancellation outcomes.
  Do not request real payment credentials.
- Pass a validated checkout attempt to Task 10; do not award points or
  deduct stock merely because the payment screen was opened.

**Acceptance:** member and guest flows work, invalid membership input is
handled, and failed or cancelled payment cannot create a completed sale.

## Task 10 — Purchase finalization and loyalty points

**Depends on:** Tasks 4 and 9.

Directions:

- On successful simulated payment, persist the purchase and price/name
  snapshots, reduce available product stock, and award points according to
  Task 1. Do not mark reusable product tags permanently sold.
- Perform related database changes atomically.
- Revalidate availability and prices according to the agreed policy at
  confirmation time.
- Prevent double submission, refresh, or concurrent attempts from committing
  the same checkout twice, overselling stock, or awarding duplicate points.
  A later legitimate checkout using the same tag is allowed while stock remains.
- Keep external email delivery outside the purchase transaction.

**Acceptance:** success updates all related records once; insufficient stock or
a persistence failure leaves no partial sale; duplicate and competing checkout
attempts cannot oversell stock or duplicate points. Include transaction and
failure-path tests.

## Task 11 — Receipts and receipt email

**Depends on:** Task 10.

Directions:

- Generate receipts from saved purchase data with product name, quantity,
  price, total amount, points earned, and date/time.
- Display a receipt after successful checkout, including for guests.
- Automatically email receipts when a registered customer email is
  available.
- Reuse existing email configuration patterns where appropriate, while
  keeping receipt delivery separate from fridge-alert behavior.
- Handle email failures without losing or repeating the sale; provide a
  clear delivery status and a documented retry approach.

**Acceptance:** on-screen and emailed receipts agree with persisted purchase
data; later product edits do not change old receipts; mocked delivery tests
cover success and failure. Record live email verification separately.

## Task 12 — Customer account and purchase history

**Depends on:** Tasks 5, 10, and 11.

Directions:

- Display the signed-in customer's name, email, membership number, and
  current points.
- List their past purchases and allow access to individual receipts.
- Enforce receipt ownership on the server for all history and receipt
  routes.
- Handle customers with no purchases gracefully.

**Acceptance:** a customer can inspect their own points and receipts; changing
a URL or identifier cannot reveal another customer's history. Include ownership
regression tests.

## Task 13 — End-to-end verification and submission documentation

**Depends on:** Tasks 1–12.

Directions:

- Run `python -m unittest discover -v` and resolve regressions.
- Verify this complete flow: register products → receive stock → scan
  several RFID tags together → remove an item → identify membership → simulate
  payment → inspect reduced stock, awarded points, receipt email, and account
  history.
- Also verify guest checkout, repeated reads, invalid membership, payment
  cancellation/failure, insufficient stock, duplicate submission, and email
  failure.
- Verify physical barcode/RFID operation and live email delivery on the
  configured environment; record evidence and remaining limitations.
- Verify that all four tags from `RFID_TAGS.jpeg` resolve to the intended four
  database products. Complete two successive purchases using the same tag and
  confirm one stock deduction per purchase, without any tag reset.
- Verify customer self-enrollment and replacement with the actual ESP32/RC522
  over MQTT; verify membership identification and guest checkout. Test stale
  events, reader disconnects, expiry, and a competing browser session. Product
  scans must not enroll cards; membership scans must not add products or log in.
- Review notifications for every user operation, including errors.
- Update the README, ER diagram, setup/migration instructions, SDK/device
  prerequisites, and `.env.example` if configuration was added.
- Confirm the existing refrigerator dashboard and service lifecycle still
  work using appropriate automated checks and configured hardware verification.

**Acceptance:** all required PDF features are accounted for, automated checks
pass, and documentation accurately distinguishes verified behavior from
outstanding hardware or integration checks.

## Task 14 — English/French interface

**Depends on:** completed core workflows.

The PDF labels bilingual support a bonus. The user explicitly chose to include
it. Implement it after the core workflows; it is part of the intended delivery.

**Acceptance:** a persistent language selection switches customer and
administrator interface text, validation messages, notifications, and receipt
text between English and French without altering stored identifiers or amounts.

## Task 15 — Responsive UI polish

**Depends on:** completed core workflows.

The PDF offers extra credit for a modern responsive UI using HTML/CSS
frameworks. The user explicitly chose to include this work. Reuse the project's
existing frontend foundation where practical; include enrollment and scanner
status screens in the responsive review.

**Acceptance:** product management, inventory, checkout, account pages, and
receipts are usable on desktop and narrow screens, with clear labels, keyboard
access, and readable status messages.

## Progress and handoff notes

Update this section after each task. Mark a checklist item complete only when
its acceptance criteria are met.

For each task, record:

- Status: not started / in progress / blocked / complete.
- Decisions made and documentation links.
- Main files changed and any relevant commit identifiers.
- Checks run and their results.
- Physical hardware or live integration checks performed.
- Remaining dependencies and the next task to implement.

### Implementation session — 2026-11-10

Design and discovery: [docs/phase3-design.md](../docs/phase3-design.md).
Setup, migrations and diagnostics: [README](../README.md).
Evidence, physical dependencies and owners:
[docs/phase3-verification.md](../docs/phase3-verification.md).

**54 unittest checks pass** with isolated MariaDB tests enabled. Generic ESP32
firmware build and the desktop/mobile Chromium flow pass. All hardware/live
checks below remain distinct from these software results. No commits were made.

| Task | Status and outcome | Main files / remaining work |
| --- | --- | --- |
| 0 | Blocked on physical discovery; prerequisite report written. All three local references inspected; Linux x86_64 host identified; SDK absent. | Design/discovery report. Operator must supply SDK, Pi/reader evidence, actual product/card/scanner facts, broker/DB deployment and sender verification. |
| 1 | Complete. Money, stock, reusable tags, points, snapshots, archiving, migration, admin, ownership and MQTT contract settled. SDK transport explicitly deferred. | docs/phase3-design.md includes ER diagram and exact topics/messages. |
| 2 | In progress; software complete. New schema, repeatable additive upgrade, membership generation and guarded repeatable seed importer implemented. SQLite and isolated InnoDB migration checks pass. | models/shop.py, customer.py, services/migrations.py, scripts/setup_shop.py. Actual four-product seed remains blocked on verified EPCs and metadata; no guessed production records inserted. |
| 3 | Complete. Protected product list/create/edit/delete/archive; string UPC/EPC; exact cents; server validation/uniqueness; archived history preserved. | routes/shop.py, services/catalog.py, shop templates, tests/test_phase3.py. |
| 4 | Complete. Multiple immutable dated receptions with atomic stock increments, positive-quantity/date validation, stock display and reception history. | Reception model, catalog.receive, inventory route/template and regression tests. |
| 5 | Complete. Hashed signup/login, session rotation/logout, server ownership, admin provisioning, global CSRF and private account/receipt controls. Signup redirects to account. | security.py, routes/auth.py, setup CLI, tests/test_app.py. Threshold writes now admin-only. |
| 6 | In progress; keyboard-wedge/manual software path complete and tested. UPC terminators/leading zeros/length/unknown/repeated input handled. | static/product.js, lookup route. Actual scanner/input method and printed UPC checks remain blocked on device details. |
| 7 | Blocked on SDK/Pi access; adapter boundary, exclusive owned timed scans, registration capture, multi-tag deduplication, fake input, errors and guarded diagnostic implemented/tested. | hardware/product_reader.py, scripts/scan_products.py. No fabricated CF600 protocol; native transport and all-four physical scan still required. |
| 8 | In progress; live cart software complete and tested with four synthetic mapping fixtures. Ownership, quantity-one deduplication, totals, suppress/remove/restore and stop-at-review work. | checkout service, cart routes/templates/JS. Confirm and seed actual four EPC mappings before physical acceptance. |
| 8A | In progress; firmware and independent backend complete; generic esp32dev compilation and fake-MQTT protocol tests pass. | firmware/esp32/membershipReader, services/membership.py, runtime switches, diagnostic. Actual board confirmation, upload and live UID over MQTT remain required. |
| 8B | In progress; authenticated enrollment/replacement/cancel/confirmation and conflict/expiry/ownership tests and browser flow pass. | account/card routes, membership templates/JS. Actual-card enrollment/recognition remains required. |
| 9 | Complete in software. Explicit card selection confirmation or guest, review and payment success/failure/cancel; no real payment credentials. Scanning never grants login. | checkout routes and payment template; fake-reader and browser regression coverage. Physical dependencies remain in 7/8A/8B. |
| 10 | Complete. Atomic purchase/snapshots/stock/points; conditional stock updates; checkout compare-and-set plus unique purchase key. Failures roll back; duplicate/competing tests pass on SQLite and InnoDB. Later tag reuse tested without reset. | services/checkout.py, purchase models and concurrency tests. |
| 11 | Complete in software. Saved-data receipts for member/guest, customer email recipient, post-commit automatic delivery, failure state and explicit idempotent retry. | services/receipts.py, receipt routes/template. Mock success/failure/provider payload verified; live delivery remains a separate operator check. |
| 12 | Complete. Own name/email/membership/points, empty/history views and receipts with server ownership checks. | account template/routes; history/receipt ownership and browser tests. |
| 13 | In progress. Software E2E, documentation, ER diagram, setup/upgrade instructions, configuration, deployment caveats and regression suite completed. | README and verification handoff. Physical barcode/CF600/RC522, target Pi, live email and full hardware-mode evidence remain blocked as listed in handoff. |
| 14 | Complete. Persistent English/French selection for customer/admin workflows, server validation/status/notifications/errors and receipt text; identifiers and numeric values retained. | presentation/i18n.py, translated templates and UI/browser tests. |
| 15 | Complete. Existing responsive frontend extended to all new pages, scanner/enrollment states, stacked mobile carts/receipts, focus styles, labels and scrollable admin tables. | templates, dashboard.css and static JS. Desktop 1440px/mobile 390px browser flow and local screenshot review pass. |

Next independent implementation work is finished. Next required integration is
Task 0/7: obtain the CF600 SDK and Pi sample evidence, then verified full EPCs and
product data for Task 2. In parallel the operator can perform the actual-board
membership upload and live checks for Tasks 8A/8B. See the verification handoff
for the exact remaining dependencies and ownership; do not mark these checklist
items complete from synthetic scans or the generic firmware build.
