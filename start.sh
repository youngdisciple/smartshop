#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ -z ${DATABASE_URL:-} && ! -f membership-test.db ]]; then
    echo "SmartShop database is missing: membership-test.db"
    exit 1
fi

if [[ -x .venv/bin/python ]]; then
    python=.venv/bin/python
elif [[ -x venv/bin/python ]]; then
    python=venv/bin/python
else
    python3 -m venv .venv
    python=.venv/bin/python
fi
if ! "$python" -c 'import dotenv, flask_sqlalchemy, paho.mqtt.client, pymysql, requests' 2>/dev/null; then
    "$python" -m pip install -r requirements.txt
fi

export DATABASE_URL="${DATABASE_URL:-sqlite:///$PWD/membership-test.db}"
export FRIDGE_SERVICES_ENABLED="${FRIDGE_SERVICES_ENABLED:-false}"
export GMAIL_SERVICE_ENABLED="${GMAIL_SERVICE_ENABLED:-false}"
export MEMBERSHIP_SERVICE_ENABLED="${MEMBERSHIP_SERVICE_ENABLED:-false}"
if [[ -z ${PRODUCT_READER_BACKEND:-} && -z ${FAKE_READERS_ENABLED:-} ]] &&
   [[ -c "${CF600_SERIAL_DEVICE:-/dev/serial/by-id/usb-CFUSB_HID_By_YLW28-if03-port0}" ]]; then
    export PRODUCT_READER_BACKEND=cf600_serial
fi
if [[ ${PRODUCT_READER_BACKEND:-disabled} == disabled ]]; then
    export FAKE_READERS_ENABLED="${FAKE_READERS_ENABLED:-true}"
else
    export FAKE_READERS_ENABLED="${FAKE_READERS_ENABLED:-false}"
fi

exec "$python" -c 'import os; from app import main; main(debug=False, open_browser=os.getenv("SMARTSHOP_OPEN_BROWSER", "1") != "0")'

#sudo modprobe usbserial vendor=0x0483 product=0x5750 ls -l /dev/serial/by-id/