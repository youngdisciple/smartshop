#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ ! -x .venv/bin/python ]]; then
    echo "Python setup is missing. Create .venv and install requirements.txt first."
    exit 1
fi

mkdir -p instance
export DATABASE_URL="sqlite:///$PWD/instance/local-preview.db"
export FRIDGE_SERVICES_ENABLED=false
export GMAIL_SERVICE_ENABLED=false
export MEMBERSHIP_SERVICE_ENABLED=false
export FAKE_READERS_ENABLED=true

echo "Open http://127.0.0.1:5000 in your browser."
echo "Press Ctrl+C here to stop SmartShop."
exec .venv/bin/python -c 'from app import main; main(debug=False)'
