# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixed-input local benchmark, scheduled by the song worker between songs."""
import hashlib
import json
import os
import platform
import signal
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import psutil

from . import acceleration, config
from .media import read_json, write_json

ASSETS = Path(__file__).parent / "benchmark_assets"
STAGES = ["prepare", "separate", "transcribe", "align", "pitch", "chart", "package"]
ACTIVE = {"queued", "running", "cancelling"}


def hardware():
    chip = platform.processor() or platform.machine()
    if sys.platform == "darwin":
        try:
            chip = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True, timeout=2).strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return {"chip": chip, "architecture": platform.machine(), "os": platform.platform(),
            "memory_gb": round(psutil.virtual_memory().total / 1024**3, 1)}


def baseline():
    return read_json(ASSETS / "baseline.json")


def compare(rows, mode):
    """Only publish comparison scores for complete three-run fixture sets."""
    result = []
    reference = "cpu" if mode == "cpu" else "gpu"
    for fixture in baseline()["fixtures"]:
        samples = [r for r in rows if r["language"] == fixture["language"]]
        if len(samples) != 3 or {r["run"] for r in samples} != {1, 2, 3}:
            continue
        seconds = statistics.median(r["elapsed_seconds"] for r in samples)
        if seconds <= 0:
            continue
        result.append({"language": fixture["language"], "seconds": seconds,
                       "ratio": fixture[reference]["seconds"] / seconds,
                       "stages": {stage: round(statistics.median(r["stages"][stage]["seconds"]
                                                                for r in samples), 2) for stage in STAGES}})
    total = None
    if len(result) == 3:
        total = sum(f[reference]["seconds"] for f in baseline()["fixtures"]) / sum(r["seconds"] for r in result)
    return {"fixtures": result, "ratio": total, "reference_mode": reference}


class Benchmarks:
    def __init__(self):
        self.root = config.DATA / "benchmarks"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "latest.json"
        self.lock = threading.RLock()
        self.process = None
        self.state = read_json(self.path) if self.path.exists() else {"status": "idle"}

    def recover(self):
        # Called only after the worker owns the application lock.
        if self.state["status"] in ACTIVE:
            self.state.update(status="interrupted", error="The app stopped. Start a fresh benchmark to compare complete runs.")
            self.save()

    def save(self):
        write_json(self.path, self.state)

    def snapshot(self):
        with self.lock:
            state = dict(self.state)
        if state.get("id"):
            folder = self.root / state["id"]
            progress = folder / "progress.json"
            rows = folder / "benchmark.json"
            state["progress"] = read_json(progress) if progress.exists() else {}
            state["rows"] = read_json(rows) if rows.exists() else []
            state["comparison"] = compare(state["rows"], state["mode"])
            database = folder / "jobs.sqlite3"
            job_id = state["progress"].get("job")
            if state["status"] in ACTIVE and job_id and database.exists():
                with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as db:
                    job = db.execute("SELECT stage FROM jobs WHERE id=?", (job_id,)).fetchone()
                if job:
                    state["progress"]["stage"] = job[0]
        return state

    def start(self, mode):
        if mode not in ("auto", "cpu"):
            raise ValueError("Choose automatic acceleration or CPU.")
        with self.lock:
            if self.state["status"] in ACTIVE:
                raise ValueError("A benchmark is already queued or running.")
            self.state = {"id": uuid.uuid4().hex, "status": "queued", "mode": mode, "created": time.time(),
                          "hardware": hardware(),
                          "baseline_id": baseline()["id"]}
            self.save()
        return self.snapshot()

    def cancel(self):
        with self.lock:
            if self.state["status"] not in ACTIVE:
                return self.snapshot()
            self.state["status"] = "cancelling" if self.process else "cancelled"
            if self.process and self.process.poll() is None:
                try:
                    self.process.terminate()  # Runner stops its active stage process group before exiting.
                except ProcessLookupError:
                    pass
            self.save()
        return self.snapshot()

    def run_pending(self, stopping):
        with self.lock:
            if self.state["status"] != "queued" or stopping.is_set():
                return False
            folder = self.root / self.state["id"]
            folder.mkdir()
            self.state.update(status="running", started=time.time())
            self.save()
            log = (folder / "runner.log").open("w")
            try:
                self.process = subprocess.Popen(
                    [sys.executable, "-m", "karapincho.benchmark", str(folder), self.state["mode"]],
                    cwd=config.ROOT, env={**os.environ, "KARAPINCHO_DATA": str(config.DATA)},
                    stdout=log, stderr=log, start_new_session=True,
                )
            except Exception as exc:
                log.close()
                self.state.update(status="failed", error=str(exc))
                self.save()
                return True
        try:
            while self.process.poll() is None:
                if stopping.wait(0.2):
                    self.cancel()
                    self.process.wait(timeout=8)
            with self.lock:
                cancelled = self.state["status"] == "cancelling" or stopping.is_set()
                status = "cancelled" if cancelled else "completed" if self.process.returncode == 0 else "failed"
                self.state.update(status=status, finished=time.time())
                if status == "failed":
                    error = folder / "error.json"
                    self.state["error"] = (read_json(error)["error"] if error.exists()
                                           else "Benchmark failed. See runner.log in the benchmark report folder.")
                self.save()
        except subprocess.TimeoutExpired:
            # Last resort for a stuck runner: reap only descendants of our own process.
            parent = psutil.Process(self.process.pid)
            children = parent.children(recursive=True)
            for child in reversed(children):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            self.process.kill()
            self.process.wait()
            with self.lock:
                self.state.update(status="cancelled", finished=time.time())
                self.save()
        finally:
            log.close()
            with self.lock:
                self.process = None
        return True


