#!/usr/bin/env bash
# One-command start for macOS (Intel or Apple Silicon) and Linux:   ./start.sh
# First run creates ./venv and installs the Python packages; later runs start straight away.
# Then open http://localhost:8000 (PORT=8080 ./start.sh to use another port).
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"

say() { printf "\n\033[1m%s\033[0m\n" "$*"; }
fail() { printf "\n\033[31m%s\033[0m\n" "$*" >&2; exit 1; }

# 1. A Python between 3.11 and 3.13 (macOS's built-in python3 is often 3.9, which is too old)
PY=""
for c in python3.12 python3.13 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ] && [ ! -x venv/bin/python ]; then
  if [ "$(uname)" = "Darwin" ]; then
    fail "Python 3.12 is needed. Install it with ONE of:
  * Homebrew:  brew install python@3.12
  * Installer: https://www.python.org/downloads/macos/  (choose Python 3.12, 'macOS 64-bit universal2')
Then run ./start.sh again."
  else
    fail "Python 3.11-3.13 is needed (e.g. sudo apt install python3.12 python3.12-venv). Then run ./start.sh again."
  fi
fi

# 2. Virtual environment + packages (re-installed only when requirements.txt changes)
if [ ! -x venv/bin/python ]; then
  say "Creating a virtual environment with $($PY --version)..."
  "$PY" -m venv venv
fi
STAMP=venv/.requirements.sha
WANT=$(shasum requirements.txt 2>/dev/null || sha1sum requirements.txt)
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$WANT" ]; then
  say "Installing Python packages (first run takes a few minutes)..."
  venv/bin/python -m pip install --upgrade pip >/dev/null
  venv/bin/python -m pip install -r requirements.txt
  echo "$WANT" > "$STAMP"
fi

# 3. macOS: XGBoost needs the OpenMP runtime (libomp), which macOS does not ship
if ! venv/bin/python -c "import xgboost" >/dev/null 2>&1; then
  if [ "$(uname)" = "Darwin" ]; then
    if command -v brew >/dev/null 2>&1; then
      say "Installing libomp (needed by XGBoost on macOS)..."
      brew install libomp
    else
      fail "XGBoost needs libomp on macOS. Install Homebrew from https://brew.sh, then run:
  brew install libomp
and run ./start.sh again."
    fi
  fi
  venv/bin/python -c "import xgboost" || fail "XGBoost could not be loaded; see the error above."
fi

# 4. Start the server and open the browser
say "Starting MoMo Fraud Detection on http://localhost:$PORT  (press Ctrl+C to stop)"
[ "${NO_BROWSER:-0}" = "1" ] || ( sleep 3; if command -v open >/dev/null 2>&1; then open "http://localhost:$PORT"; elif command -v xdg-open >/dev/null 2>&1; then xdg-open "http://localhost:$PORT"; fi ) >/dev/null 2>&1 &
exec venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port "$PORT"
