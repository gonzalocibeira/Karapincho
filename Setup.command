#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PIP_CACHE_DIR="$PWD/.cache/pip"

fail() { echo "Setup stopped: $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }

[ "$(uname -s)" = "Darwin" ] || fail "Karapincho v0.1 supports macOS only."
[ "$(uname -m)" = "arm64" ] || fail "Karapincho v0.1 requires an Apple Silicon Mac."
mac_major="$(sw_vers -productVersion | cut -d. -f1)"
[ "$mac_major" -ge 14 ] || fail "macOS 14 or newer is required."

free_kb="$(df -Pk . | awk 'NR==2 {print $4}')"
minimum_kb=$((10 * 1024 * 1024))
recommended_kb=$((20 * 1024 * 1024))
[ "$free_kb" -ge "$minimum_kb" ] || fail "At least 10 GB of free disk space is required."
if [ "$free_kb" -lt "$recommended_kb" ]; then
  echo "Warning: less than 20 GB is free. Setup can finish, but song processing needs working space."
fi

step "Checking Python 3.12 and Node.js 22+"
if ! command -v python3.12 >/dev/null; then
  if command -v brew >/dev/null; then brew install python@3.12; else
    echo "Install Python 3.12 from python.org, then run Setup.command again."; exit 1
  fi
fi
if ! command -v node >/dev/null || [ "$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || echo 0)" -lt 22 ]; then
  if command -v brew >/dev/null; then brew install node; else
    echo "Install Node.js 22 or newer from nodejs.org, then run Setup.command again."; exit 1
  fi
fi
node_major="$(node -p 'Number(process.versions.node.split(".")[0])')"
[ "$node_major" -ge 22 ] || fail "Node.js 22 or newer is required. Upgrade Node and run Setup.command again."

step "Creating the local Python environment"
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-macos.lock
.venv/bin/python -m pip install -e '.[ai]'

step "Installing optional Apple acceleration"
if ! .venv/bin/python -m pip install -r requirements-gpu.lock; then
  echo 'Optional GPU runtime unavailable; CPU processing remains available.'
fi
step "Building the interface"
npm ci --prefix frontend --cache .cache/npm
npm run build --prefix frontend
step "Downloading and verifying local AI models (about 7 GB)"
.venv/bin/python -m karapincho.setup_models
step "Setup complete"
echo "Ready. Open Start.command to launch Karapincho."
