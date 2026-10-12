# SPDX-License-Identifier: GPL-3.0-or-later
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from karapincho import acceleration, recognition
from karapincho import quality_transcription as q
from karapincho.media import read_json, write_json


def candidate(text="hola mundo", family="qwen", source="original.wav", **extra):
    return {"text": text, "family": family, "audio_source": source, "truncated": False,
            "estimated": False, "alignment_coverage": 1, "alignment_score": .8,
            "model": family, "model_revision": "test", **extra}


@pytest.mark.parametrize("seconds", [0, .01, 1, 25, 28, 60, 1200])
def test_bounded_windows_cover_entire_recording_with_context(seconds):
    audio = np.ones(round(q.RATE * seconds), dtype=np.float32)
    windows = q.windows(audio)
    if seconds == 0:
        assert not windows
        return
    assert windows[0]["core_start"] == 0
    assert windows[-1]["core_end"] == seconds
    assert all(0 < w["end"] - w["start"] <= 28.001 for w in windows)
    assert all(a["core_end"] == b["core_start"] and a["end"] > b["start"]
               for a, b in zip(windows, windows[1:]))


def test_boundary_chooses_low_energy_trough():
    audio = np.ones(q.RATE * 60, dtype=np.float32)
    audio[24 * q.RATE:25 * q.RATE] = 0
    assert 24 <= q.windows(audio)[0]["core_end"] < 25


def test_quiet_singing_triggers_investigation_but_digital_silence_does_not():
    assert q.vocal_activity(np.ones(q.RATE) * .00001)
    assert not q.vocal_activity(np.zeros(q.RATE))
    assert not q.vocal_activity(np.array([]))
    words = [{"start": 0, "end": 1}]
    assert q.uncovered_vocals(np.ones(q.RATE * 5), words, 0) >= 3
    assert q.uncovered_vocals(np.zeros(q.RATE * 5), [], 0) == 0


def passage(language, start=0, end=24):
    return {"core_start": start, "core_end": end,
            "candidates": [candidate(detected_language=language)]}


def test_recording_language_does_not_flip_on_a_single_window():
    passages = [passage("Spanish", i * 24, (i + 1) * 24) for i in range(4)]
    passages[1] = passage("English", 24, 48)
    assert q.recording_languages(passages) == ["es"] * 4
    assert q.recording_languages(passages, "ja") == ["ja"] * 4


def test_sustained_mixed_language_passage_can_switch():
    passages = [passage(code, i * 24, (i + 1) * 24)
                for i, code in enumerate(["Spanish"] * 3 + ["English"] * 2)]
    assert q.recording_languages(passages) == ["es"] * 3 + ["en"] * 2


def test_independent_agreement_beats_correlated_high_scoring_wrong_output():
    original = candidate(alignment_score=.5, score=-100)
    agreeing = candidate(family="whisper", alignment_score=.5, score=-999)
    wrong = candidate("wrong output", alignment_score=.99, score=100)
    winner, uncertain = q.choose_candidate([wrong, original, agreeing])
    assert winner is original and not uncertain


def test_alignment_tie_keeps_original_qwen_and_flags_disagreement():
    original = candidate()
    alternate = candidate("adios mundo", source="vocals.wav")
    winner, uncertain = q.choose_candidate([alternate, original])
    assert winner is original and uncertain


def test_well_aligned_lone_hallucination_cannot_replace_dual_view_consensus():
    original = candidate(estimated=True, alignment_coverage=.95)
    vocals = candidate(source="vocals.wav", estimated=True, alignment_coverage=.95)
    hallucination = candidate("subscribe to the channel", family="whisper", alignment_score=.99)
    winner, uncertain = q.choose_candidate([original, vocals, hallucination])
    assert winner is original and uncertain


def test_adjacent_repeated_single_words_are_not_deduplicated():
    result = q.stitch([segment("la", 23, 24), segment("la", 24.05, 25, 24)])
    assert [s["text"] for s in result] == ["la", "la"]


def test_truncated_candidates_are_never_selected():
    assert q.choose_candidate([candidate(truncated=True)]) == (None, True)
    assert q.needs_recovery({"candidates": [candidate(), candidate(truncated=True)]})


def test_empty_output_failed_alignment_and_uncovered_vocals_trigger_recovery():
    for candidates in ([], [candidate("")], [candidate(), candidate(estimated=True)],
                       [candidate(), candidate(uncovered_vocal_seconds=3)]):
        assert q.needs_recovery({"candidates": candidates})
    assert not q.needs_recovery({"candidates": [candidate(), candidate(source="vocals.wav")]})


