# Phase 3 design and discovery

## Discovery (2026-11-10)

All three local references are present and inspected: Phase-3.pdf,
ESP32-RFID.pdf and RFID_TAGS.jpeg. They remain ignored local assets; supply
them separately in another checkout. The photograph identifies suffixes 4965,
4970, 4968 and 4951. Full EPC zero counts have **not** been reader-confirmed;
no production mapping is seeded from an uncertain transcription.

The development host is Linux x86_64, not verified as the target Pi. No CF600
SDK, Arduino CLI, reader transport information or physical scan captures were
found. Owner: project operator must download the Omnivox SDK, record Pi model,
OS/architecture, connection method and sample command/output. A native adapter
cannot be selected responsibly before this evidence exists. Product names,
UPCs, prices, producers, initial quantities and barcode scanner type also need
operator confirmation. Software supports keyboard-wedge UPC input provisionally.
The RC522 wiring is specified in the guide; actual board, cards, UID lengths,
Wi-Fi/MQTT and live receipt delivery remain unverified. No credentials or live
device changes are needed for automated tests.

## Policies

* Money is CAD integer cents, no tax calculation. Prices must be positive,
  at most 999999.99, with at most two decimal places.
* Register exactly one full uppercase hex EPC per product (2–24 even hex
  characters); UPC is 1–13 ASCII digits. Preserve leading zeros. SDK byte-order
  normalization remains deferred pending actual output. Membership UIDs are
  separate uppercase hex strings of 4, 7 or 10 bytes.
* Registering a tag creates no stock. Positive dated receptions increase the
  cached stock counter and append an immutable reception. Completed sales
  decrease it. Tags remain reusable; each checkout holds one unit per product.
  Suppress removed products until explicitly restored or a new cart starts.
* Snapshot names/prices at review. If price or availability changes, refuse
  payment and require another review. Atomic conditional updates prevent
  overselling; checkout state compare-and-set and a unique purchase checkout
  key prevent duplicate payment. Email is outside that transaction.
* Members earn floor(total cents / 100) points per purchase. Guests earn zero.
  Card identification alone grants no authentication or history access.
* Public signup never creates administrators. An explicit local CLI command
  promotes an existing customer. All mutations require CSRF; admin routes and
  fridge threshold mutations require authenticated administrators.
* Products with reception or sale history are archived, retaining ledger
  integrity. Unused products can be deleted. Account deletion is not exposed.
* Receipt snapshots include recipient and language. Guest receipts require
  the checkout browser capability; member history additionally requires login.
* One serving process owns each physical reader and fan. Reader leases last
  60 seconds. A random server-session ID owns operations and carts; logout
  invalidates leases and rotates the session. Development fake inputs require
  an explicit configuration switch. No hardware opens during app construction.

## Schema

```mermaid
erDiagram
    CUSTOMER ||--o{ PURCHASE : earns
    CUSTOMER ||--o| MEMBERSHIP_CARD : links
    PRODUCT ||--o{ RECEPTION : receives
    PRODUCT ||--o{ PURCHASE_ITEM : snapshots
    CHECKOUT ||--o| PURCHASE : finalizes
    PURCHASE ||--|{ PURCHASE_ITEM : contains
    CUSTOMER {
      string email PK
      string password
      string membership_number UK
      int points
      boolean is_admin
    }
    MEMBERSHIP_CARD {
      string uid PK
      string customer_email UK,FK
    }
    PRODUCT {
      int id PK
      string upc UK
      string epc UK
      int price_cents
      int stock
      boolean archived
    }
    RECEPTION {
      int id PK
      int product_id FK
      int quantity
      date received_on
    }
    CHECKOUT {
      string id PK
      string owner
      string status
      json items
      json suppressed
      string customer_email FK
    }
    PURCHASE {
      string id PK
      string checkout_id UK,FK
      string customer_email FK
      int total_cents
      int points_earned
      string receipt_status
    }
    PURCHASE_ITEM {
      int id PK
      string purchase_id FK
      int product_id FK
      string name
      int unit_cents
      int quantity
    }
```

Legacy customer email keys and password hashes are preserved. Versioned,
repeatable migration adds membership/points/admin fields and indexes, then
creates new tables. Back up first; MySQL DDL is not transactional. SQLite and
MySQL are supported dialects; actual MySQL execution remains an operator check.

## Membership MQTT contract v1

Dedicated topics (never Frig1/# or Frig2/#):

* `SmartShop/membership/command`: backend → one reader, QoS 1, non-retained.
  Arm: `{"v":1,"action":"arm","operation_id":"uuid","purpose":"enroll",
  "reader_epoch":"connection-uuid","expires_at":1790000060}`.
  Purpose is `enroll` or `checkout`. Cancel carries the same operation_id and
  reader_epoch with action `cancel`.
* `SmartShop/membership/event`: reader → backend, non-retained, QoS 0:
  `{"v":1,"operation_id":"uuid","event_id":"unique-uuid",
  "reader_epoch":"connection-uuid","uid":"00010203"}`.
* `SmartShop/membership/status`: reader heartbeat every 5 seconds,
  non-retained, QoS 0: `{"v":1,"online":true,"reader_epoch":"connection-uuid"}`.
  LWT has online=false. Backend requires a heartbeat within 15 seconds.

Both sides use clean MQTT sessions; every reader reconnect generates a new
epoch, invalidates the old arm, and requires a new operation. Backend accepts
only one matching event for its active owned operation, rejects retained,
malformed, stale and wrong-epoch messages, expires after 60 seconds, and
invalidates on broker/reader disconnect, cancel, logout or completion. Reader
requires NTP time and rejects expired commands. It requires card absence after
arming before accepting a fresh presentation. Enrollment/replacement requires
authenticated explicit confirmation. Checkout requires separate explicit
confirmation of the selected loyalty member, or guest choice.

Deploy on a trusted broker with per-client ACLs: backend publishes commands,
reader publishes events/status; ordinary clients cannot inject either. Never
retain commands/events. Use TLS outside a trusted isolated LAN. UID cards are
loyalty identifiers, not authentication credentials.

Firmware APIs checked against [MFRC522 upstream](https://github.com/miguelbalboa/rfid)
and [PubSubClient API](https://pubsubclient.knolleary.net/api). The historical
PDF patch is not applied. Actual board compilation and physical verification
remain separate checks.
