# SPDX-License-Identifier: GPL-3.0-or-later
import math
import re
import statistics
from itertools import groupby

from .media import read_json, write_json

TICKS_PER_SECOND = 20  # Classic UltraStar BPM 300 * 4 / 60.


def hz_to_pitch(hz):
    if not math.isfinite(hz) or hz <= 0:
        raise ValueError("Pitch frequency must be positive and finite")
    return round(69 + 12 * math.log2(hz / 440)) - 60


def ticks(seconds):
    return max(0, round(seconds * TICKS_PER_SECOND))


def clean_text(value):
    return re.sub(r"[\r\n\x00-\x1f]", " ", str(value)).strip()


def romanize_reading(reading, converter):
    # Expand katakana vowel extenders before conversion to avoid ASCII hyphens as vowels.
    pieces = converter.convert(reading)
    text = "".join(p["hepburn"] for p in pieces).lower()
    text = re.sub(r"([aeiou])[-ー]", r"\1\1", text)
    for vowel, replacement in (("ā", "aa"), ("ī", "ii"), ("ū", "uu"), ("ē", "ee"), ("ō", "ou")):
        text = text.replace(vowel, replacement)
    return text


def japanese_units(words):
    import fugashi
    import pykakasi

    tagger, converter = fugashi.Tagger(), pykakasi.kakasi()
    text, positions = "", []
    for word in words:
        surface = word["word"].strip()
        if not surface:
            continue
        if (
            text
            and text[-1].isascii()
            and text[-1].isalnum()
            and surface[0].isascii()
            and surface[0].isalnum()
        ):
            text += " "
            positions.append((word["start"], word["start"], word))
        for i, char in enumerate(surface):
            text += char
            positions.append(
                (
                    word["start"] + (word["end"] - word["start"]) * i / len(surface),
                    word["start"] + (word["end"] - word["start"]) * (i + 1) / len(surface),
                    word,
                )
            )
    units, cursor = [], 0
    for token in tagger(text):
        index = text.find(token.surface, cursor)
        if index < 0:
            continue
        end = index + len(token.surface)
        cursor = end
        if not re.search(r"[\w\u3040-\u30ff\u4e00-\u9fff]", token.surface):
            continue
        first, last = positions[index], positions[end - 1]
        original_latin = bool(re.fullmatch(r"[A-Za-z0-9'’-]+", token.surface))
        reading = getattr(token.feature, "pron", None) or getattr(token.feature, "kana", None)
        ambiguous = not original_latin and (
            not reading or reading == "*" or bool(re.search(r"[\u4e00-\u9fff]", token.surface))
        )
        romaji = (
            token.surface
            if original_latin
            else romanize_reading(reading if reading and reading != "*" else token.surface, converter)
        )
        if not romaji.isascii():
            romaji = "".join(p["hepburn"] for p in converter.convert(token.surface))
        # Mora-like romanized units retain consonant clusters; final n attaches to the prior vowel.
        parts = (
            [romaji]
            if original_latin
            else re.findall(r"[^aeiou]*[aeiou](?:n(?=[^aeiouy]|$))?|[^aeiou]+$", romaji)
        )
        parts = parts or [romaji]
        for i, part in enumerate(parts):
            units.append(
                {
                    "text": part + (" " if i == len(parts) - 1 else ""),
                    "start": first[0] + (last[1] - first[0]) * i / len(parts),
                    "end": first[0] + (last[1] - first[0]) * (i + 1) / len(parts),
                    "phrase": first[2]["phrase"],
                    "language": "ja",
                    "estimated": len(parts) > 1,
                    "reading_uncertain": ambiguous,
                }
            )
    return units


