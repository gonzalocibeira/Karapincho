# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare fixed, documented fixture excerpts to the generated output.

This is a small lyric regression check, not a whole-song accuracy score. References
are used only here, after generation, and are never supplied to the application.
"""

import argparse
import json
import re
import unicodedata

from karapincho import config
from karapincho.media import read_json


def distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, left in enumerate(reference, 1):
        current = [i]
        for j, right in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def words(text):
    text = unicodedata.normalize("NFKC", text.lower()).replace("auld", "old")
    return re.findall(r"\w+", text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spanish-job", required=True)
    parser.add_argument("--japanese-job", required=True)
    parser.add_argument("--english-job", required=True)
    args = parser.parse_args()
    result = {}
    for language, job_id, reference, count in [
        (
            "es",
            args.spanish_job,
            "La cucaracha la cucaracha ya no puede caminar porque no tiene porque le falta la patita principal",
            1,
        ),
        (
            "en",
            args.english_job,
            "Should auld acquaintance be forgot and never brought to mind should auld acquaintance be forgot and days of auld lang syne",
            2,
        ),
    ]:
        transcript = read_json(config.DATA / "jobs" / job_id / "transcript.json")
        hypothesis = " ".join(s["text"] for s in transcript["segments"][:count])
        expected, actual = words(reference), words(hypothesis)
        errors = distance(expected, actual)
        result[language] = {
            "scope": "first chorus" if language == "es" else "first verse; auld/old normalized",
            "reference_words": len(expected),
            "word_errors": errors,
            "word_error_rate": errors / len(expected),
            "hypothesis": hypothesis,
        }
    units = read_json(config.DATA / "jobs" / args.japanese_job / "notes.json")["units"]
    hypothesis = "".join(u["text"] for u in units if u["phrase"] == units[0]["phrase"])
    expected = "sakurasakurayayoinosorawamiwatasukagiri"
    actual = re.sub(r"[^a-z]", "", hypothesis.lower())
    errors = distance(expected, actual)
    result["ja"] = {
        "scope": "first phrase through miwatasu kagiri; romaji spaces ignored",
        "reference_characters": len(expected),
        "character_errors": errors,
        "character_error_rate": errors / len(expected),
        "hypothesis": hypothesis,
    }
    output = config.ROOT / ".cache" / "lyric-excerpt-metrics.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
