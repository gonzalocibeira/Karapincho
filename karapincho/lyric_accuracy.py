# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent lyric evaluation. Never imported by recognition or alignment."""

import math
import hashlib
import json
import re
import unicodedata
from difflib import SequenceMatcher


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def corpus_fingerprint(corpus):
    """Identify the same frozen audio/references independently of cache location."""
    payload = {"spec_sha256": corpus["spec_sha256"], "records": [
        {k: v for k, v in record.items() if k != "audio"}
        for record in sorted(corpus["records"], key=lambda r: r["id"])]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def units(text, language):
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    if language == "ja":
        return [c for c in text if c.isalnum()]
    return re.findall(r"[^\W_]+(?:'[^\W_]+)*", text, re.UNICODE)


def errors(reference, hypothesis):
    """Minimum edit path with reproducible substitution/deletion/insertion counts."""
    previous = [(j, 0, 0, j) for j in range(len(hypothesis) + 1)]
    for i, expected in enumerate(reference, 1):
        current = [(i, 0, i, 0)]
        for j, actual in enumerate(hypothesis, 1):
            if expected == actual:
                current.append(previous[j - 1])
            else:
                n, s, d, a = previous[j - 1]
                substitutions = (n + 1, s + 1, d, a)
                n, s, d, a = previous[j]
                deletions = (n + 1, s, d + 1, a)
                n, s, d, a = current[j - 1]
                insertions = (n + 1, s, d, a + 1)
                current.append(min((substitutions, deletions, insertions), key=lambda v: v[0]))
        previous = current
    count, substitutions, deletions, insertions = previous[-1]
    return {"errors": count, "substitutions": substitutions, "deletions": deletions, "insertions": insertions,
            "reference_units": len(reference), "error_rate": count / len(reference) if reference else None}


def timing(reference_lines, predicted_words, language):
    """Boundary error only for exact matched units; always report reference coverage.

    Jam-ALT provides line times, not word times. Unmatched lines stay in the
    coverage denominator so deleting lyrics cannot masquerade as better timing.
    """
    expected, ranges = [], []
    for line in reference_lines:
        first = len(expected)
        expected.extend(units(line["text"], language))
        ranges.append((first, len(expected)))
    actual, bounds = [], []
    for word in predicted_words:
        tokens = units(word["word"], language)
        actual.extend(tokens)
        bounds.extend([(word["start"], word["end"])] * len(tokens))
    mapping = {}
    for block in SequenceMatcher(None, expected, actual, autojunk=False).get_matching_blocks():
        mapping.update({block.a + i: block.b + i for i in range(block.size)})
    differences = []
    matched = 0
    for line, (first, last) in zip(reference_lines, ranges):
        if first == last or any(i not in mapping for i in range(first, last)):
            continue
        matched += 1
        differences.extend([abs(bounds[mapping[first]][0] - line["start"]),
                            abs(bounds[mapping[last - 1]][1] - line["end"])])
    differences.sort()
    return {"annotation_level": "line", "reference_lines": len(reference_lines), "matched_lines": matched,
            "coverage": matched / len(reference_lines) if reference_lines else None,
            "median_boundary_error_seconds": differences[len(differences)//2] if differences else None,
            "p95_boundary_error_seconds": differences[math.ceil(len(differences)*.95)-1] if differences else None}


def summarize(rows):
    by_language = {}
    for language in ("en", "es", "ja"):
        samples = [r for r in rows if r["language"] == language]
        if not samples:
            continue
        counts = {key: sum(r["metrics"][key] for r in samples)
                  for key in ("errors", "substitutions", "deletions", "insertions", "reference_units")}
        by_language[language] = {**counts, "songs": len(samples), "error_rate": counts["errors"] / max(
            1, counts["reference_units"])}
    return {"languages": by_language, "balanced_error_rate": sum(
        v["error_rate"] for v in by_language.values()) / len(by_language) if by_language else None}


def release_gate(before, after):
    """Incomplete/tuning/different-corpus runs can never authorize promotion."""
    reasons = []
    if any(r.get("split") != "evaluation" or not r.get("complete") for r in (before, after)):
        reasons.append("Both runs must cover the complete frozen evaluation split.")
    if before.get("profile") != "legacy" or after.get("profile") != "quality-v2":
        reasons.append("Compare legacy Quality against quality-v2.")
    if not before.get("corpus_sha256") or before.get("corpus_sha256") != after.get("corpus_sha256"):
        reasons.append("Corpus manifests differ or are not fingerprinted.")
    if {r["id"] for r in before["rows"]} != {r["id"] for r in after["rows"]}:
        reasons.append("Recording sets differ.")
    for run in (before, after):
        ids = [r["id"] for r in run["rows"]]
        if not run.get("evaluation_ids") or set(ids) != set(run["evaluation_ids"]) or len(ids) != len(set(ids)):
            reasons.append("Run does not contain each frozen evaluation recording exactly once.")
    original_records = {r["id"]: (r["language"], r["metrics"]["reference_units"]) for r in before["rows"]}
    updated_records = {r["id"]: (r["language"], r["metrics"]["reference_units"]) for r in after["rows"]}
    if original_records != updated_records:
        reasons.append("Reference counts or recording languages differ.")
    a, b = summarize(before["rows"]), summarize(after["rows"])
    if set(a["languages"]) != {"en", "es", "ja"} or set(b["languages"]) != {"en", "es", "ja"}:
        reasons.append("All three priority languages are required.")
    improvement = None
    if a["balanced_error_rate"] and b["balanced_error_rate"] is not None:
        improvement = 1 - b["balanced_error_rate"] / a["balanced_error_rate"]
    if improvement is None or improvement < .30:
        reasons.append("Language-balanced error reduction is below 30%.")
    for language, original in a["languages"].items():
        updated = b["languages"].get(language)
        if updated and updated["error_rate"] > original["error_rate"]:
            reasons.append(f"{language} error rate regressed.")
    old_deletions = sum(v["deletions"] for v in a["languages"].values())
    new_deletions = sum(v["deletions"] for v in b["languages"].values())
    if new_deletions >= old_deletions:
        reasons.append("Omitted lyric units did not decrease.")
    if sum(v["insertions"] for v in b["languages"].values()) > sum(v["insertions"] for v in a["languages"].values()):
        reasons.append("Inserted lyric units increased.")
    return {"passed": not reasons, "relative_error_reduction": improvement, "reasons": reasons,
            "before": a, "after": b}
