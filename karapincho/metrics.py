# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-stage measurements; each stage runs in its own process."""
import time
from contextlib import contextmanager

MODEL_LOADS = {}


@contextmanager
def model_loading(name):
    started = time.monotonic()
    try:
        yield
    finally:
        MODEL_LOADS[name] = MODEL_LOADS.get(name, 0) + round(time.monotonic() - started, 4)