def lyric_units(words):
    import pyphen

    dictionaries = {"en": pyphen.Pyphen(lang="en_US"), "es": pyphen.Pyphen(lang="es")}
    result = []
    for (language, phrase), group in groupby(words, key=lambda w: (w["language"], w["phrase"])):
        group = list(group)
        if language == "ja":
            result.extend(japanese_units(group))
            continue
        for word in group:
            text = clean_text(word["word"])
            if not text:
                continue
            parts = dictionaries[language].inserted(text).split("-") if language in dictionaries else [text]
            parts = [part for part in parts if part] or [text]
            offset = 0
            chars = [c for c in word.get("chars", []) if c.get("char", "").strip()]
            precise = (
                len(chars) == len(text) and "".join(c["char"] for c in chars).casefold() == text.casefold()
            )
            for index, part in enumerate(parts):
                start = (
                    chars[offset]["start"]
                    if precise
                    else word["start"] + (word["end"] - word["start"]) * offset / len(text)
                )
                offset += len(part)
                end = (
                    chars[min(offset - 1, len(chars) - 1)]["end"]
                    if precise
                    else word["start"] + (word["end"] - word["start"]) * offset / len(text)
                )
                result.append(
                    {
                        "text": part + (" " if index == len(parts) - 1 else ""),
                        "start": start,
                        "end": end,
                        "language": language,
                        "phrase": phrase,
                        "estimated": word.get("estimated", False) or (len(parts) > 1 and not precise),
                    }
                )
    return result


def make_notes(units, track, duration):
    import numpy as np

    times, hz, confidence, energy = (np.asarray(track[k]) for k in ("time", "hz", "confidence", "energy"))
    notes, warnings = [], []
    for unit in units:
        start, end = max(0, unit["start"]), min(duration, unit["end"])
        if end <= start:
            continue
        selected = (times >= start) & (times < end)
        # Refine estimated boundaries toward nearby low-energy transitions, retaining word containment.
        if unit.get("estimated"):
            for which in ("start", "end"):
                boundary = start if which == "start" else end
                nearby = np.flatnonzero((abs(times - boundary) < min(0.06, (end - start) / 4)))
                if len(nearby):
                    candidate = float(times[nearby[np.argmin(energy[nearby])]])
                    if which == "start":
                        start = max(0, candidate)
                    else:
                        end = min(duration, candidate)
            selected = (times >= start) & (times < end)
        indexes = np.flatnonzero(selected & (confidence >= 0.35) & (energy > 0.001) & (hz > 0))
        ratio = len(indexes) / max(1, int(selected.sum()))
        if ratio < 0.3 or not len(indexes):
            notes.append(
                {
                    "start": start,
                    "end": end,
                    "pitch": 0,
                    "type": "F",
                    "text": unit["text"],
                    "phrase": unit["phrase"],
                    "confidence": 0,
                }
            )
            continue
        pitches = [hz_to_pitch(float(hz[i])) for i in indexes]
        # Median smoothing removes brief vibrato and octave spikes without forcing a musical key.
        smoothed = [round(statistics.median(pitches[max(0, i - 2) : i + 3])) for i in range(len(pitches))]
        runs = []
        for value, group in groupby(enumerate(smoothed), key=lambda x: x[1]):
            positions = [i for i, _ in group]
            if len(positions) >= 8:
                runs.append((float(times[indexes[positions[0]]]), value))
        if not runs:
            runs = [(start, round(statistics.median(pitches)))]
        runs[0] = (start, runs[0][1])
        for i, (begin, value) in enumerate(runs):
            finish = runs[i + 1][0] if i + 1 < len(runs) else end
            if finish <= begin:
                continue
            text = unit["text"].rstrip() if i == 0 else "~"
            if i == len(runs) - 1 and unit["text"].endswith(" "):
                text += " "
            notes.append(
                {
                    "start": begin,
                    "end": finish,
                    "pitch": value,
                    "type": ":",
                    "text": text,
                    "phrase": unit["phrase"],
                    "confidence": float(confidence[indexes].mean()),
                }
            )
    if any(u.get("estimated") for u in units):
        warnings.append(
            "Some syllable boundaries are acoustically refined estimates, especially sustained or rapid vocals."
        )
    if any(u.get("reading_uncertain") for u in units):
        warnings.append(
            "Japanese kanji readings were inferred automatically; names and unusual sung readings may differ."
        )
    if any(n["type"] == "F" for n in notes):
        warnings.append("Uncertain melody passages are freestyle notes and do not require an exact pitch.")
    return notes, warnings