def segment(text, start, end, core_start=0):
    return {"text": text, "language": "es", "window_start": max(0, core_start - 1),
            "window_end": end + 1, "core_start": core_start, "estimated": False,
            "start": start, "end": end, "words": [{"word": text, "start": start, "end": end}]}


def test_stitch_only_deduplicates_matching_words_at_overlapping_times():
    assert len(q.stitch([segment("hola", 23, 24.5), segment("hola", 23.1, 24.6, 24)])) == 1
    result = q.stitch([segment("hola", 1, 2), segment("hola", 30, 31, 28)])
    assert [s["text"] for s in result] == ["hola", "hola"]


def test_word_across_boundary_survives_stitching():
    left = segment("patita", 24, 25.4)
    right = segment("principal", 25.4, 27, 25)
    assert [s["text"] for s in q.stitch([left, right])] == ["patita", "principal"]


def test_conflicting_boundary_marks_clipped_times_estimated_and_clips_chars():
    left = segment("one", 23.8, 24.4)
    left["words"][0]["chars"] = [{"char": "e", "start": 24.1, "end": 24.4}]
    right = segment("two", 24, 24.8, 24.2)
    result = q.stitch([left, right])
    assert len(result) == 2 and all(s["estimated"] and s["uncertain"] for s in result)
    assert result[0]["words"][-1]["end"] == result[1]["words"][0]["start"] == 24.2
    assert result[0]["words"][-1]["chars"][0]["end"] == 24.2
    assert not any(q.reusable_alignment(s) for s in result)


@pytest.mark.parametrize("word", [{"start": float("nan"), "end": 1}, {"start": 1, "end": 0},
                                  {"start": -1, "end": 1}, {"start": 0, "end": 5},
                                  {"start": 0, "end": float("inf")}])
def test_invalid_timestamps_cannot_be_reused(word):
    assert not q.valid_words([{"word": "hola", **word}], 0, 2)


def test_alignment_reuse_requires_current_text_model_revision_and_valid_words():
    item = segment("hola", 0, 1)
    item["alignment_key"] = q.alignment_key(item)
    assert q.reusable_alignment(item)
    item["text"] = "otra letra"
    assert not q.reusable_alignment(item)
    item["alignment_key"] = q.alignment_key(item)
    item["estimated"] = True
    assert not q.reusable_alignment(item)


def test_alignment_keeps_every_sentence_and_character(tmp_path, monkeypatch):
    first = {"word": "Hola.", "start": 1, "end": 2, "score": .8}
    second = {"word": "Adiós.", "start": 3, "end": 4, "score": .8}
    alignment = {"segments": [
        {"words": [first], "chars": [{"char": "H", "start": 1, "end": 1.1}]},
        {"words": [second], "chars": [{"char": "A", "start": 3, "end": 3.1}]},
    ]}
    monkeypatch.setitem(sys.modules, "whisperx.alignment", SimpleNamespace(
        load_align_model=lambda *args, **kwargs: (object(), {}),
        align=lambda *args, **kwargs: alignment))
    monkeypatch.setattr(q, "spanish_alignment_path", lambda: tmp_path)
    monkeypatch.setattr("karapincho.ai.audio_window", lambda *args: np.ones(q.RATE * 5))
    item = {"start": 10, "end": 15, "language": "es", "candidates": [candidate("Hola. Adiós.")]}
    q.align_candidates(tmp_path, [item])
    output = item["candidates"][0]
    assert not output["estimated"] and output["alignment_coverage"] == 1
    assert [(w["word"], w["start"]) for w in output["words"]] == [("Hola.", 11), ("Adiós.", 13)]
    assert [w["chars"][0]["char"] for w in output["words"]] == ["H", "A"]


def test_japanese_standalone_punctuation_does_not_invalidate_lyric_alignment():
    words, chars = q.alignment_items({"segments": [{"words": [
        {"word": "桜", "start": 0, "end": 1}, {"word": "。"}], "chars": []}]})
    assert words == [{"word": "桜", "start": 0, "end": 1}]
    assert q.valid_words(words, 0, 1)
    words[0]["chars"] = [{"char": "桜", "start": float("nan"), "end": 1}]
    assert not q.valid_words(words, 0, 1)