def run(folder, mode):
    """Runs in an isolated process; global config never changes in the web app."""
    from .store import Store
    from .worker import Worker

    cancelled = threading.Event()
    worker = None

    def stop(*_):
        cancelled.set()
        if worker:
            worker.stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    original = config.DATA
    config.initialize()
    config.DATA = folder
    config.initialize()
    (folder / "models").rmdir()
    (folder / "models").symlink_to(original / "models", target_is_directory=True)
    config.STAGES = STAGES
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", KARAPINCHO_ACCELERATION=mode)
    store = Store()
    base = baseline()
    for fixture in base["fixtures"]:
        source = ASSETS / f'{fixture["language"]}.mp4'
        if hashlib.sha256(source.read_bytes()).hexdigest() != fixture["sha256"]:
            raise ValueError("Benchmark sample has changed. Restore the bundled benchmark assets before comparing.")
    current = {s: acceleration.provenance(s) for s in base["provenance"]}
    # Mode affects selection, not the software comparison.
    expected = json.loads(json.dumps(base["provenance"]))
    for p in (current, expected):
        for value in p.values():
            value.pop("mode", None)
    rows = []
    for repeat in range(1, 4):
        for fixture in base["fixtures"]:
            if cancelled.is_set():
                return
            language = fixture["language"]
            job = store.create("file", "input.mp4", fixture["title"])
            job_folder = folder / "jobs" / job["id"]
            job_folder.mkdir()
            metadata = {k: fixture[k] for k in ("title", "artist", "duration")}
            metadata["input"] = str(ASSETS / f"{language}.mp4")
            write_json(job_folder / "acquire.json", {"metadata": metadata, "pipeline_version": 1})
            write_json(job_folder / "lyrics.json", {"lines": [], "source": "transcription"})
            write_json(job_folder / "lyrics-source.json", {"lines": [], "source": "transcription", "metadata": metadata})
            write_json(folder / "progress.json", {"run": repeat, "language": language, "title": fixture["title"],
                                                  "completed": len(rows), "total": 9, "job": job["id"],
                                                  "software_matches": current == expected})
            worker = Worker(store)
            if cancelled.is_set():
                return
            started = time.monotonic()
            try:
                worker.execute(job)
            finally:
                worker.terminate()
            if cancelled.is_set():
                return
            report = read_json(job_folder / "report.json")
            rows.append({"run": repeat, "language": language, "elapsed_seconds": round(time.monotonic()-started, 2),
                         "stages": {s: {"seconds": r["total_elapsed_seconds"], "runtime": r.get("runtime", {}),
                                        "attempts": r.get("attempts", []), "peak_rss_mb": r.get("peak_rss_mb")}
                                    for s, r in report.items()}})
            write_json(folder / "benchmark.json", rows)
    write_json(folder / "progress.json", {"completed": 9, "total": 9, "software_matches": current == expected})


if __name__ == "__main__":
    output = Path(sys.argv[1])
    try:
        run(output, sys.argv[2])
    except Exception as exc:
        write_json(output / "error.json", {"error": f"{exc} If a model is missing, run Setup.command before retrying."})
        raise
