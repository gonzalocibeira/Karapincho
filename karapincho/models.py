# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve release-pinned Hugging Face model snapshots."""

import json
from functools import lru_cache
from pathlib import Path

from . import config


@lru_cache
def manifest():
    path = Path(__file__).with_name("model_manifest.json")
    return json.loads(path.read_text())["models"]


def _model(purpose):
    return next(model for model in manifest() if model["purpose"] == purpose)


def _snapshot(model, cache, download=False):
    from huggingface_hub import snapshot_download

    options = {}
    if model.get("allow_patterns"):
        options["allow_patterns"] = model["allow_patterns"]
    return Path(snapshot_download(
        repo_id=model["repository"],
        revision=model["revision"],
        cache_dir=str(cache),
        local_files_only=not download,
        **options,
    ))


def whisper_path(size="medium", download=False):
    purpose = "low-memory CPU transcription recovery" if size == "small" else "primary CPU transcription"
    return _snapshot(_model(purpose), config.DATA / "models" / "whisper", download)


def japanese_alignment_path(download=False):
    return _snapshot(_model("Japanese forced alignment"), config.DATA / "models" / "alignment", download)


def spanish_alignment_path(download=False):
    return _snapshot(_model("Spanish forced alignment"), config.DATA / "models" / "alignment", download)
