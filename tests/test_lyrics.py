# SPDX-License-Identifier: GPL-3.0-or-later
import json
from types import SimpleNamespace

import pytest

from karapincho import config, lyrics
from karapincho.media import read_json, write_json


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    write_json(tmp_path / "job.json", {"lyric_settings": {}})
    write_json(tmp_path / "prepare.json", {"metadata": {
        "artist": "Singer", "title": "Song", "album": "Album", "duration": 100,
    }})
    return tmp_path


def record(**values):
    return {"id": 1, "trackName": "Song", "artistName": "Singer", "duration": 100,
            "syncedLyrics": "[00:10.00]hello world\n[00:20.00]sing again", **values}


def reference(texts, language="en", starts=None):
    return {"segments": [{"text": text, "language": language, "start": start, "end": start + 2,
                          "words": [{"word": text, "start": start, "end": start + 2, "score": .9}]}
                         for text, start in zip(texts, starts or [10 + i * 10 for i in range(len(texts))])]}


def test_lrc_offsets_repeats_and_unicode():
    lines = lyrics.parse_lyrics("[ar:歌手]\n[offset:-500]\n[00:10.00][00:20.500]こんにちは\n[00:25.00]")
    assert lines == [{"text": "こんにちは", "start": 9.5}, {"text": "こんにちは", "start": 20},
                     {"text": "", "start": 24.5}]


@pytest.mark.parametrize("text", ["[00:99]bad", "[00:01]one\nuntimed", "[offset:1]", ""])
def test_invalid_lyrics(text):
    with pytest.raises(ValueError):
        lyrics.parse_lyrics(text)


def test_user_lyrics_override_and_never_contact_provider(folder, monkeypatch):
    write_json(folder / "job.json", {"lyric_settings": {"title": "Corrected", "artist": "Correct singer",
                                                       "lyrics": "こんにちは", "language": "ja"}})
    monkeypatch.setattr(lyrics, "request", lambda *a: pytest.fail("Should not look up manual lyrics"))
    result = lyrics.lookup(folder)
    assert result["source"] == "user"
    assert result["metadata"]["title"] == "Corrected"
    assert result["lines"][0]["text"] == "こんにちは"


def test_exact_lookup(folder, monkeypatch):
    calls = []
    def request(endpoint, params):
        calls.append((endpoint, params))
        return record()
    monkeypatch.setattr(lyrics, "request", request)
    result = lyrics.lookup(folder)
    assert result["source"] == "lrclib" and result["record_id"] == 1
    assert len(calls) == 1 and calls[0][1]["album_name"] == "Album"


@pytest.mark.parametrize("change", [{"duration": 103}, {"artistName": "Other"},
                                   {"trackName": "Song (Live)"}, {"duration": float("nan")},
                                   {"instrumental": True}])
def test_wrong_record_rejected(folder, monkeypatch, change):
    monkeypatch.setattr(lyrics, "request", lambda endpoint, params: record(**change) if endpoint == "get" else [])
    assert lyrics.lookup(folder)["source"] == "transcription"


def test_search_ambiguity(folder, monkeypatch):
    monkeypatch.setattr(lyrics, "request", lambda endpoint, params: None if endpoint == "get" else [
        record(), record(id=2, syncedLyrics="[00:10]different words")])
    assert lyrics.lookup(folder)["source"] == "transcription"


def test_search_prefers_synced_over_exact_plain(folder, monkeypatch):
    monkeypatch.setattr(lyrics, "request", lambda endpoint, params:
                        record(syncedLyrics=None, plainLyrics="hello world") if endpoint == "get" else [record(id=2)])
    result = lyrics.lookup(folder)
    assert result["record_id"] == 2 and result["lines"][0]["start"] == 10


def test_outage_and_missing_metadata(folder, monkeypatch):
    def unavailable(*args):
        raise TimeoutError("offline")
    monkeypatch.setattr(lyrics, "request", unavailable)
    result = lyrics.lookup(folder)
    assert result["source"] == "transcription" and "unavailable" in result["warnings"][0]
    metadata = read_json(folder / "prepare.json")
    metadata["metadata"]["artist"] = "Unknown Artist"
    write_json(folder / "prepare.json", metadata)
    monkeypatch.setattr(lyrics, "request", lambda *a: pytest.fail("Unknown artist must not search"))
    assert "insufficient" in lyrics.lookup(folder)["warnings"][0]


