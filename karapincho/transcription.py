# SPDX-License-Identifier: GPL-3.0-or-later
"""Accelerated inference adapters; output contracts match the CPU pipeline."""

import math

from . import acceleration, config
from .metrics import model_loading
from .media import read_json, write_json


class QualityRetry(RuntimeError):
    """Rerun recognition in a fresh CPU process; never hold both models in RAM."""


def model_path(download=False):
    from huggingface_hub import snapshot_download
    if not acceleration.MLX_REVISION:
        raise RuntimeError("MLX model revision has not been pinned")
    return snapshot_download(acceleration.MLX_MODEL, revision=acceleration.MLX_REVISION,
                             cache_dir=str(config.DATA / "models" / "mlx"), local_files_only=not download)


def normalize_segment(seg, language, offset=0):
    return {"start": offset + seg["start"], "end": offset + seg["end"], "text": seg["text"].strip(),
            "language": language, "score": seg["avg_logprob"], "compression": seg["compression_ratio"],
            "words": [{"word": w["word"], "start": offset + w["start"], "end": offset + w["end"],
                       "score": w.get("probability", 0)} for w in seg.get("words", [])]}


def needs_cpu_retry(raw):
    values = [raw["no_speech_prob"], raw["avg_logprob"], raw["compression_ratio"],
              *[w.get("probability", 0) for w in raw.get("words", [])]]
    if not all(math.isfinite(value) for value in values):
        return True
    return (raw["no_speech_prob"] > 0.7 or raw["avg_logprob"] < -0.8 or raw["compression_ratio"] > 2.4
            or not raw.get("words") or any(w.get("probability", 0) < 0.5 for w in raw["words"]))


def transcribe_mlx(folder):
    import importlib
    import mlx.core as mx
    import mlx_whisper
    import numpy as np
    from mlx_whisper.audio import log_mel_spectrogram, pad_or_trim
    from .ai import audio_window

    settings = read_json(folder / "job.json").get("lyric_settings", {}) if (folder / "job.json").exists() else {}
    audio = audio_window(folder / "vocals.wav")
    if not len(audio) or np.sqrt(np.mean(audio**2)) < 0.001:
        raise QualityRetry("quality retry: no recognizable vocals on GPU")
    mx.random.seed(0)
    path = model_path()
    # Load explicitly so model startup is measured independently of decoding.
    module = importlib.import_module("mlx_whisper.transcribe")
    with model_loading("whisper-mlx"):
        module.ModelHolder.get_model(path, mx.float16)
    output = mlx_whisper.transcribe(audio, path_or_hf_repo=path, language=settings.get("language") or None,
                                   task="transcribe", word_timestamps=True, temperature=0.0,
                                   condition_on_previous_text=False, verbose=False)
    model = importlib.import_module("mlx_whisper.transcribe").ModelHolder.model
    segments = []
    for raw in output["segments"]:
        if not raw["text"].strip():
            continue
        # A CPU retry of the stage also executes the established original-mix passage retries.
        # This costs more than a passage-only retry but avoids two models and preserves CPU quality policy.
        if needs_cpu_retry(raw):
            raise QualityRetry("quality retry: uncertain GPU transcription; using CPU beam search")
        language = settings.get("language") or output["language"]
        if not settings.get("language") and raw["end"] - raw["start"] >= 1:
            sample = audio[round(raw["start"] * 16000):round(raw["end"] * 16000)]
            if len(sample):
                mel = pad_or_trim(log_mel_spectrogram(sample, n_mels=model.dims.n_mels), 3000, axis=-2)
                _, probs = model.detect_language(mel.astype(mx.float16))
                detected = max(probs, key=probs.get)
                if probs[detected] >= 0.6:
                    language = detected
        segment = normalize_segment(raw, language)
        if not segment["words"] or any(not math.isfinite(w[k]) for w in segment["words"] for k in ("start", "end")):
            raise QualityRetry("quality retry: invalid GPU word timestamps")
        if any(w["start"] < 0 or w["end"] <= w["start"] or w["end"] > len(audio) / 16000 + .02
               for w in segment["words"]):
            raise QualityRetry("quality retry: out-of-range GPU word timestamps")
        segment.update(start=segment["words"][0]["start"], end=segment["words"][-1]["end"],
                       text="".join(w["word"] for w in segment["words"]).strip())
        segments.append(segment)
    if not segments:
        raise QualityRetry("quality retry: no usable GPU transcription")
    result = {"segments": segments, "warnings": [], "model": "mlx-whisper/medium/fp16",
              "model_revision": acceleration.MLX_REVISION}
    write_json(folder / "transcript.json", result)
    return {k: v for k, v in result.items() if k != "segments"}


def predict_pitch(audio, sample_rate, hop_length, fmin, fmax, model, batch_size, device, return_periodicity):
    import torch
    import torchcrepe
    if device == "cpu":
        return torchcrepe.predict(audio, sample_rate, hop_length, fmin, fmax, model,
                                  batch_size=batch_size, device=device, return_periodicity=return_periodicity)
    # Only the convolutional network runs on MPS. Viterbi decoding and periodicity stay on CPU.
    pitches, confidences = [], []
    # Viterbi boundaries must stay at the established 16 frames even when GPU batch sizes change.
    # Otherwise memory tuning alone changes the decoded melody.
    for frames in torchcrepe.preprocess(audio, sample_rate, hop_length, max(16, batch_size), "cpu", True):
        probabilities = torch.cat([torchcrepe.infer(part.to(device), model, device).cpu()
                                   for part in frames.split(batch_size)], 0)
        for group in probabilities.split(16):
            group = group.reshape(audio.size(0), -1, 360).transpose(1, 2)
            pitch, confidence = torchcrepe.postprocess(group, fmin, fmax, return_periodicity=True)
            pitches.append(pitch)
            confidences.append(confidence)
    return torch.cat(pitches, 1), torch.cat(confidences, 1)
