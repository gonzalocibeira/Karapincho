# SPDX-License-Identifier: GPL-3.0-or-later
import os
import shutil
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


def ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()