def test_http_cache_and_timeout(folder, monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return json.dumps(record()).encode()
    calls = []
    def open_url(req, timeout):
        calls.append(timeout)
        assert req.full_url.startswith("https://lrclib.net/api/get?")
        return Response()
    monkeypatch.setattr(lyrics, "urlopen", open_url)
    assert lyrics.request("get", {"track_name": "日本語"})["id"] == 1
    assert lyrics.request("get", {"track_name": "日本語"})["id"] == 1
    assert calls == [8]


@pytest.mark.parametrize("language,texts", [
    ("ja", ["こんにちは世界", "もう一度歌おう"]), ("es", ["hola corazón", "cantamos otra vez"]),
    ("en", ["hello world", "sing again"]), ("ko", ["안녕하세요 세상", "다시 노래해요"]),
])
def test_original_script_and_intro_offset(language, texts):
    source = {"source": "user", "language": language,
              "lines": lyrics.parse_lyrics(f"[00:05]{texts[0]}\n[00:15]{texts[1]}")}
    output = lyrics.compose(source, reference(texts, language), 40)
    assert [s["text"] for s in output["segments"]] == texts
    assert output["timing_offset"] == 5
    assert [s["start"] for s in output["segments"]] == [10, 20]


def test_plain_repeated_choruses_and_mixed_languages():
    texts = ["hello world", "こんにちは世界", "hello world"]
    ref = reference(texts)
    ref["segments"][1]["language"] = "ja"
    output = lyrics.compose({"source": "user", "lines": lyrics.parse_lyrics("\n".join(texts))}, ref, 40)
    assert [s["text"] for s in output["segments"]] == texts
    assert [s["language"] for s in output["segments"]] == ["en", "ja", "en"]
    assert [s["start"] for s in output["segments"]] == [10, 20, 30]


def test_unlocatable_plain_online_rejected_but_user_preserved():
    source = {"source": "lrclib", "language": "en", "lines": lyrics.parse_lyrics("correct lyrics")}
    with pytest.raises(ValueError, match="no reliable audio anchors"):
        lyrics.compose(source, reference(["xyz"]), 40)
    source["source"] = "user"
    result = lyrics.compose(source, reference(["xyz"]), 40)
    assert result["segments"][0]["text"] == "correct lyrics"
    assert result["warnings"]


def test_out_of_range_manual_timestamp_fails():
    with pytest.raises(ValueError, match="beyond"):
        lyrics.compose({"source": "user", "language": "en", "lines": lyrics.parse_lyrics("[01:00]hello")},
                       {"segments": []}, 30)


def test_alignment_unavailable_preserves_user_words(folder, monkeypatch):
    import sys
    from karapincho.ai import align
    def missing(*a, **kw): raise ValueError("unsupported")
    monkeypatch.setitem(sys.modules, "whisperx.alignment", SimpleNamespace(load_align_model=missing, align=missing))
    transcript = lyrics.compose({"source": "user", "language": "ja", "lines": lyrics.parse_lyrics("[00:10]こんにちは")},
                                {"segments": []}, 20)
    write_json(folder / "transcript.json", transcript)
    result = align(folder)
    words = read_json(folder / "aligned.json")["words"]
    assert "".join(w["word"] for w in words) == "こんにちは"
    assert all(w["estimated"] for w in words)
    assert result["alignment_quality"]["estimated"] == 1


def test_alignment_retries_original_and_preserves_text(folder, monkeypatch):
    import sys
    from karapincho import ai
    calls = []
    def forced(segments, *args, **kwargs):
        calls.append(segments[0]["text"])
        if len(calls) == 1:
            raise ValueError("weak vocals")
        return {"segments": [{"words": [{"word": "こんにちは", "start": 2, "end": 4, "score": .9}], "chars": []}]}
    monkeypatch.setitem(sys.modules, "whisperx.alignment", SimpleNamespace(
        load_align_model=lambda *a, **k: (None, {}), align=forced))
    # The aligner uses a non-None model to distinguish unavailable models.
    sys.modules["whisperx.alignment"].load_align_model = lambda *a, **k: (object(), {})
    monkeypatch.setattr(ai, "audio_window", lambda *a: [])
    monkeypatch.setattr(ai, "japanese_alignment_path", lambda: folder / "pinned-japanese-aligner")
    transcript = lyrics.compose({"source": "user", "language": "ja", "lines": lyrics.parse_lyrics("[00:10]こんにちは")},
                                {"segments": []}, 20)
    write_json(folder / "transcript.json", transcript)
    result = ai.align(folder)
    assert calls == ["こんにちは", "こんにちは"]
    assert result["alignment_quality"]["precise"] == 1
    assert read_json(folder / "aligned.json")["words"][0]["start"] == 10


def test_neighbor_windows_do_not_interleave_words():
    texts = ["hello world", "sing again", "goodbye world"]
    ref = reference(texts, starts=[10, 12, 14])
    result = lyrics.compose({"source": "user", "language": "en", "lines": lyrics.parse_lyrics("\n".join(texts))}, ref, 20)
    for left, right in zip(result["segments"], result["segments"][1:]):
        assert left["window_end"] <= right["window_start"]


def test_plain_exact_survives_search_outage(folder, monkeypatch):
    def request(endpoint, params):
        if endpoint == "get":
            return record(syncedLyrics=None, plainLyrics="hello world")
        raise TimeoutError("offline")
    monkeypatch.setattr(lyrics, "request", request)
    result = lyrics.lookup(folder)
    assert result["source"] == "lrclib" and result["lines"][0]["start"] is None


def test_japanese_script_overrides_incorrect_asr_language():
    result = lyrics.compose({"source": "user", "lines": lyrics.parse_lyrics("[00:10]こんにちは")},
                            reference(["こんにちは"], language="en"), 20)
    assert result["segments"][0]["language"] == "ja"


def test_bad_online_alignment_uses_transcription(folder, monkeypatch):
    import sys
    from karapincho import ai
    def fail(*args, **kwargs):
        raise ValueError("bad alignment")
    monkeypatch.setitem(sys.modules, "whisperx.alignment", SimpleNamespace(
        load_align_model=lambda *a, **k: (object(), {}), align=fail))
    monkeypatch.setattr(ai, "audio_window", lambda *a: [])
    transcript = lyrics.compose({"source": "lrclib", "language": "en", "lines": lyrics.parse_lyrics("[00:10]wrong wording")},
                                reference(["correct wording"]), 20)
    write_json(folder / "transcript.json", transcript)
    result = ai.align(folder)
    words = read_json(folder / "aligned.json")["words"]
    assert "".join(w["word"] for w in words) == "correct wording"
    assert result["source"] == "lrclib+transcription"
    assert result["alignment_quality"]["transcription_fallback"] == 1
