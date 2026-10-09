#!/bin/bash
set -e

# Signet: start server with automatic setup.
# Works from any directory; project path may contain spaces.

cd "$(dirname "$0")"

# Find Python 3.11 or 3.12
PYTHON=""
for py in python3.12 python3.11 python3 python; do
  if command -v "$py" &> /dev/null; then
    version=$($py --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
    if [[ "$version" == "3.11" ]] || [[ "$version" == "3.12" ]]; then
      PYTHON="$py"
      break
    fi
  fi
done

if [[ -z "$PYTHON" ]]; then
  echo "Error: Python 3.11 or 3.12 required."
  exit 1
fi

echo "Using $PYTHON ($("$PYTHON" --version 2>&1))"

# Create venv if missing
if [[ ! -d ".venv" ]]; then
  echo "Creating .venv..."
  $PYTHON -m venv .venv
fi

# Install requirements only when needed
if [[ ! -f ".venv/.installed" ]] || [[ "requirements.txt" -nt ".venv/.installed" ]]; then
  echo "Installing requirements..."
  .venv/bin/python -m pip install -q -r requirements.txt
  touch .venv/.installed
fi

# Run setup script
echo "Running setup..."
.venv/bin/python scripts/setup.py

# Train classifier if model missing
if [[ ! -f "models/change_clf.joblib" ]]; then
  echo "Training classifier..."
  .venv/bin/python scripts/train_classifier.py
fi

# Create demo set if missing
if [[ ! -f "demo/expected.json" ]]; then
  echo "Creating demo set..."
  .venv/bin/python scripts/make_demo_set.py
fi

# Get port
PORT="${PORT:-8000}"

# Get LAN IP (no internet required)
LAN_IP=$(.venv/bin/python -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('10.255.255.255', 1))
    print(s.getsockname()[0])
except Exception:
    print('127.0.0.1')
")

echo ""
echo "Signet server starting on:"
echo "  http://localhost:$PORT"
echo "  http://$LAN_IP:$PORT"
echo ""

# Start server
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
