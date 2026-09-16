# SPDX-License-Identifier: GPL-3.0-or-later
"""Model stages. Each entry point is run in a fresh process, never in the web server."""

import gc
import math
import os

from . import acceleration, config
from .metrics import model_loading
from .models import japanese_alignment_path, spanish_alignment_path, whisper_path
from .media import read_json, write_json


def audio_window(path, start=0, end=None, rate=16000):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    with sf.SoundFile(path) as source:
        source.seek(min(len(source), round(start * source.samplerate)))
        count = -1 if end is None else max(0, round((end - start) * source.samplerate))
        audio = source.read(count, dtype="float32", always_2d=True).mean(axis=1)
        original_rate = source.samplerate
    if original_rate != rate:
        divisor = math.gcd(original_rate, rate)
        audio = resample_poly(audio, rate // divisor, original_rate // divisor)
    return np.asarray(audio, dtype=np.float32)


def separate(folder, low_memory=False):
    import numpy as np
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    torch.set_num_threads(4)
    device = acceleration.CURRENT.backend
    with model_loading("demucs"):
        model = get_model("htdemucs").to(device).eval()
    bounded = low_memory or acceleration.CURRENT.reduced
    length = 10 if bounded else 20
    with sf.SoundFile(folder / "original.wav") as source:
        sr = source.samplerate
        if sr != model.samplerate:
            raise ValueError("Unexpected sample rate for vocal separation")
        total = len(source)
        with sf.SoundFile(folder / "vocals.wav", "w", samplerate=sr, channels=1, subtype="FLOAT") as out:
            for first in range(0, total, length * sr):
                left, right = max(0, first - sr), min(total, first + (length + 1) * sr)
                source.seek(left)
                audio = source.read(right - left, dtype="float32", always_2d=True).T
                waveform = torch.from_numpy(audio)
                ref = waveform.mean(0)
                scale = ref.std().clamp(min=1e-6)
                normalized = (waveform - ref.mean()) / scale
                with torch.inference_mode():
                    result = apply_model(
                        model,
                        normalized[None],
                        device=device,
                        shifts=0,
                        split=True,
                        overlap=0.25,
                        segment=4 if bounded else 7,
                        progress=False,
                    )[0]
                vocals = (result[model.sources.index("vocals")].cpu() * scale + ref.mean()).mean(0).numpy()
                offset = first - left
                out.write(
                    np.asarray(vocals[offset : offset + min(length * sr, total - first)], dtype="float32")
                )
                print(f"Separated {min(first + length * sr, total) / total:.0%}", flush=True)
    return {"model": "htdemucs", "warnings": []}


def transcribe_audio(folder, low_memory=False):
    job = read_json(folder / "job.json") if (folder / "job.json").exists() else {}
    fast = job.get("processing_mode") == "fast"
    if acceleration.CURRENT.backend == "mlx" and not fast:
        from .transcription import transcribe_mlx
        return transcribe_mlx(folder)
    import soundfile as sf
    from faster_whisper import WhisperModel

    model_name = "small" if low_memory or fast else os.environ.get("KARAPINCHO_WHISPER_MODEL", "medium")
    model_source = str(whisper_path(model_name)) if model_name in ("medium", "small") else model_name
    with model_loading("whisper"):
        model = WhisperModel(
            model_source,
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
            num_workers=1,
            download_root=str(config.DATA / "models" / "whisper"),
        )
    settings = read_json(folder / "job.json").get("lyric_settings", {}) if (folder / "job.json").exists() else {}
    duration = sf.info(folder / "vocals.wav").duration
    segments, warnings = [], []

    def decode(audio, offset, alternate=False):
        result, info = model.transcribe(
            audio,
            language=settings.get("language") or None,
            task="transcribe",
            beam_size=1 if fast else 5,
            word_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=False,
            temperature=0.2 if alternate else 0.0,
        )
        decoded = []
        for seg in result:
            if not seg.text.strip() or seg.no_speech_prob > 0.7 or seg.avg_logprob < -1.5:
                continue
            language = info.language
            if not settings.get("language") and seg.end - seg.start >= 1:
                sample = audio[round(seg.start * 16000) : round(seg.end * 16000)]
                if len(sample):
                    detected, probability, _ = model.detect_language(sample)
                    if probability >= 0.6:
                        language = detected
            decoded.append(
                {
                    "start": offset + seg.start,
                    "end": offset + seg.end,
                    "text": seg.text.strip(),
                    "language": language,
                    "score": seg.avg_logprob,
                    "compression": seg.compression_ratio,
                    "words": [
                        {
                            "word": w.word,
                            "start": offset + w.start,
                            "end": offset + w.end,
                            "score": w.probability,
                        }
                        for w in (seg.words or [])
                    ],
                }
            )
            print(f"Transcribed through {offset + seg.end:.1f}s", flush=True)
        return decoded

    # Whisper owns its seek windows: cutting our own fixed windows loses words at chorus boundaries.
    # Twenty minutes at 16 kHz occupies only 77 MB; model inference still uses bounded windows.
    audio = audio_window(folder / "vocals.wav")
    import numpy as np

    first = decode(audio, 0) if len(audio) and np.sqrt(np.mean(audio**2)) >= 0.001 else []
    if not first and len(audio) and np.sqrt(np.mean(audio**2)) >= 0.001:
        first = decode(audio_window(folder / "original.wav"), 0, True)
        warnings.append("Retried transcription on original audio; vocals were difficult to recognize.")
    del audio

    def quality(items):
        return sum(s["score"] - max(0, s["compression"] - 2.4) for s in items) / len(items) if items else -99

    for seg in first:
        candidates = [seg]
        uncertain = seg["score"] < -0.8 or seg["compression"] > 2.4
        if uncertain:
            left, right = max(0, seg["start"] - 0.25), min(duration, seg["end"] + 0.25)
            alternate = decode(audio_window(folder / "original.wav", left, right), left, True)
            if quality(alternate) > quality(candidates):
                candidates = alternate
            warnings.append(f"Retried uncertain lyrics at {seg['start']:.1f}s; wording may need checking.")
        for candidate in candidates:
            words = [
                w for w in candidate["words"] if seg["start"] <= (w["start"] + w["end"]) / 2 <= seg["end"]
            ]
            if words:
                candidate.update(
                    words=words,
                    start=words[0]["start"],
                    end=words[-1]["end"],
                    text="".join(w["word"] for w in words).strip(),
                )
                segments.append(candidate)
    if not segments:
        raise ValueError(
            "No intelligible vocals were detected. An instrumental-only video cannot produce a lyric chart."
        )
    if fast:
        warnings.append("Fast mode uses a smaller transcription model; lyrics may be less accurate.")
    elif low_memory:
        warnings.append(
            "Used the smaller Whisper model after a memory failure; transcription may be less accurate."
        )
    result = {"segments": segments, "warnings": warnings, "model": f"faster-whisper/{model_name}/cpu-int8"}
    write_json(folder / "transcript.json", result)
    return {"model": result["model"], "warnings": warnings}


def transcribe(folder, low_memory=False):
    from .lyrics import compose
    import soundfile as sf

    source = read_json(folder / "lyrics-source.json") if (folder / "lyrics-source.json").exists() else {}
    reference = {"segments": [], "warnings": []}
    try:
        result = transcribe_audio(folder, low_memory)
        reference = read_json(folder / "transcript.json")
        write_json(folder / "asr-reference.json", reference)
    except ValueError:
        if not source.get("lines"):
            raise
        result = {"warnings": ["Speech recognition found no usable text; aligning supplied lyrics."], "model": "none"}
    if not source.get("lines"):
        result["source"] = "transcription"
        return result
    try:
        transcript = compose(source, reference, sf.info(folder / "vocals.wav").duration)
    except ValueError as exc:
        if source["source"] == "user" or not reference["segments"]:
            raise
        result.setdefault("warnings", []).append(f"Online lyrics could not be located: {exc}; using transcription.")
        result["source"] = "transcription"
        return result
    transcript["warnings"] = result.get("warnings", []) + transcript["warnings"]
    write_json(folder / "transcript.json", transcript)
    return {**result, **{k: v for k, v in transcript.items() if k != "segments"}}


def align(folder, low_memory=False):
    import torch
    from whisperx.alignment import align as forced_align, load_align_model

    torch.set_num_threads(2 if low_memory else 4)
    transcript = read_json(folder / "transcript.json")
    aligned, warnings = [], []
    alignment_counts = {"precise": 0, "estimated": 0, "transcription_fallback": 0}
    languages = sorted({s["language"] for s in transcript["segments"]})
    for language in languages:
        model = None
        try:
            with model_loading(f"alignment/{language}"):
                model, metadata = load_align_model(
                    language,
                    acceleration.CURRENT.backend,
                    model_name=(
                        str(japanese_alignment_path()) if language == "ja"
                        else str(spanish_alignment_path()) if language == "es"
                        else None
                    ),
                    model_dir=str(config.DATA / "models" / "alignment"),
                )
        except Exception as exc:
            if (acceleration.failure_kind(f"{type(exc).__name__}: {exc}", acceleration.CURRENT.backend) != "application"
                    or (acceleration.CURRENT.backend != "cpu" and isinstance(exc, RuntimeError))):
                raise
            warnings.append(
                f"Precise {language} alignment unavailable; using estimated word timings ({type(exc).__name__})."
            )
        for seg in (s for s in transcript["segments"] if s["language"] == language):
            words = None
            if model is not None:
                padding = 2.0 if seg.get("external") else 0.3
                start = seg.get("window_start", max(0, seg["start"] - padding))
                end = seg.get("window_end", seg["end"] + padding)
                for attempt, source in enumerate(("vocals.wav", "original.wav")):
                    try:
                        sample = audio_window(folder / source, start, end)
                        result = forced_align(
                            [{"start": 0 if seg.get("external") else seg["start"] - start,
                              "end": end - start if seg.get("external") else seg["end"] - start,
                              "text": seg["text"]}],
                            model,
                            metadata,
                            sample,
                            acceleration.CURRENT.backend,
                            return_char_alignments=True,
                            print_progress=False,
                        )
                        candidate = result["segments"][0]
                        timed = candidate.get("words", [])
                        valid = [w for w in timed if "start" in w and "end" in w]
                        if (
                            not timed
                            or len(valid) != len(timed)
                            or any(not math.isfinite(w[k]) for w in valid for k in ("start", "end"))
                            or any(w["start"] < 0 or w["end"] <= w["start"] or w["end"] > end - start
                                   for w in valid)
                            or sum(w.get("score", 0) for w in valid) / len(valid) < 0.3
                        ):
                            raise ValueError("Insufficient aligned words")
                        if seg.get("external"):
                            from .lyrics import normalized
                            if normalized("".join(w["word"] for w in valid)) != normalized(seg["text"]):
                                raise ValueError("Alignment did not preserve the supplied text")
                        words = [
                            {
                                **w,
                                "start": w["start"] + start,
                                "end": w["end"] + start,
                                "language": language,
                                "estimated": False,
                            }
                            for w in valid
                        ]
                        # Preserve character timing for acoustic syllable boundaries where available.
                        for word in words:
                            word["chars"] = [
                                {**c, "start": c["start"] + start, "end": c["end"] + start}
                                for c in candidate.get("chars", [])
                                if "start" in c
                                and "end" in c
                                and word["start"] - 0.02 <= c["start"] + start < word["end"]
                            ]
                        if attempt:
                            warnings.append(f"Retried alignment on original audio at {seg['start']:.1f}s.")
                        break
                    except Exception as exc:
                        if (acceleration.failure_kind(f"{type(exc).__name__}: {exc}", acceleration.CURRENT.backend) != "application"
                                or (acceleration.CURRENT.backend != "cpu" and isinstance(exc, RuntimeError))):
                            raise
                        print(f"Alignment attempt {attempt + 1} at {seg['start']:.1f}s: {exc}", flush=True)
            if words is None:
                if acceleration.CURRENT.backend != "cpu" and model is not None:
                    raise RuntimeError("quality retry: GPU alignment did not meet the timing quality threshold")
                fallback = seg["words"]
                if seg.get("external") == "lrclib" and (model is not None or not seg.get("timed_lyrics")):
                    fallback = seg.get("fallback_words", [])
                    if not fallback:
                        warnings.append(f"Online lyrics could not be verified at {seg['start']:.1f}s; omitted this passage.")
                        alignment_counts["transcription_fallback"] += 1
                        continue
                    alignment_counts["transcription_fallback"] += 1
                    warnings.append(f"Online lyrics did not align at {seg['start']:.1f}s; used transcription for this passage.")
                alignment_counts["estimated"] += 1
                words = [{**w, "language": language, "estimated": True} for w in fallback]
                warnings.append(f"Estimated lyric timing at {seg['start']:.1f}s.")
            else:
                alignment_counts["precise"] += 1
            for word in words:
                word["phrase"] = seg["start"]
            aligned.extend(words)
        del model
        gc.collect()
    if not aligned:
        reference_path = folder / "asr-reference.json"
        if transcript.get("source", "").startswith("lrclib") and reference_path.exists():
            for seg in read_json(reference_path)["segments"]:
                aligned.extend({**w, "language": seg["language"], "phrase": seg["start"], "estimated": True}
                               for w in seg["words"])
            warnings.append("Online lyrics could not be aligned; retained the original transcription.")
            transcript["source"] = "transcription"
        if not aligned:
            raise ValueError("No lyric words could be aligned to this recording.")
    source_label = transcript.get("source", "transcription")
    if alignment_counts["transcription_fallback"] and source_label.startswith("lrclib"):
        source_label = "lrclib+transcription"
    result = {
        "words": sorted(aligned, key=lambda w: w["start"]),
        "warnings": warnings,
        "languages": languages,
        "alignment_quality": alignment_counts,
        "source": source_label,
    }
    write_json(folder / "aligned.json", result)
    return {"model": "whisperx/wav2vec2", "warnings": warnings, "alignment_quality": alignment_counts,
            "source": result["source"]}


def pitch_energy(audio, count):
    """Same 320-sample RMS windows, evaluated in a vectorized view."""
    import numpy as np
    energies = np.zeros(count, dtype=np.float32)
    if not len(audio) or not count:
        return energies
    energies[0] = np.sqrt(np.mean(audio[:160] ** 2))
    full = min(count - 1, max(0, (len(audio) - 320) // 160 + 1))
    if full:
        windows = np.lib.stride_tricks.sliding_window_view(audio, 320)[::160][:full]
        energies[1:full + 1] = np.sqrt(np.mean(windows ** 2, axis=1))
    for index in range(full + 1, count):
        sample = audio[max(0, index * 160 - 160):min(len(audio), index * 160 + 160)]
        energies[index] = np.sqrt(np.mean(sample ** 2)) if len(sample) else 0
    return energies


def pitch(folder, low_memory=False):
    import numpy as np
    import soundfile as sf
    import torch
    import torchcrepe

    torch.set_num_threads(4)
    duration = sf.info(folder / "vocals.wav").duration
    with model_loading("torchcrepe"):
        torchcrepe.load.model(acceleration.CURRENT.backend, "full")
    tracks = {"time": [], "hz": [], "confidence": [], "energy": []}
    for start in range(0, math.ceil(duration), 15):
        left = max(0, start - 0.1)
        audio = audio_window(folder / "vocals.wav", left, min(duration, start + 15.1))
        if not len(audio):
            continue
        tensor = torch.from_numpy(audio)[None]
        with torch.inference_mode():
            from .transcription import predict_pitch
            f0, confidence = predict_pitch(
                tensor,
                16000,
                160,
                50,
                1100,
                "full",
                batch_size=4 if low_memory else acceleration.CURRENT.batch_size,
                device=acceleration.CURRENT.backend,
                return_periodicity=True,
            )
            confidence = torchcrepe.filter.median(confidence, 3)
            f0 = torchcrepe.filter.median(f0, 5)
        values, conf = f0[0].numpy(), confidence[0].numpy()
        timestamps = left + np.arange(len(values)) / 100
        keep = (timestamps >= start) & (timestamps < min(start + 15, duration))
        energy = pitch_energy(audio, len(values))
        tracks["time"].extend(timestamps[keep].tolist())
        tracks["hz"].extend(np.where(np.isfinite(values), values, 0)[keep].tolist())
        # Retain the same waveform RMS and voicing policy, including sustained vowels.
        tracks["confidence"].extend(np.where((energy > 0.001) & np.isfinite(conf), conf, 0)[keep].tolist())
        tracks["energy"].extend(energy[keep].tolist())
        print(f"Detected pitch {min(start + 15, duration) / duration:.0%}", flush=True)
    np.savez_compressed(folder / "pitch.npz", **{k: np.asarray(v) for k, v in tracks.items()})
    return {"model": "torchcrepe/full", "warnings": []}
