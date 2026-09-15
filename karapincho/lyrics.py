# SPDX-License-Identifier: GPL-3.0-or-later
"""Conservative LRCLIB lookup and original-script lyric preparation."""
import hashlib
import json
import math
import re
import time
import unicodedata
from difflib import SequenceMatcher
from itertools import groupby
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, field_validator

from . import config
from .media import read_json, write_json


class LyricSettings(BaseModel):
    title: str = Field(default="", max_length=300)
    artist: str = Field(default="", max_length=300)
    language: str = Field(default="", pattern=r"^([a-z]{2,3})?$")
    lyrics: str = Field(default="", max_length=100000)

    @field_validator("title", "artist", "lyrics", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("lyrics")
    @classmethod
    def validate_lyrics(cls, value):
        if value:
            parse_lyrics(value)
        return value


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def parse_lyrics(text):
    """Return all lines, expanding repeat timestamps and applying the global LRC offset."""
    stamp = re.compile(r"\[(\d{1,3}):([0-5]\d(?:\.\d{1,3})?)\]")
    offsets = re.findall(r"\[offset:([+-]?\d+)\]", text, re.I)
    offset = int(offsets[-1]) / 1000 if offsets else 0
    lines, timed = [], False
    for raw in text.lstrip("\ufeff").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        times = list(stamp.finditer(raw))
        if times:
            timed = True
            wording = stamp.sub("", raw).strip()
            for match in times:
                start = int(match[1]) * 60 + float(match[2]) + offset
                lines.append({"text": wording, "start": max(0, start)})
        elif re.fullmatch(r"\[(?:ar|ti|al|by|length|re|ve|offset):.*\]", raw, re.I):
            continue
        elif raw.startswith("["):
            raise ValueError("Malformed LRC timestamp or unsupported lyric tag.")
        else:
            lines.append({"text": raw, "start": None})
    if not any(normalized(line["text"]) for line in lines):
        raise ValueError("Lyrics must contain sung text.")
    if timed and any(line["start"] is None for line in lines):
        raise ValueError("Use timestamps on every lyric line, or paste plain lyrics without timestamps.")
    if timed:
        merged = {}
        for line in sorted(lines, key=lambda line: line["start"]):
            if line["start"] in merged:
                merged[line["start"]]["text"] += " " + line["text"]
            else:
                merged[line["start"]] = dict(line)
        return list(merged.values())
    return lines


def request(endpoint, params):
    query = urlencode(params)
    key = hashlib.sha256(f"{endpoint}?{query}".encode()).hexdigest()
    cache = config.DATA / "lyrics-cache" / f"{key}.json"
    if cache.exists():
        try:
            saved = read_json(cache)
            if time.time() - saved["time"] < (86400 if saved["value"] is None else 30 * 86400):
                return saved["value"]
        except (ValueError, KeyError, OSError):
            pass
    req = Request(f"https://lrclib.net/api/{endpoint}?{query}", headers={
        "User-Agent": "Karapincho/0.1 (local karaoke studio)", "Accept": "application/json",
    })
    try:
        with urlopen(req, timeout=8) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("Lyrics response exceeded size limit")
            value = json.loads(raw)
    except HTTPError as exc:
        if exc.code != 404:
            raise
        value = None
    cache.parent.mkdir(parents=True, exist_ok=True)
    write_json(cache, {"time": time.time(), "value": value})
    return value


def matches(record, metadata):
    if not isinstance(record, dict) or record.get("instrumental"):
        return False
    try:
        duration = float(record["duration"])
        return (math.isfinite(duration) and abs(duration - metadata["duration"]) <= 2
                and normalized(record.get("trackName", "")) == normalized(metadata["title"])
                and normalized(record.get("artistName", "")) == normalized(metadata["artist"]))
    except (KeyError, TypeError, ValueError):
        return False


def lookup(folder):
    job = read_json(folder / "job.json")
    settings = job.get("lyric_settings") or {}
    metadata = {**read_json(folder / "prepare.json")["metadata"]}
    for key in ("title", "artist"):
        metadata[key] = settings.get(key) or metadata[key]
    result = {"source": "transcription", "lines": [], "warnings": [], "metadata": metadata,
              "language": settings.get("language", ""), "record_id": None}
    if settings.get("lyrics"):
        result.update(source="user", lines=parse_lyrics(settings["lyrics"]))
    elif metadata.get("artist") and metadata["artist"] != "Unknown Artist" and metadata.get("title"):
        try:
            params = {"track_name": metadata["title"], "artist_name": metadata["artist"],
                      "duration": metadata["duration"]}
            if metadata.get("album"):
                params["album_name"] = metadata["album"]
            exact = request("get", params)
            candidates = [exact] if matches(exact, metadata) else []
            if not candidates or not exact.get("syncedLyrics"):
                try:
                    found = request("search", {k: params[k] for k in ("track_name", "artist_name")})
                except (OSError, ValueError):
                    if not candidates:
                        raise
                    found = []
                    result["warnings"].append("Synced lyric search unavailable; using the exact plain lyric match.")
                if not isinstance(found, (list, type(None))):
                    raise ValueError("Invalid lyric search response")
                candidates += [r for r in (found or []) if matches(r, metadata)]
            # Deduplicate identical records, but never choose among different lyric versions.
            usable = {}
            for record in candidates:
                text = record.get("syncedLyrics") or record.get("plainLyrics")
                if text:
                    usable[text] = record
            synced = {t: r for t, r in usable.items() if r.get("syncedLyrics")}
            usable = synced or usable
            if len(usable) == 1:
                text, record = next(iter(usable.items()))
                result.update(source="lrclib", lines=parse_lyrics(text), record_id=record.get("id"))
            else:
                result["warnings"].append("No unambiguous LRCLIB match; using local transcription.")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            result["warnings"].append(f"LRCLIB unavailable or invalid ({type(exc).__name__}); using local transcription.")
    else:
        result["warnings"].append("Artist/title metadata is insufficient for lyric lookup; using local transcription.")
    write_json(folder / "lyrics-source.json", result)
    return result


def estimated_words(text, start, end):
    # Keep whitespace and script intact; Japanese mora processing happens after alignment.
    tokens = re.findall(r"\S+\s*", text)
    total = sum(len(t) for t in tokens) or 1
    words, cursor = [], start
    for token in tokens:
        stop = cursor + (end - start) * len(token) / total
        words.append({"word": token, "start": cursor, "end": stop, "score": 0})
        cursor = stop
    return words


def compose(source, reference, duration):
    """Locate original lyric lines using monotonically matched ASR character anchors."""
    lines = source["lines"]
    segments = reference.get("segments", [])
    chars, timings, languages = [], [], []
    for seg in segments:
        for word in seg["words"]:
            text = normalized(word["word"])
            for i, char in enumerate(text):
                chars.append(char)
                timings.append((word["start"] + (word["end"] - word["start"]) * i / len(text),
                                word["start"] + (word["end"] - word["start"]) * (i + 1) / len(text)))
                languages.append(seg["language"])
    target = "".join(normalized(line["text"]) for line in lines)
    mapping = {}
    for block in SequenceMatcher(None, target, "".join(chars), autojunk=False).get_matching_blocks():
        if block.size >= 3:
            mapping.update({block.a + i: block.b + i for i in range(block.size)})
    anchors, cursor = [], 0
    for line in lines:
        length = len(normalized(line["text"]))
        indices = [mapping[i] for i in range(cursor, cursor + length) if i in mapping]
        anchors.append(indices if len(indices) >= max(3, length * 0.6) else [])
        cursor += length
    timed = lines[0]["start"] is not None
    offsets = [timings[a[0]][0] - line["start"] for line, a in zip(lines, anchors) if a and timed]
    offset = sorted(offsets)[len(offsets) // 2] if len(offsets) >= 2 else 0
    if offsets and max(abs(x - offset) for x in offsets) > 3:
        offset = 0  # An edited recording needs local anchors, not a guessed global shift.
    warnings = []
    if not timed and not any(anchors):
        if source["source"] != "user":
            raise ValueError("Plain online lyrics have no reliable audio anchors")
        warnings.append("Supplied plain lyrics have no reliable audio anchors; timing is estimated.")
    if offset:
        warnings.append(f"Adjusted lyric timing by {offset:+.2f}s against the recording.")
    if timed:
        anchors = [a if a and abs(timings[a[0]][0] - (line["start"] + offset)) <= 3 else []
                   for line, a in zip(lines, anchors)]
    starts = [timings[a[0]][0] if a else (line["start"] + offset if timed else None)
              for line, a in zip(lines, anchors)]
    if timed and any(starts[i] >= starts[i + 1] for i in range(len(starts) - 1)):
        starts = [line["start"] + offset for line in lines]
        anchors = [[] for _ in lines]
    # Fill unanchored plain-text runs between known anchors, marking estimates explicitly.
    for i in range(len(starts)):
        if starts[i] is not None:
            continue
        left = next((j for j in range(i - 1, -1, -1) if starts[j] is not None), None)
        right = next((j for j in range(i + 1, len(starts)) if starts[j] is not None), len(starts))
        begin = starts[left] if left is not None else 0
        finish = starts[right] if right < len(starts) else duration
        base = left if left is not None else i
        for j in range(i, right):
            starts[j] = begin + (finish - begin) * (j - base) / (right - base)
    output = []
    for i, (line, anchor) in enumerate(zip(lines, anchors)):
        if not normalized(line["text"]):
            continue
        start = max(0, starts[i])
        end = min(duration, starts[i + 1] if i + 1 < len(starts) else duration)
        if anchor:
            end = min(end, timings[anchor[-1]][1] + 0.3)
        if end <= start:
            if source["source"] == "user":
                raise ValueError("Supplied lyric timestamps overlap or extend beyond this recording; correct the lyrics.")
            warnings.append("Skipped an online lyric line outside the recording.")
            continue
        text = line["text"]
        script_language = ("ja" if re.search(r"[\u3040-\u30ff]", text) else
                           "ko" if re.search(r"[\uac00-\ud7af]", text) else None)
        language = source.get("language") or script_language or (languages[anchor[0]] if anchor else None)
        if not language:
            language = segments[0]["language"] if segments else None
        if not language:
            raise ValueError("Choose a lyric language so supplied lyrics can be aligned.")
        fallback = [w for seg in segments for w in seg["words"]
                    if start <= (w["start"] + w["end"]) / 2 < end]
        output.append({"start": start, "end": end, "text": line["text"], "language": language,
                       "words": estimated_words(line["text"], start, end), "external": source["source"],
                       "timed_lyrics": timed, "anchored": bool(anchor), "fallback_words": fallback})
    if not output:
        raise ValueError("No supplied lyrics fit the recording.")
    if source["source"] == "lrclib":
        # Recover words in uncovered passages without replacing supplied wording inside a line.
        intervals = [(s["start"], s["end"]) for s in output]
        for seg in segments:
            for covered, group in groupby(seg["words"], key=lambda w: any(
                    w["start"] < end and w["end"] > start for start, end in intervals)):
                if covered:
                    continue
                uncovered = list(group)
                output.append({**seg, "words": uncovered, "text": "".join(w["word"] for w in uncovered),
                               "start": uncovered[0]["start"], "end": uncovered[-1]["end"]})
                warnings.append(f"Recovered an uncovered passage from transcription at {uncovered[0]['start']:.1f}s.")
        output.sort(key=lambda s: s["start"])
    output.sort(key=lambda s: s["start"])
    for i, seg in enumerate(output):
        previous_end = output[i - 1]["end"] if i else 0
        next_start = output[i + 1]["start"] if i + 1 < len(output) else duration
        seg["window_start"] = max(0, seg["start"] - 2, (previous_end + seg["start"]) / 2 if i else 0)
        seg["window_end"] = min(duration, seg["end"] + 2, (seg["end"] + next_start) / 2)
    source_label = source["source"]
    if source_label == "lrclib" and any(not s.get("external") for s in output):
        source_label = "lrclib+transcription"
    return {"segments": output, "warnings": warnings, "source": source_label,
            "record_id": source.get("record_id"), "matched_lines": sum(bool(a) for a in anchors),
            "total_lines": len(lines), "timing_offset": offset}
