# SPDX-License-Identifier: GPL-3.0-or-later
"""Download a frozen independent corpus. No model inference runs in this script."""

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from karapincho import config
from karapincho.media import read_json, write_json

SPEC = config.ROOT / "docs" / "accuracy" / "corpus.json"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url, path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        with urlopen(url, timeout=60) as response, temporary.open("wb") as target:
            shutil.copyfileobj(response, target)
        temporary.replace(path)
    return path


def prepare(root, archive=None):
    spec = read_json(SPEC)
    root.mkdir(parents=True, exist_ok=True)
    pjs = archive or fetch(spec["pjs_url"], root / "downloads" / "pjs.zip")
    if digest(pjs) != spec["pjs_sha256"]:
        raise ValueError("PJS archive does not match the frozen corpus checksum")
    sentences = fetch(spec["pjs_text_url"], root / "downloads" / "balance_sentences.txt")
    if digest(sentences) != spec["pjs_text_sha256"]:
        raise ValueError("Japanese reference text differs from the frozen source")
    japanese = {line.split()[0]: line.split()[1] for line in sentences.read_text().splitlines()[1:] if line.strip()}
    metadata = {}
    for language in ("en", "es"):
        base = f"https://huggingface.co/datasets/jamendolyrics/jam-alt/resolve/{spec['jam_revision']}/"
        path = fetch(base + f"subsets/{language}/metadata.jsonl", root / "downloads" / f"jam-{language}.jsonl")
        metadata[language] = {row["name"]: row for row in (json.loads(line) for line in path.read_text().splitlines())}
    records = []
    with zipfile.ZipFile(pjs) as source:
        for record in spec["records"]:
            name, language = record["name"], record["language"]
            if record["corpus"] == "pjs":
                # Extract exactly one known audio member, never arbitrary ZIP paths.
                audio = root / "audio" / f"{name}.wav"
                audio.parent.mkdir(exist_ok=True)
                if not audio.exists():
                    with source.open(f"PJS_corpus_ver1.1/{name}/{name}_song.wav") as entry, audio.open("wb") as target:
                        shutil.copyfileobj(entry, target)
                text, lines = japanese[name[3:]], []
            else:
                item = metadata[language][name]
                url = base + quote(f"subsets/{language}/{item['file_name']}", safe="/")
                audio = fetch(url, root / "audio" / f"{record['id']}.mp3")
                text, lines = item["text"], item["lines"]
            records.append({**record, "audio": str(audio.resolve()), "audio_sha256": digest(audio),
                            "reference_text": text, "reference_lines": lines})
            print(f"Prepared {record['id']} ({record['split']})", flush=True)
    result = {"schema": 1, "spec_sha256": digest(SPEC), "records": records}
    write_json(root / "manifest.json", result)
    print(root / "manifest.json", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=config.ROOT / ".cache" / "lyric-accuracy-corpus")
    parser.add_argument("--pjs-archive", type=Path)
    args = parser.parse_args()
    prepare(args.output.resolve(), args.pjs_archive)


if __name__ == "__main__":
    main()
