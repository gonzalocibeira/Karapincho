# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded, dual-view lyric recognition with independent recovery and shared alignment.

No reference lyrics or online services are used here. Model families run sequentially;
Qwen's explicit Session avoids its process-global model cache retaining GPU weights.
"""

import gc
import hashlib
import json
import math
from collections import Counter

from . import acceleration, recognition
from .lyrics import estimated_words, normalized
from .media import read_json, write_json
from .metrics import model_loading
from .models import japanese_alignment_path, manifest, qwen_model, qwen_path, spanish_alignment_path, whisper_path

RATE = 16000
ALIGNMENT_REVISION = 3


def windows(audio):
    """Contiguous ownership cores with one second of context on each side (<=28s)."""
    import numpy as np
    duration = len(audio) / RATE
    begin = 0.0
    result = []
    while begin < duration:
        end = min(duration, begin + 26)
        if end < duration:
            # Choose a trough near the end, without allowing tiny/oversized windows.
            positions = np.arange(begin + 22, end + .001, .1)
            energy = [float(np.mean(audio[round(p * RATE):round((p + .05) * RATE)] ** 2))
                      for p in positions]
            end = float(positions[int(np.argmin(energy))])
        result.append({"core_start": begin, "core_end": end,
                       "start": max(0, begin - 1), "end": min(duration, end + 1)})
        begin = end
    return result


def vocal_activity(audio):
    """An investigation trigger, never evidence that a hypothesis is correct."""
    import numpy as np
    frames = len(audio) // 320
    if not frames:
        return False
    energy = np.sqrt(np.mean(audio[:frames * 320].reshape(-1, 320) ** 2, axis=1))
    # Relative threshold retains quiet singing; numerical silence cannot trigger ASR.
    return int(np.count_nonzero(energy > max(1e-6, float(energy.max()) * .08))) >= 5


def recording_languages(passages, forced=None):
    if forced:
        return [forced] * len(passages)
    votes = Counter()
    names = {name.casefold(): code for code, name in recognition.LANGUAGES.items()}
    observations = []
    for passage in passages:
        codes = [names.get(c.get("detected_language", "").casefold(), c.get("detected_language", ""))
                 for c in passage["candidates"] if normalized(c["text"])]
        code = Counter(codes).most_common(1)[0][0] if codes else None
        observations.append(code)
        if code:
            votes[code] += passage["core_end"] - passage["core_start"]
    language = votes.most_common(1)[0][0] if votes else "en"
    result = [language] * len(passages)
    # A switch needs two consecutive substantive windows, not one short phrase.
    for i in range(1, len(passages)):
        previous, current = observations[i - 1:i + 1]
        if previous and previous == current and previous != language:
            if all(passages[j]["core_end"] - passages[j]["core_start"] >= 4 for j in (i - 1, i)):
                language = previous
                result[i - 1] = language
        result[i] = language
    return result


def detect_languages(folder, passages, forced=None):
    """Detect with an independent speech encoder before constraining Qwen decoding.

    Qwen's unconstrained singing output can translate into English. A separate,
    recording-level detector prevents the generated text from choosing its own
    alignment language. It is released before loading the lyric recognizer.
    """
    if forced:
        return [forced] * len(passages)
    if not any(p["active"] for p in passages):
        return ["en"] * len(passages)
    from faster_whisper import WhisperModel
    from .ai import audio_window
    model = None
    observations = []
    try:
        with model_loading("lyric-language-detection"):
            model = WhisperModel(str(whisper_path("medium")), device="cpu", compute_type="int8",
                                 cpu_threads=4, num_workers=1)
        for passage in passages:
            detected = []
            if passage["active"]:
                sample = audio_window(folder / "vocals.wav", passage["start"], passage["end"])
                code, probability, _ = model.detect_language(sample)
                if probability >= .6:
                    detected = [{"text": "detected", "detected_language": code}]
            observations.append({**passage, "candidates": detected})
        return recording_languages(observations)
    finally:
        del model
        gc.collect()


def alignment_key(segment):
    models = [{key: m[key] for key in ("repository", "revision")}
              for m in manifest() if "forced alignment" in m["purpose"]]
    payload = {"revision": ALIGNMENT_REVISION, "models": models,
               **{key: segment.get(key) for key in ("text", "language", "window_start", "window_end")}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def valid_time(item, start, end):
    return (all(isinstance(item.get(k), (int, float)) and math.isfinite(item[k]) for k in ("start", "end"))
            and start <= item["start"] < item["end"] <= end + .02)


def valid_words(words, start, end):
    return bool(words) and all(
        isinstance(w.get("word"), str) and normalized(w["word"])
        and valid_time(w, start, end)
        and all(valid_time(c, start, end) for c in w.get("chars", []))
        and (i == 0 or w["start"] >= words[i - 1]["start"])
        for i, w in enumerate(words))


def reusable_alignment(segment):
    return (segment.get("alignment_key") == alignment_key(segment)
            and not segment.get("external") and not segment.get("estimated", True)
            and not any(w.get("estimated", False) for w in segment.get("words", []))
            and valid_words(segment.get("words", []), segment["window_start"], segment["window_end"]))


def alignment_items(result):
    """Retain every sentence; standalone punctuation is not a sung word."""
    return ([w for segment in result["segments"] for w in segment.get("words", []) if normalized(w.get("word", ""))],
            [c for segment in result["segments"] for c in segment.get("chars", [])])


def recognize_qwen(folder, passages, forced, compact):
    from .ai import audio_window
    from .transcription import QualityRetry
    model = qwen_model(compact)
    session = mx = None
    try:
        import mlx.core as mx
        from mlx_qwen3_asr import Session
        with model_loading("qwen3-asr"):
            session = Session(model=str(qwen_path(compact)), dtype=mx.float16)
        for i, passage in enumerate(passages):
            for source in ("original.wav", "vocals.wav"):
                sample = audio_window(folder / source, passage["start"], passage["end"])
                if not vocal_activity(sample):
                    continue
                language = passage.get("language") or forced
                output = session.transcribe(sample, language=recognition.LANGUAGES.get(language),
                                            return_chunks=True)
                passage["candidates"].append({
                    "text": output.text.strip(), "detected_language": output.language,
                    "model": model["repository"], "model_revision": model["revision"],
                    "family": "qwen", "audio_source": source,
                    "truncated": bool(output.truncated or output.finish_reason == "repetition"),
                })
            print(f"Recognized both audio views through {passage['core_end']:.1f}s ({i + 1}/{len(passages)})",
                  flush=True)
    except (ImportError, OSError, RuntimeError) as exc:
        raise QualityRetry(f"quality retry: Qwen inference failed ({type(exc).__name__}: {exc})") from exc
    finally:
        del session
        gc.collect()
        if mx is not None:
            try:
                mx.synchronize()
                mx.clear_cache()
            except RuntimeError as exc:
                raise QualityRetry(f"quality retry: Qwen cleanup failed ({exc})") from exc


def recognize_whisper(folder, passages, indices, size="large-v3", detect=False):
    """One independent model, loaded only after Qwen/aligners have been released."""
    from faster_whisper import WhisperModel
    from .ai import audio_window
    model = None
    try:
        try:
            path = whisper_path(size)
        except OSError as exc:
            raise RuntimeError("Quality recovery model is not cached. Run .venv/bin/python -m "
                               "karapincho.setup_models --quality, then retry.") from exc
        with model_loading(f"whisper/{size}"):
            model = WhisperModel(str(path), device="cpu", compute_type="int8",
                                 cpu_threads=4, num_workers=1)
        revision = next(m["revision"] for m in manifest()
                        if m["repository"] == f"Systran/faster-whisper-{size}")
        if detect:
            observations = []
            for passage in passages:
                sample = audio_window(folder / "vocals.wav", passage["start"], passage["end"])
                code, probability, _ = model.detect_language(sample)
                observations.append({**passage, "candidates": [
                    {"text": "detected", "detected_language": code}] if probability >= .6 else []})
            for passage, language in zip(passages, recording_languages(observations)):
                passage["language"] = language
        for index in indices:
            passage = passages[index]
            # Recover from both views when MLX is unavailable as well.
            for source in ("original.wav", "vocals.wav"):
                audio = audio_window(folder / source, passage["start"], passage["end"])
                if not vocal_activity(audio):
                    continue
                output, info = model.transcribe(audio, language=passage["language"], task="transcribe",
                                               beam_size=5, word_timestamps=True, vad_filter=False,
                                               condition_on_previous_text=False, temperature=0.0)
                segments = [s for s in output if s.text.strip() and s.no_speech_prob <= .7
                            and math.isfinite(s.avg_logprob) and s.avg_logprob >= -1.5]
                # Text is evaluated using the common aligner, not Whisper's log probability.
                passage["candidates"].append({
                    "text": " ".join(s.text.strip() for s in segments), "family": "whisper",
                    "model": f"Systran/faster-whisper-{size}", "model_revision": revision,
                    "audio_source": source, "truncated": False, "detected_language": info.language,
                })
            print(f"Recovered passage through {passage['core_end']:.1f}s with Whisper {size}", flush=True)
    finally:
        del model
        gc.collect()


def align_candidates(folder, passages):
    """Evaluate every recognizer using the same CPU CTC alignment and audio view."""
    import torch
    from whisperx.alignment import align, load_align_model
    from .ai import audio_window
    torch.set_num_threads(4)
    for language in sorted({p["language"] for p in passages}):
        pending = [(p, c) for p in passages if p["language"] == language
                   for c in p["candidates"] if "words" not in c]
        if not pending:
            continue
        model = None
        try:
            name = str(japanese_alignment_path()) if language == "ja" else (
                str(spanish_alignment_path()) if language == "es" else None)
            from . import config
            with model_loading(f"candidate-alignment/{language}"):
                model, metadata = load_align_model(language, "cpu", model_name=name,
                                                   model_dir=str(config.DATA / "models" / "alignment"))
            for passage, candidate in pending:
                candidate.update(words=[], alignment_coverage=0.0, alignment_score=0.0, estimated=True)
                if not normalized(candidate["text"]):
                    continue
                # A shared audio view prevents selecting a model merely because its own
                # input was easier to align. Retry the same comparison on the mix if needed.
                for source in ("vocals.wav", "original.wav"):
                    try:
                        sample = audio_window(folder / source, passage["start"], passage["end"])
                        aligned = align([{"start": 0, "end": len(sample) / RATE, "text": candidate["text"]}],
                                        model, metadata, sample, "cpu", return_char_alignments=True,
                                        print_progress=False)
                        timed, chars = alignment_items(aligned)
                        valid = [w for w in timed if valid_words([w], 0, len(sample) / RATE)]
                        coverage = len(normalized("".join(w["word"] for w in valid))) / max(
                            1, len(normalized(candidate["text"])))
                        scores = [w.get("score", 0) for w in valid]
                        score = sum(s for s in scores if math.isfinite(s)) / max(1, len(scores))
                        if coverage > candidate["alignment_coverage"]:
                            candidate.update(alignment_coverage=min(1, coverage), alignment_score=score)
                        if len(valid) != len(timed) or coverage < .98 or score < .3:
                            continue
                        words = [{**w, "start": w["start"] + passage["start"],
                                  "end": w["end"] + passage["start"], "estimated": False,
                                  "chars": [{**c, "start": c["start"] + passage["start"],
                                             "end": c["end"] + passage["start"]}
                                            for c in chars if valid_time(c, 0, len(sample) / RATE)
                                            and w["start"] <= c["start"] < w["end"]]}
                                 for w in valid]
                        if normalized("".join(w["word"] for w in words)) != normalized(candidate["text"]):
                            continue
                        if not valid_words(words, passage["start"], passage["end"]):
                            continue
                        candidate.update(words=words, alignment_coverage=min(1, coverage),
                                         alignment_score=score, estimated=False, alignment_source=source)
                        break
                    except (ValueError, IndexError, KeyError) as exc:
                        candidate["alignment_error"] = type(exc).__name__
        except (OSError, ValueError, KeyError) as exc:
            for passage, candidate in pending:
                candidate.update(words=[], alignment_coverage=0.0, alignment_score=0.0,
                                 estimated=True, alignment_error=type(exc).__name__)
        finally:
            del model
            gc.collect()
    for passage in passages:
        sample = audio_window(folder / "vocals.wav", passage["start"], passage["end"])
        for candidate in passage["candidates"]:
            candidate["uncovered_vocal_seconds"] = uncovered_vocals(sample, candidate.get("words", []),
                                                                   passage["start"])


def uncovered_vocals(audio, words, offset):
    import numpy as np
    frames = len(audio) // 320
    if not frames:
        return 0.0
    energy = np.sqrt(np.mean(audio[:frames * 320].reshape(-1, 320) ** 2, axis=1))
    active = energy > max(1e-6, float(energy.max()) * .08)
    for word in words:
        first = max(0, int((word["start"] - offset - .3) / .02))
        last = min(frames, math.ceil((word["end"] - offset + .3) / .02))
        active[first:last] = False
    # Count sustained runs, tolerating short breath gaps without merging long rests.
    longest = current = 0
    for value in active:
        current = current + 1 if value else 0
        longest = max(longest, current)
    return round(longest * .02, 3)


def needs_recovery(passage):
    candidates = passage["candidates"]
    texts = [normalized(c["text"]) for c in candidates]
    return (not texts or len(texts) < 2 or len(set(texts)) != 1 or not any(texts)
            or any(c.get("truncated") or c.get("estimated", True)
                   or c.get("uncovered_vocal_seconds", 0) >= 2 for c in candidates))


def choose_candidate(candidates):
    usable = [c for c in candidates if normalized(c["text"]) and not c.get("truncated")]
    if not usable:
        return None, True
    # Independent-model agreement outranks two correlated passes of the same model.
    families = {}
    for c in usable:
        families.setdefault(normalized(c["text"]), set()).add(c["family"])
    winner = max(usable, key=lambda c: (
        len(families[normalized(c["text"])]),
        len({other["audio_source"] for other in usable if normalized(other["text"]) == normalized(c["text"])}),
        not c.get("estimated", True),
        round(c.get("alignment_coverage", 0), 2), round(c.get("alignment_score", 0), 2),
        c["family"] == "qwen" and c["audio_source"] == "original.wav"))
    independent = len(families[normalized(winner["text"])]) > 1
    dual_agreement = sum(normalized(c["text"]) == normalized(winner["text"]) for c in usable) > 1
    uncertain = (winner.get("estimated", True) or winner.get("uncovered_vocal_seconds", 0) >= 2
                 or not (independent or dual_agreement))
    if len({normalized(c["text"]) for c in usable}) > 1 and not independent:
        uncertain = True
    return winner, uncertain


def stitch(segments):
    """Remove only matching words in overlapping time, never distant repetitions."""
    result = []
    for segment in sorted(segments, key=lambda s: s["window_start"]):
        words = [dict(w) for w in segment["words"]]
        if result and words:
            previous = result[-1]["words"]
            # Match suffix/prefix sequences within the context overlap. A single
            # repeated word is deduplicated only when its time also overlaps.
            for count in range(min(len(previous), len(words), 32), 0, -1):
                left, right = previous[-count:], words[:count]
                if ([normalized(w["word"]) for w in left] == [normalized(w["word"]) for w in right]
                        and all(max(a["start"], b["start"]) < min(a["end"], b["end"])
                                for a, b in zip(left, right))):
                    words = words[count:]
                    break
            # Different words at a context seam: the preceding core owns words
            # before the seam; the following core owns words after it.
            seam = segment["core_start"]
            if previous and words and words[0]["start"] < previous[-1]["end"]:
                previous[:] = [w for w in previous if (w["start"] + w["end"]) / 2 < seam]
                words = [w for w in words if (w["start"] + w["end"]) / 2 >= seam]
                if previous and words and previous[-1]["end"] > words[0]["start"]:
                    previous[-1]["end"] = min(previous[-1]["end"], seam)
                    words[0]["start"] = max(words[0]["start"], seam)
                    # A clipped boundary is an estimate until it is acoustically
                    # aligned again. Do not cache it as verified character timing.
                    for word in (previous[-1], words[0]):
                        word["estimated"] = True
                        word["chars"] = [{**c, "start": max(c["start"], word["start"]),
                                          "end": min(c["end"], word["end"])}
                                         for c in word.get("chars", [])
                                         if max(c["start"], word["start"]) < min(c["end"], word["end"])]
                    result[-1].update(estimated=True, uncertain=True)
                    segment["estimated"] = True
                    segment["uncertain"] = True
                    segment["boundary_conflict"] = True
                if previous:
                    result[-1].update(start=previous[0]["start"], end=previous[-1]["end"],
                                      text=join_words(previous, result[-1]["language"]))
                    result[-1]["alignment_key"] = alignment_key(result[-1])
                else:
                    result.pop()
        if words:
            item = {**segment, "words": words, "text": join_words(words, segment["language"]),
                    "start": words[0]["start"], "end": words[-1]["end"]}
            item["alignment_key"] = alignment_key(item)
            result.append(item)
    return result


def join_words(words, language):
    # WhisperX words have no leading spaces; Whisper words may have them.
    return ("" if language in ("ja", "zh") else " ").join(w["word"].strip() for w in words).strip()


def transcribe_quality(folder, low_memory=False):
    from .ai import audio_window
    audio = audio_window(folder / "vocals.wav")
    passages = [{**window, "candidates": [], "active": vocal_activity(
        audio[round(window["core_start"] * RATE):round(window["core_end"] * RATE)])}
        for window in windows(audio)]
    del audio
    job = read_json(folder / "job.json") if (folder / "job.json").exists() else {}
    forced = job.get("lyric_settings", {}).get("language") or None
    warnings = []
    compact = recognition.quantized(acceleration.CURRENT.physical_bytes, acceleration.CURRENT.reduced)
    qwen = acceleration.CURRENT.backend == "mlx" and not low_memory and (not forced or forced in recognition.LANGUAGES)
    for passage, language in zip(passages, detect_languages(folder, passages, forced)):
        passage["language"] = language
    qwen = qwen and all(p["language"] in recognition.LANGUAGES for p in passages)
    if qwen:
        recognize_qwen(folder, passages, forced, compact)
    else:
        warnings.append("Quality recognition used CPU recovery; Qwen MLX was unavailable or memory was reduced.")
    # All Qwen models have been released before common alignment and CPU recovery.
    align_candidates(folder, passages)
    recover = [i for i, p in enumerate(passages) if needs_recovery(p) and (
        p["active"] or any(normalized(c["text"]) for c in p["candidates"]))]
    if recover:
        recognize_whisper(folder, passages, recover, "medium" if low_memory else "large-v3",
                          detect=False)
        align_candidates(folder, passages)
        warnings.append(f"Independently checked {len(recover)} lyric passages with CPU beam search.")
    segments, diagnostics = [], []
    for passage in passages:
        candidate, uncertain = choose_candidate(passage["candidates"])
        diagnostics.append({key: passage[key] for key in ("start", "end", "language", "active")})
        diagnostics[-1].update(uncertain=uncertain, candidates=[
            {k: v for k, v in c.items() if k != "words"} for c in passage["candidates"]])
        if candidate is None:
            if passage["active"]:
                warnings.append(f"No reliable wording recovered at {passage['core_start']:.1f}s; review this passage.")
            continue
        if uncertain:
            warnings.append(f"Uncertain lyric wording at {passage['core_start']:.1f}s; review this passage.")
        words = candidate["words"] or estimated_words(candidate["text"], passage["start"], passage["end"])
        words = [{**w, "estimated": candidate["estimated"]} for w in words]
        segments.append({"text": candidate["text"], "language": passage["language"], "words": words,
                         "start": words[0]["start"], "end": words[-1]["end"],
                         "window_start": passage["start"], "window_end": passage["end"],
                         "core_start": passage["core_start"], "core_end": passage["core_end"],
                         "estimated": candidate["estimated"], "uncertain": uncertain,
                         "recognizer": candidate["model"], "model_revision": candidate["model_revision"],
                         "audio_source": candidate["audio_source"]})
    segments = stitch(segments)
    warnings.extend(f"Uncertain lyric boundary at {s['core_start']:.1f}s; review this passage."
                    for s in segments if s.get("boundary_conflict"))
    if not segments:
        raise ValueError("No intelligible vocals were detected. Supply lyrics or try another recording.")
    result = {"segments": segments, "warnings": warnings, "source": "transcription",
              "model": "quality-v2/qwen3-asr+whisper", "recognition": recognition.provenance(job),
              "passages": diagnostics}
    write_json(folder / "transcript.json", result)
    return {k: v for k, v in result.items() if k != "segments"}