def render_chart(notes, metadata):
    ordered, last_end = [], 0
    for note in sorted(notes, key=lambda n: n["start"]):
        begin, end = max(last_end, ticks(note["start"])), ticks(note["end"])
        if end <= begin:
            # Preserve fast syllables with one tick if there is room before the audio ends.
            end = begin + 1
        if end > ticks(metadata["duration"]):
            continue
        ordered.append({**note, "beat": begin, "length": end - begin})
        last_end = end
    if not ordered:
        raise ValueError("No usable notes could be generated from this recording.")
    lines = [
        f"#TITLE:{clean_text(metadata['title'])}",
        f"#ARTIST:{clean_text(metadata['artist'])}",
        "#MP3:audio.mp3",
        "#VIDEO:video.mp4",
        "#COVER:cover.jpg",
        "#BPM:300",
        "#GAP:0",
        "#VIDEOGAP:0",
        "#ENCODING:UTF8",
        "#CREATOR:Karapincho",
    ]
    count, previous = 0, None
    for note in ordered:
        if previous is not None and (
            note["phrase"] != previous["phrase"]
            or count >= 42
            or note["beat"] - previous["beat"] - previous["length"] >= 20
        ):
            lines.append(f"- {previous['beat'] + previous['length']}")
            count = 0
        text = note["text"].replace("\n", " ").replace("\r", " ")
        lines.append(f"{note['type']} {note['beat']} {note['length']} {note['pitch']} {text}")
        count += len(text)
        previous = note
    lines.append("E")
    return "\n".join(lines) + "\n"


def validate_chart(text, folder=None):
    headers, previous_end, total, ended = {}, 0, 0, False
    for line in text.splitlines():
        if ended:
            raise ValueError("Unexpected data after end marker")
        if line.startswith("#"):
            name, value = line[1:].split(":", 1)
            headers[name] = value
        elif line == "E":
            ended = True
        elif line.startswith((": ", "F ")):
            kind, start, length, pitch, lyric = line.split(" ", 4)
            start, length, pitch = int(start), int(length), int(pitch)
            if start < previous_end or length <= 0 or not lyric.strip():
                raise ValueError("Invalid or overlapping note")
            previous_end = start + length
            total += 1
        elif line.startswith("- "):
            if int(line[2:]) < previous_end:
                raise ValueError("Phrase break precedes previous note end")
        else:
            raise ValueError(f"Unexpected chart line: {line}")
    if not ended or not total or not all(headers.get(k) for k in ("TITLE", "ARTIST", "MP3", "BPM")):
        raise ValueError("Incomplete UltraStar chart")
    if headers.get("BPM") != "300" or headers.get("GAP") != "0":
        raise ValueError("Unexpected timing grid")
    for key in ("MP3", "VIDEO", "COVER"):
        value = headers.get(key, "")
        if not value or "/" in value or "\\" in value or value in (".", ".."):
            raise ValueError("Unsafe media reference")
        if folder is not None and not (folder / value).is_file():
            raise ValueError(f"Missing {key} file")
    return {"note_count": total, "end_seconds": previous_end / TICKS_PER_SECOND}


def create_chart(folder):
    import numpy as np

    aligned, metadata = read_json(folder / "aligned.json"), read_json(folder / "prepare.json")["metadata"]
    if (folder / "lyrics-source.json").exists():
        metadata = read_json(folder / "lyrics-source.json")["metadata"]
    units = lyric_units(aligned["words"])
    with np.load(folder / "pitch.npz") as track:
        notes, warnings = make_notes(units, track, metadata["duration"])
    text = render_chart(notes, metadata)
    details = validate_chart(text)
    (folder / "song.txt").write_text(text, encoding="utf-8")
    write_json(folder / "notes.json", {"units": units, "notes": notes, **details})
    return {"warnings": warnings, **details}
