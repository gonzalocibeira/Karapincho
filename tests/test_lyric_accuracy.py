# SPDX-License-Identifier: GPL-3.0-or-later
import copy

from karapincho.lyric_accuracy import corpus_fingerprint, errors, release_gate, timing, units


def test_edit_counts_distinguish_wrong_missing_and_inserted_lyrics():
    result = errors(["one", "two", "three", "four"], ["one", "wrong", "four", "extra"])
    assert result["errors"] == 3
    assert sum(result[k] for k in ("substitutions", "deletions", "insertions")) == 3
    assert errors(["hola", "mundo"], ["hola"])["deletions"] == 1
    assert errors(["hola"], ["hola", "mundo"])["insertions"] == 1
    assert errors([], ["hallucination"])["error_rate"] is None


def test_metrics_preserve_accents_and_japanese_script_without_romaji():
    assert units("¡Óyeme! Don't, don’t", "es") == ["óyeme", "don't", "don't"]
    assert units("桜、さくら。", "ja") == list("桜さくら")
    assert units("auld", "en") != units("old", "en")


def report(error=50, deletions=30, insertions=10, profile="quality-v2"):
    rows = [{"id": language, "language": language, "metrics": {
        "errors": error, "deletions": deletions, "insertions": insertions,
        "substitutions": error - deletions - insertions, "reference_units": 100}}
        for language in ("en", "es", "ja")]
    return {"profile": profile, "split": "evaluation", "complete": True, "corpus_sha256": "frozen",
            "evaluation_ids": [r["id"] for r in rows], "rows": rows}


def test_release_gate_requires_real_improvement_in_all_languages():
    before = report(profile="legacy")
    after = report(20, 10, 5)
    assert release_gate(before, after)["passed"]
    after["rows"][2]["metrics"]["errors"] = 51
    assert "ja error rate regressed." in release_gate(before, after)["reasons"]


def test_tuning_partial_changed_corpus_and_increased_insertions_cannot_pass_gate():
    before, valid = report(profile="legacy"), report(20, 10, 5)
    for key, value in (("split", "tuning"), ("complete", False), ("corpus_sha256", "different")):
        after = copy.deepcopy(valid)
        after[key] = value
        assert not release_gate(before, after)["passed"]
    after = report(30, 10, 11)
    assert "Inserted lyric units increased." in release_gate(before, after)["reasons"]
    after = report(20, 10, 5)
    after["rows"].pop()
    assert not release_gate(before, after)["passed"]


def test_gate_rejects_duplicate_recordings_and_wrong_profiles():
    before, after = report(profile="legacy"), report(20, 10, 5)
    after["rows"].append(after["rows"][0])
    assert not release_gate(before, after)["passed"]
    after = report(20, 10, 5, "legacy")
    assert not release_gate(before, after)["passed"]


def test_corpus_fingerprint_tracks_references_and_audio_hashes_not_cache_path():
    corpus = {"spec_sha256": "frozen", "records": [
        {"id": "one", "audio": "/first/path.wav", "audio_sha256": "audio", "reference_text": "hola"}]}
    before = corpus_fingerprint(corpus)
    corpus["records"][0]["audio"] = "/another/path.wav"
    assert corpus_fingerprint(corpus) == before
    corpus["records"][0]["reference_text"] = "mundo"
    assert corpus_fingerprint(corpus) != before


def test_timing_reports_coverage_when_missing_lines_cannot_be_measured():
    reference = [{"text": "hello world", "start": 1, "end": 2},
                 {"text": "missing lyrics", "start": 3, "end": 4}]
    words = [{"word": "hello", "start": 1.1, "end": 1.5},
             {"word": "world", "start": 1.5, "end": 2.1}]
    result = timing(reference, words, "en")
    assert result["coverage"] == .5
    assert result["annotation_level"] == "line"
    assert abs(result["p95_boundary_error_seconds"] - .1) < .001


def test_frozen_corpus_has_disjoint_splits_and_three_languages():
    from karapincho import config
    from karapincho.media import read_json
    spec = read_json(config.ROOT / "docs/accuracy/corpus.json")
    tuning = {r["id"] for r in spec["records"] if r["split"] == "tuning"}
    evaluation = {r["id"] for r in spec["records"] if r["split"] == "evaluation"}
    assert tuning and evaluation and not tuning & evaluation
    assert {r["language"] for r in spec["records"] if r["split"] == "evaluation"} == {"en", "es", "ja"}
    assert len(spec["jam_revision"]) == 40 and len(spec["pjs_sha256"]) == 64
