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
    purpose = {"small": "low-memory CPU transcription recovery", "medium": "primary CPU transcription",
               "large-v3": "quality transcription recovery"}[size]
    path = _snapshot(_model(purpose), config.DATA / "models" / "whisper", download)
    if size == "large-v3":
        _require_files(path, ["config.json", "model.bin", "tokenizer.json", "vocabulary.json"])
    return path


def _require_files(path, names):
    if not names or any(Path(name).name != name or not (path / name).is_file()
                        or not (path / name).stat().st_size for name in names):
        raise FileNotFoundError("Incomplete quality model cache; run karapincho.setup_models --quality")


def qwen_model(quantized=False):
    return _model("quality MLX transcription 8bit" if quantized else "quality MLX transcription")


def qwen_path(quantized=False, download=False):
    path = _snapshot(qwen_model(quantized), config.DATA / "models" / "qwen", download)
    files = ["config.json", "vocab.json", "merges.txt", "tokenizer_config.json"]
    if quantized:
        files.append("weights.safetensors")
    else:
        _require_files(path, ["model.safetensors.index.json"])
        try:
            weight_map = json.loads((path / "model.safetensors.index.json").read_text())["weight_map"]
            if not isinstance(weight_map, dict):
                raise ValueError("Invalid weight index")
            shards = list(set(weight_map.values()))
            _require_files(path, shards)
        except (KeyError, TypeError, ValueError) as exc:
            raise FileNotFoundError("Invalid quality model cache; run karapincho.setup_models --quality") from exc
        files.extend(shards)
    _require_files(path, files)
    return path


def japanese_alignment_path(download=False):
    return _snapshot(_model("Japanese forced alignment"), config.DATA / "models" / "alignment", download)


def spanish_alignment_path(download=False):
    return _snapshot(_model("Spanish forced alignment"), config.DATA / "models" / "alignment", download)
