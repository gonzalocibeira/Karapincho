# SPDX-License-Identifier: GPL-3.0-or-later
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("KARAPINCHO_DATA", ROOT / "data")).resolve()
MAX_BYTES = 2 * 1024**3
MAX_SECONDS = 20 * 60
STAGES = ["acquire", "prepare", "lyrics", "separate", "transcribe", "align", "pitch", "chart", "package"]


def initialize():
    for name in ("jobs", "library", "models"):
        (DATA / name).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(DATA / "models" / "huggingface"))
    os.environ.setdefault("TORCH_HOME", str(DATA / "models" / "torch"))
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")


@lru_cache(maxsize=1)
def ffmpeg():
    found = shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("Install maintained FFmpeg 9.0.2 or newer (brew install ffmpeg), then restart Karapincho.")
    result = subprocess.run([found, "-version"], capture_output=True, text=True, check=True, timeout=10)
    match = re.match(r"ffmpeg version (\d+)\.(\d+)(?:\.(\d+))?\b", result.stdout)
    if not match or tuple(int(part or 0) for part in match.groups()) < (9, 0, 2):
        raise RuntimeError("Upgrade FFmpeg to 9.0.2 or newer (brew upgrade ffmpeg), then restart Karapincho.")
    return found
