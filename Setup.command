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

step "Checking Python 3.12 and security-patched Node.js"
if ! command -v python3.12 >/dev/null; then
  if command -v brew >/dev/null; then brew install python@3.12; else
    echo "Install Python 3.12 from python.org, then run Setup.command again."; exit 1
  fi
fi
if ! command -v node >/dev/null || ! node frontend/scripts/check-node.mjs; then
  if command -v brew >/dev/null; then
    if brew list --versions node >/dev/null 2>&1; then brew upgrade node; else brew install node; fi
  else
    echo "Install patched Node.js 22.23.4+, 24.22.1+, or 26.12.1+ from nodejs.org, then run Setup.command again."
    exit 1
  fi
fi
node frontend/scripts/check-node.mjs || fail "Upgrade Node.js and run Setup.command again."

step "Creating the local Python environment"
python3.12 -m venv .venv
# Hash-pinned bootstrap also replaces pip's vulnerable vendored CA bundle.
.venv/bin/python -m pip install --upgrade 'pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70'
.venv/bin/python -m pip install -r requirements-macos.lock
.venv/bin/python -m pip install -e '.[ai]'

step "Checking maintained FFmpeg"
if ! .venv/bin/python -c 'from karapincho.config import ffmpeg; print(ffmpeg())'; then
  if command -v brew >/dev/null; then
    if brew list --versions ffmpeg >/dev/null 2>&1; then brew upgrade ffmpeg; else brew install ffmpeg; fi
  else
    fail "Install FFmpeg 9.0.2 or newer on PATH, then run Setup.command again."
  fi
fi
.venv/bin/python -c 'from karapincho.config import ffmpeg; print(ffmpeg())'

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
