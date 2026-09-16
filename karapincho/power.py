# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep macOS awake for active processing without changing its sleep settings."""

from contextlib import contextmanager
import logging
import os
from subprocess import DEVNULL, Popen, TimeoutExpired
import sys


logger = logging.getLogger(__name__)


@contextmanager
def keep_awake():
    """Prevent idle system sleep during work; the display can still turn off."""
    process = None
    if sys.platform == "darwin":
        try:
            # Watching our PID also releases the assertion if we crash or are killed.
            process = Popen(
                ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())],
                stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL,
            )
        except OSError:
            logger.warning("Could not prevent idle sleep during processing.", exc_info=True)
    try:
        yield
    finally:
        if process is not None:
            try:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except TimeoutExpired:
                    process.kill()
                    process.wait()
            except OSError:
                logger.warning("Could not release processing sleep prevention.", exc_info=True)
