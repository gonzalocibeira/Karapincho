#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if [ ! -x .venv/bin/python ] || [ ! -f frontend/dist/index.html ]; then
  ./Setup.command
fi
exec .venv/bin/python -m karapincho.launch
