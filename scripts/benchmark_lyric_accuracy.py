# SPDX-License-Identifier: GPL-3.0-or-later
"""Run frozen lyric accuracy inputs locally, then score withheld reference lyrics.

Audio preparation and separation are shared across profiles. Reference text is
never placed in job folders, prompts, or metadata visible to inference stages.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from karapincho import config
from karapincho.lyric_accuracy import corpus_fingerprint, errors, file_digest as digest, summarize, timing, units
from karapincho.media import inspect_media, read_json, run, write_json
from karapincho.store import Store
from karapincho.worker import Worker

SPEC = config.ROOT / "docs" / "accuracy" / "corpus.json"


def prepare_audio(record, root, model_root):
    folder = root / record["audio_sha256"]
    folder.mkdir(parents=True, exist_ok=True)
    audio = Path(record["audio"])
    if digest(audio) != record["audio_sha256"]:
        raise ValueError("Evaluation input audio changed")
    if (folder / "separate.json").exists() and (folder / "vocals.wav").exists():
        return folder
    source = folder / "input.mp4"
    if not source.exists():
        run([config.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=1",
             "-i", audio, "-shortest", "-c:v", "libx264", "-c:a", "aac", source])
    write_json(folder / "acquire.json", {"metadata": {"input": str(source), "title": record["id"],
                                                      "artist": "Accuracy fixture",
                                                      "duration": inspect_media(source)["duration"]}})
    env = {**os.environ, "KARAPINCHO_DATA": str(model_root), "KARAPINCHO_WORKER_PROTOCOL": "gpu-v1",
           "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    # Each command owns its process group; interruption always reaps its descendants.
    for stage in ("prepare", "separate"):
        with (folder / f"{stage}.log").open("w") as log:
            child = subprocess.Popen([sys.executable, "-m", "karapincho.stage", stage, str(folder)],
                                     env=env, stdout=log, stderr=log, start_new_session=True)
            try:
                if child.wait() != 0:
                    raise RuntimeError(f"Fixture {stage} failed; inspect {folder / (stage + '.log')}")
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
    return folder


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=config.ROOT / ".cache/lyric-accuracy-corpus/manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("legacy", "quality-v2"), required=True)
    parser.add_argument("--split", choices=("tuning", "evaluation"), default="evaluation")
    parser.add_argument("--ids", nargs="+", help="Subset smoke only; cannot satisfy the release gate")
    parser.add_argument("--reduced", action="store_true",
                        help="Evaluate 8-bit Qwen on this Mac; does not validate 8 GB hardware")
    args = parser.parse_args()
    if args.reduced and args.profile != "quality-v2":
        parser.error("--reduced is for quality-v2 model evaluation")
    args.corpus = args.corpus.resolve()
    if args.output.exists():
        parser.error("Use a fresh output directory")
    corpus = read_json(args.corpus)
    if corpus["spec_sha256"] != digest(SPEC):
        parser.error("Prepared corpus no longer matches the frozen specification")
    all_records = [r for r in corpus["records"] if r["split"] == args.split]
    records = [r for r in all_records if not args.ids or r["id"] in args.ids]
    if not records or (args.ids and set(args.ids) != {r["id"] for r in records}):
        parser.error("Select existing recording IDs in the requested split")
    original_data = config.DATA
    config.initialize()
    config.DATA = args.output.resolve()
    config.initialize()
    (config.DATA / "models").rmdir()
    (config.DATA / "models").symlink_to(original_data / "models", target_is_directory=True)
    config.STAGES = ["transcribe", "align"]
    os.environ.update(KARAPINCHO_TRANSCRIPTION=args.profile, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    store = Store()
    worker = Worker(store, reduced_stages={"transcribe"} if args.reduced else ())
    def stop(*_):
        worker.stopping.set()
        worker.terminate()
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    result = {"schema": 1, "profile": args.profile, "split": args.split, "complete": False,
              "requested_precision": "8bit" if args.reduced else "auto",
              "corpus_sha256": corpus_fingerprint(corpus),
              "evaluation_ids": [r["id"] for r in corpus["records"] if r["split"] == "evaluation"],
              "rows": []}
    try:
        for record in records:
            print(f"START {args.profile} {record['id']}", flush=True)
            analysis = prepare_audio(record, args.corpus.parent / "analysis", original_data)
            job = store.create("file", "input.mp4", record["id"], processing_mode="quality",
                               lyric_settings={"language": record["language"]})
            folder = config.DATA / "jobs" / job["id"]
            folder.mkdir()
            for name in ("original.wav", "vocals.wav", "separate.json"):
                (folder / name).symlink_to(analysis / name)
            write_json(folder / "lyrics.json", {"source": "transcription"})
            write_json(folder / "lyrics-source.json", {"source": "transcription", "lines": []})
            started = time.monotonic()
            worker.execute(job)
            transcript, aligned = read_json(folder / "transcript.json"), read_json(folder / "aligned.json")
            hypothesis = " ".join(s["text"] for s in transcript["segments"])
            # This is the first point at which a reference is used. Inference has exited.
            metrics = errors(units(record["reference_text"], record["language"]), units(hypothesis, record["language"]))
            row = {"id": record["id"], "language": record["language"], "job": job["id"], "metrics": metrics,
                   "timing": timing(record["reference_lines"], aligned["words"], record["language"]),
                   "elapsed_seconds": round(time.monotonic() - started, 2),
                   "warnings": store.get(job["id"])["warnings"], "report": read_json(folder / "report.json")}
            result["rows"].append(row)
            result["summary"] = summarize(result["rows"])
            write_json(config.DATA / "accuracy.json", result)
            print(f"DONE {record['id']}: error={metrics['error_rate']:.3f}", flush=True)
        result["complete"] = len(result["rows"]) == len(all_records)
        write_json(config.DATA / "accuracy.json", result)
    finally:
        worker.terminate()
    print(json.dumps(result["summary"], indent=2), flush=True)


if __name__ == "__main__":
    main()
