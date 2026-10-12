# SPDX-License-Identifier: GPL-3.0-or-later
"""Recognition policy. Safe to import in the web server: no inference imports."""

import importlib.util
import os

from .models import qwen_model, qwen_path, manifest, whisper_path

# Promotion requires the independent accuracy gate documented in LYRIC_ACCURACY.md.
# An explicit opt-in permits evaluation without changing existing installations.
QUALITY_V2_VALIDATED = False
REVISION = 7
LANGUAGES = {"en": "English", "es": "Spanish", "ja": "Japanese"}


def engine():
    requested = os.environ.get("KARAPINCHO_TRANSCRIPTION", "auto")
    if requested not in ("auto", "legacy", "quality-v2"):
        raise ValueError("KARAPINCHO_TRANSCRIPTION must be auto, legacy, or quality-v2")
    return "quality-v2" if requested == "quality-v2" or (requested == "auto" and QUALITY_V2_VALIDATED) else "legacy"


def quantized(total, reduced=False):
    return reduced or total < 16 * 1024**3


def provenance():
    return {"engine": engine(), "revision": REVISION, "validated": QUALITY_V2_VALIDATED,
            "models": [{key: model[key] for key in ("repository", "revision")}
                       for model in manifest() if model["purpose"].startswith("quality")
                       or model["purpose"] == "primary CPU transcription"],
            "window_seconds": 28, "context_seconds": 1,
            "language_policy": "independent-encoder-majority-with-two-window-switch",
            "selection": "independent-then-dual-view-agreement-common-alignment-original-tie"}


def readiness():
    """Report optional capabilities separately from basic application readiness."""
    import psutil
    compact = quantized(psutil.virtual_memory().total)
    missing = []
    if importlib.util.find_spec("mlx_qwen3_asr") is None:
        missing.append("mlx-qwen3-asr")
    for label, resolve in (("Qwen3-ASR-1.7B", lambda: qwen_path(compact)),
                           ("Whisper large-v3", lambda: whisper_path("large-v3"))):
        try:
            resolve()
        except (OSError, ValueError):
            missing.append(label)
    return {"engine": engine(), "validated": QUALITY_V2_VALIDATED, "ready": not missing,
            "missing": missing, "model": qwen_model(compact)["repository"]}
