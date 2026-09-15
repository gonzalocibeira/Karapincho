# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated pipeline stage executable: python -m karapincho.stage STAGE JOB_DIR."""

import argparse
from dataclasses import asdict
import os
import tempfile
import importlib.metadata
import resource
import shutil
import sys
import time
import traceback
import zipfile

from . import acceleration, config
from .export import download_name
from .media import acquire, prepare, read_json, write_json


def package(folder):
    from .chart import validate_chart

    destination = config.DATA / "library" / folder.name
    temporary = config.DATA / "library" / (folder.name + ".partial")
    temporary.mkdir(parents=True, exist_ok=True)
    for name in ("song.txt", "audio.mp3", "video.mp4", "cover.jpg"):
        shutil.copyfile(folder / name, temporary / name)
    validate_chart((temporary / "song.txt").read_text(encoding="utf-8"), temporary)
    archive = folder / "song.zip.partial"
    archive_folder = download_name(temporary)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as output:
        for name in ("song.txt", "audio.mp3", "video.mp4", "cover.jpg"):
            output.write(temporary / name, f"{archive_folder}/{name}")
    # Build and validate everything before replacing either previous export.
    backup = destination.with_name(destination.name + ".previous")
    if backup.exists():
        if not destination.exists():
            backup.replace(destination)
        else:
            shutil.rmtree(backup)
    had_previous = destination.exists()
    if had_previous:
        destination.replace(backup)
    try:
        temporary.replace(destination)
        archive.replace(folder / "song.zip")
    except BaseException:
        if destination.exists():
            shutil.rmtree(destination)
        if had_previous and backup.exists():
            backup.replace(destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)
    return {"warnings": [], "folder": str(destination)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=config.STAGES)
    parser.add_argument("folder", type=__import__("pathlib").Path)
    parser.add_argument("--low-memory", action="store_true")
    parser.add_argument("--backend", choices=("cpu", "mps", "mlx", "videotoolbox"))
    parser.add_argument("--reduced", action="store_true")
    args = parser.parse_args()
    config.initialize()
    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "0"
    start = time.monotonic()
    original_folder = args.folder.resolve()
    scratch = None
    try:
        # An already-running pre-upgrade worker cannot handle GPU recovery requests.
        # Keep its children on CPU until the app is restarted with the new worker.
        legacy_worker = args.backend is None and os.environ.get("KARAPINCHO_WORKER_PROTOCOL") != "gpu-v1"
        backend = "cpu" if legacy_worker else args.backend
        runtime = acceleration.configure(args.stage, args.reduced or args.low_memory, backend)
        if legacy_worker and os.environ.get("KARAPINCHO_ACCELERATION", "auto") == "auto":
            runtime.reason = "Restart the app to enable automatic acceleration with the upgraded worker"
        write_json(original_folder / "stage-runtime.json", asdict(runtime))
        if args.stage in acceleration.AI_STAGES | {"prepare"}:
            from .worker import OUTPUTS
            scratch = tempfile.TemporaryDirectory(prefix=".attempt-", dir=original_folder)
            args.folder = __import__("pathlib").Path(scratch.name)
            excluded = set(OUTPUTS[args.stage]) | {f"{args.stage}.json", "stage-error.json"}
            if args.stage == "transcribe":
                excluded.add("asr-reference.json")
            for source in original_folder.iterdir():
                if source.is_file() and source.name not in excluded:
                    (args.folder / source.name).symlink_to(source)
        if args.stage == "acquire":
            result = {"metadata": acquire(read_json(args.folder / "job.json"), args.folder), "warnings": []}
        elif args.stage == "prepare":
            result = {
                "metadata": prepare(read_json(args.folder / "acquire.json")["metadata"], args.folder),
                "warnings": [],
            }
        elif args.stage == "lyrics":
            from .lyrics import lookup

            result = lookup(args.folder)
        elif args.stage in ("separate", "transcribe", "align", "pitch"):
            from . import ai

            result = getattr(ai, args.stage)(args.folder, args.low_memory)
        elif args.stage == "chart":
            from .chart import create_chart

            result = create_chart(args.folder)
        else:
            result = package(args.folder)
        result["runtime"] = runtime.report()
        result["provenance"] = acceleration.provenance(args.stage)
        if scratch:
            for output in args.folder.iterdir():
                if output.is_file() and not output.is_symlink():
                    os.replace(output, original_folder / output.name)
        result["elapsed_seconds"] = round(time.monotonic() - start, 2)
        memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result["peak_rss_mb"] = round(memory / (1024**2 if sys.platform == "darwin" else 1024), 1)
        result["pipeline_version"] = 1
        result["versions"] = {}
        for name in ("whisperx", "faster-whisper", "torch", "demucs", "torchcrepe", "yt-dlp", "mlx", "mlx-whisper"):
            try:
                result["versions"][name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                pass
        write_json(original_folder / f"{args.stage}.json", result)
    except Exception as exc:
        write_json(original_folder / "stage-error.json", {"message": str(exc), "type": type(exc).__name__,
                   "backend": acceleration.CURRENT.backend,
                   "runtime": asdict(acceleration.CURRENT),
                   "kind": acceleration.failure_kind(f"{type(exc).__name__}: {exc}", acceleration.CURRENT.backend),
                   "elapsed_seconds": round(time.monotonic() - start, 2)})
        traceback.print_exc()
        sys.exit(1)
    finally:
        if scratch:
            scratch.cleanup()


if __name__ == "__main__":
    main()