def test_accepted_alignment_reuse_skips_model_loading(tmp_path, monkeypatch):
    from karapincho import ai
    item = segment("hola", 0, 1)
    item["alignment_key"] = q.alignment_key(item)
    write_json(tmp_path / "transcript.json", {"segments": [item]})
    monkeypatch.setitem(sys.modules, "whisperx.alignment", SimpleNamespace(
        load_align_model=lambda *args, **kwargs: pytest.fail("Accepted alignment must be reused"),
        align=lambda *args, **kwargs: pytest.fail("Accepted alignment must be reused")))
    ai.align(tmp_path)
    output = read_json(tmp_path / "aligned.json")
    assert output["words"][0]["word"] == "hola"
    assert not output["words"][0]["estimated"]
    assert output["alignment_quality"]["precise"] == 1


def test_quality_readiness_reports_missing_optional_models(monkeypatch):
    def missing(*args):
        raise FileNotFoundError("not cached")
    monkeypatch.setenv("KARAPINCHO_TRANSCRIPTION", "quality-v2")
    monkeypatch.setattr(recognition.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(recognition, "qwen_path", missing)
    monkeypatch.setattr(recognition, "whisper_path", missing)
    status = recognition.readiness()
    assert status["engine"] == "quality-v2" and not status["ready"] and not status["validated"]
    assert status["missing"] == ["mlx-qwen3-asr", "Qwen3-ASR-1.7B", "Whisper large-v3"]


def test_detected_language_is_fixed_before_qwen_decodes(tmp_path, monkeypatch):
    sf.write(tmp_path / "vocals.wav", np.ones(q.RATE * 5) * .01, q.RATE)
    monkeypatch.setattr(acceleration, "CURRENT", acceleration.Runtime(backend="mlx", physical_bytes=24*acceleration.GIB))
    monkeypatch.setattr(q, "detect_languages", lambda *args: ["ja"])
    def recognize(folder, passages, forced, compact):
        assert passages[0]["language"] == "ja" and forced is None
        passages[0]["candidates"] = [candidate("桜"), candidate("桜", source="vocals.wav")]
    def align(folder, passages):
        for c in passages[0]["candidates"]:
            c["words"] = [{"word": "桜", "start": 1, "end": 2}]
    monkeypatch.setattr(q, "recognize_qwen", recognize)
    monkeypatch.setattr(q, "align_candidates", align)
    q.transcribe_quality(tmp_path)
    assert read_json(tmp_path / "transcript.json")["segments"][0]["language"] == "ja"


def test_memory_recovery_is_cpu_and_explicitly_degraded(tmp_path, monkeypatch):
    sf.write(tmp_path / "vocals.wav", np.ones(q.RATE * 5) * .01, q.RATE)
    write_json(tmp_path / "job.json", {"lyric_settings": {"language": "es"}})
    monkeypatch.setattr(acceleration, "CURRENT", acceleration.Runtime(backend="cpu"))
    monkeypatch.setattr(q, "recognize_qwen", lambda *args: pytest.fail("Low-memory recovery must release MLX"))
    def recover(folder, passages, indices, size, detect):
        assert size == "medium" and indices == [0]
        passages[0]["candidates"] = [candidate(family="whisper")]
    def align(folder, passages):
        for c in passages[0]["candidates"]:
            c["words"] = [{"word": c["text"], "start": 1, "end": 3}]
    monkeypatch.setattr(q, "recognize_whisper", recover)
    monkeypatch.setattr(q, "align_candidates", align)
    q.transcribe_quality(tmp_path, low_memory=True)
    assert any("CPU recovery" in w for w in read_json(tmp_path / "transcript.json")["warnings"])


def test_quality_model_profile_and_gate(monkeypatch):
    assert recognition.quantized(8 * acceleration.GIB)
    assert not recognition.quantized(24 * acceleration.GIB)
    assert recognition.quantized(24 * acceleration.GIB, True)
    monkeypatch.delenv("KARAPINCHO_TRANSCRIPTION", raising=False)
    assert recognition.engine() == "legacy"
    monkeypatch.setenv("KARAPINCHO_TRANSCRIPTION", "quality-v2")
    assert recognition.engine() == "quality-v2"
    monkeypatch.setenv("KARAPINCHO_TRANSCRIPTION", "invalid")
    with pytest.raises(ValueError):
        recognition.engine()


def test_pipeline_releases_qwen_before_alignment_and_cpu_recovery(tmp_path, monkeypatch):
    sf.write(tmp_path / "vocals.wav", np.ones(q.RATE * 5) * .01, q.RATE)
    write_json(tmp_path / "job.json", {"lyric_settings": {"language": "es"}})
    monkeypatch.setattr(acceleration, "CURRENT", acceleration.Runtime(backend="mlx", physical_bytes=24*acceleration.GIB))
    calls = []

    def recognize(folder, passages, forced, compact):
        calls.append("qwen released")
        passages[0]["candidates"] = [candidate(), candidate("otra letra", source="vocals.wav")]

    def align(folder, passages):
        calls.append("aligner released")
        for p in passages:
            for c in p["candidates"]:
                c["words"] = [{"word": c["text"], "start": 1, "end": 3}]

    def recover(folder, passages, indices, size, detect):
        calls.append("whisper released")
        assert size == "large-v3" and indices == [0] and not detect
        passages[0]["candidates"].append(candidate(family="whisper"))

    monkeypatch.setattr(q, "recognize_qwen", recognize)
    monkeypatch.setattr(q, "align_candidates", align)
    monkeypatch.setattr(q, "recognize_whisper", recover)
    q.transcribe_quality(tmp_path)
    assert calls == ["qwen released", "aligner released", "whisper released", "aligner released"]
    result = read_json(tmp_path / "transcript.json")
    assert result["segments"][0]["text"] == "hola mundo"
    assert not result["segments"][0]["uncertain"]
    assert result["passages"][0]["candidates"][2]["family"] == "whisper"


def test_silence_does_not_invoke_cpu_recognition(tmp_path, monkeypatch):
    sf.write(tmp_path / "vocals.wav", np.zeros(q.RATE), q.RATE)
    monkeypatch.setattr(acceleration, "CURRENT", acceleration.Runtime(backend="cpu"))
    monkeypatch.setattr(q, "align_candidates", lambda *args: None)
    monkeypatch.setattr(q, "detect_languages", lambda folder, passages, forced: ["en"] * len(passages))
    monkeypatch.setattr(q, "recognize_whisper", lambda *args, **kwargs: pytest.fail("Silence must not trigger ASR"))
    with pytest.raises(ValueError, match="No intelligible vocals"):
        q.transcribe_quality(tmp_path)


def test_qwen_session_released_on_inference_failure(tmp_path, monkeypatch):
    calls = []
    class Session:
        def __init__(self, **kwargs):
            pass
        def transcribe(self, *args, **kwargs):
            raise RuntimeError("Metal device failure")
        def __del__(self):
            calls.append("released")
    mx = SimpleNamespace(float16="fp16", synchronize=lambda: calls.append("synchronized"),
                         clear_cache=lambda: calls.append("cleared"))
    monkeypatch.setitem(sys.modules, "mlx.core", mx)
    monkeypatch.setitem(sys.modules, "mlx_qwen3_asr", SimpleNamespace(Session=Session))
    monkeypatch.setattr(q, "qwen_path", lambda compact: tmp_path)
    monkeypatch.setattr("karapincho.ai.audio_window", lambda *args: np.ones(q.RATE))
    with pytest.raises(RuntimeError, match="Metal device"):
        q.recognize_qwen(tmp_path, [{"start": 0, "end": 1, "candidates": []}], "es", False)
    # A raised exception retains the inference frame until its traceback is released;
    # the stage exits before another model can be loaded on this failure path.
    assert set(calls) == {"released", "synchronized", "cleared"}


def test_qwen_import_failure_requests_cpu_recovery(tmp_path, monkeypatch):
    mx = SimpleNamespace(synchronize=lambda: None, clear_cache=lambda: None)
    monkeypatch.setitem(sys.modules, "mlx.core", mx)
    monkeypatch.setitem(sys.modules, "mlx_qwen3_asr", SimpleNamespace())
    with pytest.raises(RuntimeError, match="quality retry: Qwen inference failed .*ImportError"):
        q.recognize_qwen(tmp_path, [], "es", False)


def test_checkpoint_signature_changes_with_recognizer_and_model_revision(tmp_path, monkeypatch):
    from karapincho.worker import signature
    for name in ("separate", "lyrics"):
        write_json(tmp_path / f"{name}.json", {})
    monkeypatch.setenv("KARAPINCHO_TRANSCRIPTION", "legacy")
    before = signature("transcribe", tmp_path, {})
    monkeypatch.setenv("KARAPINCHO_TRANSCRIPTION", "quality-v2")
    assert signature("transcribe", tmp_path, {}) != before
    first = signature("transcribe", tmp_path, {})
    assert signature("transcribe", tmp_path, {}, reduced=True) != first
    monkeypatch.setattr(recognition, "REVISION", 999)
    assert signature("transcribe", tmp_path, {}) != first
