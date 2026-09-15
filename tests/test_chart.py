# SPDX-License-Identifier: GPL-3.0-or-later
import numpy as np
import pytest

from karapincho.chart import (
    hz_to_pitch,
    japanese_units,
    lyric_units,
    make_notes,
    render_chart,
    ticks,
    validate_chart,
)


def word(text, start=1, end=2, language="en", phrase=1):
    return {"word": text, "start": start, "end": end, "language": language, "phrase": phrase}


def test_classic_timing_and_pitch():
    assert ticks(1) == 20
    assert ticks(10.05) == 201
    assert hz_to_pitch(440) == 9
    assert hz_to_pitch(261.625565) == 0
    assert hz_to_pitch(220) == -3
    with pytest.raises(ValueError):
        hz_to_pitch(0)


def test_spanish_syllables_preserve_words():
    units = lyric_units([word("canciones", language="es")])
    assert "".join(u["text"] for u in units) == "canciones "
    assert len(units) > 1
    assert all(u["end"] > u["start"] for u in units)
    assert units[0]["start"] == 1 and units[-1]["end"] == 2


def test_japanese_romaji_and_mixed_english():
    units = japanese_units([word("君の夢", language="ja"), word("hello", 2, 3, "ja")])
    text = "".join(u["text"] for u in units)
    assert text.isascii()
    assert "kimi" in text and "yume" in text and "hello" in text
    assert units[-1]["end"] == 3


def test_japanese_long_vowels():
    units = japanese_units([word("コーヒー", language="ja")])
    assert "".join(u["text"] for u in units).strip() == "koohii"


def test_english_words_in_japanese_phrase_remain_separate():
    units = japanese_units([word("君", 0, 1, "ja"), word("hello", 1, 2, "ja"), word("world", 2, 3, "ja")])
    assert "hello world" in "".join(u["text"] for u in units)


def test_silence_is_not_scored_as_a_note():
    units = [{"text": "hello ", "start": 1, "end": 2, "phrase": 1}]
    track = {
        "time": np.arange(0, 3, 0.01),
        "hz": np.full(300, 440),
        "confidence": np.ones(300),
        "energy": np.zeros(300),
    }
    notes, warnings = make_notes(units, track, 3)
    assert notes[0]["type"] == "F"
    assert warnings


def test_sustained_pitch_changes_make_melisma():
    track = {
        "time": np.arange(0, 3, 0.01),
        "hz": np.r_[np.full(150, 440), np.full(150, 493.88)],
        "confidence": np.ones(300),
        "energy": np.ones(300) * 0.1,
    }
    notes, _ = make_notes([{"text": "you ", "start": 1, "end": 2, "phrase": 1}], track, 3)
    assert [n["pitch"] for n in notes] == [9, 11]
    assert notes[0]["text"] == "you" and notes[1]["text"] == "~ "


def test_export_roundtrip_long_intro_and_overlap(tmp_path):
    notes = [
        {"start": 10, "end": 10.45, "type": ":", "pitch": 9, "text": "hi ", "phrase": 1},
        {"start": 10.4, "end": 10.9, "type": ":", "pitch": 9, "text": "there ", "phrase": 2},
    ]
    text = render_chart(notes, {"title": "Hello\n#BPM:1", "artist": "Artist", "duration": 12})
    for name in ("audio.mp3", "video.mp4", "cover.jpg"):
        (tmp_path / name).write_bytes(b"fixture")
    result = validate_chart(text, tmp_path)
    assert result["note_count"] == 2
    assert ": 200 9 9 hi" in text
    assert ": 209 9 9 there" in text
    assert text.endswith("E\n")
    with pytest.raises(ValueError):
        validate_chart(text.replace("audio.mp3", "../audio.mp3"), tmp_path)


def test_empty_chart_fails():
    with pytest.raises(ValueError, match="No usable notes"):
        render_chart([], {"duration": 10})
