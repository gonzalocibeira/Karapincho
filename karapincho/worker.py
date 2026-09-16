# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
import fcntl
import os
import signal
import shutil
import subprocess
import sys
import threading
import time

from . import acceleration, config
from .media import read_json, write_json
from .power import keep_awake

OUTPUTS = {
    "acquire": [],
    "prepare": ["original.wav", "audio.mp3", "video.mp4", "cover.jpg"],
    "lyrics": ["lyrics-source.json"],
    "separate": ["vocals.wav"],
    "transcribe": ["transcript.json"],
    "align": ["aligned.json"],
    "pitch": ["pitch.npz"],
    "chart": ["song.txt", "notes.json"],
    "package": ["song.zip"],
}


DEPENDENCIES = {
    "acquire": [], "prepare": ["acquire"], "lyrics": ["prepare"], "separate": ["prepare"],
    "transcribe": ["separate", "lyrics"], "align": ["transcribe"], "pitch": ["separate"],
    "chart": ["align", "pitch", "lyrics"], "package": ["chart", "prepare"],
}


def signature(stage, folder, job):
    payload = {"revision": 2 if stage in ("lyrics", "transcribe", "align", "chart", "package") else 1,
               "dependencies": {name: hashlib.sha256((folder / f"{name}.json").read_bytes()).hexdigest()
                                for name in DEPENDENCIES[stage]}}
    if stage in acceleration.AI_STAGES | {"prepare"}:
        payload["acceleration"] = acceleration.provenance(stage)
    if stage == "transcribe" and job.get("processing_mode", "quality") == "fast":
        payload["processing"] = {"mode": "fast", "model": "small", "beam_size": 1}
    if stage == "lyrics":
        payload["settings"] = job.get("lyric_settings", {})
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def cleanup_attempts(folder):
    for abandoned in folder.glob(".attempt-*"):
        if abandoned.is_dir() and not abandoned.is_symlink():
            shutil.rmtree(abandoned)


class Worker:
    def __init__(self, store, backend_overrides=None):
        self.store = store
        self.backend_overrides = backend_overrides or {}
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True, name="song-worker")
        self.process = None
        self.lock = None
        self.benchmarks = None

    def start(self):
        self.lock = (config.DATA / "worker.lock").open("w")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("Karapincho is already running with this data folder.") from None
        self.store.recover()
        if self.benchmarks:
            self.benchmarks.recover()
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.benchmarks:
            self.benchmarks.cancel()
        self.thread.join(timeout=10)
        if self.lock:
            self.lock.close()

    def terminate(self):
        if self.process and self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
            except ProcessLookupError:
                pass

    def loop(self):
        while not self.stopping.is_set():
            if self.benchmarks and self.benchmarks.run_pending(self.stopping):
                continue
            job = self.store.next()
            if job is None:
                self.stopping.wait(0.5)
                continue
            try:
                self.execute(job)
            except Exception as exc:
                self.store.update(job["id"], status="failed", error=str(exc)[-2000:])

    @keep_awake()
    def execute(self, job):
        folder = config.DATA / "jobs" / job["id"]
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "job.json", job)
        warnings = []
        regenerated = set()
        for index, stage in enumerate(config.STAGES):
            current = self.store.get(job["id"])
            if self.stopping.is_set() or current["cancel_requested"]:
                self.store.update(job["id"], status="cancelled" if current["cancel_requested"] else "queued")
                return
            expected_signature = signature(stage, folder, job)
            checkpoint = folder / f"{stage}.json"
            valid = checkpoint.is_file() and all(
                (folder / p).is_file() and (folder / p).stat().st_size for p in OUTPUTS[stage]
            )
            if valid:
                try:
                    previous = read_json(checkpoint)
                    valid = previous.get("pipeline_version") == 1
                    saved_signature = previous.get("input_signature")
                    if saved_signature:
                        valid = valid and saved_signature == expected_signature
                    else:
                        valid = valid and stage == "acquire"
                    if stage == "acquire":
                        valid = valid and __import__("pathlib").Path(previous["metadata"]["input"]).is_file()
                    if stage == "package":
                        valid = valid and (config.DATA / "library" / job["id"] / "song.txt").is_file()
                except (ValueError, KeyError):
                    valid = False
            invalid = not valid or any(d in regenerated for d in DEPENDENCIES[stage])
            self.store.update(job["id"], stage=stage, progress=index / len(config.STAGES))
            if invalid:
                regenerated.add(stage)
                checkpoint.unlink(missing_ok=True)
                error_file = folder / "stage-error.json"
                backend, reduced, low_memory = self.backend_overrides.get(stage), False, False
                attempts = []
                for attempt in range(4):
                    current = self.store.get(job["id"])
                    if self.stopping.is_set() or current["cancel_requested"]:
                        self.store.update(job["id"], status="cancelled" if current["cancel_requested"] else "queued")
                        return
                    attempt_start = time.monotonic()
                    cleanup_attempts(folder)
                    error_file.unlink(missing_ok=True)
                    (folder / "stage-runtime.json").unlink(missing_ok=True)
                    command = [sys.executable, "-m", "karapincho.stage", stage, str(folder)]
                    if low_memory:
                        command.append("--low-memory")
                    if reduced:
                        command.append("--reduced")
                    if backend:
                        command.extend(["--backend", backend])
                    with (folder / f"{stage}.log").open("a") as log:
                        env = {**os.environ, "KARAPINCHO_DATA": str(config.DATA), "PYTHONUNBUFFERED": "1",
                               "KARAPINCHO_WORKER_PROTOCOL": "gpu-v1"}
                        self.process = subprocess.Popen(
                            command, cwd=config.ROOT, stdout=log, stderr=log, env=env, start_new_session=True
                        )
                        while self.process.poll() is None:
                            current = self.store.get(job["id"])
                            if self.stopping.is_set() or current["cancel_requested"]:
                                self.terminate()
                                cleanup_attempts(folder)
                                checkpoint.unlink(missing_ok=True)
                                self.store.update(
                                    job["id"], status="cancelled" if current["cancel_requested"] else "queued"
                                )
                                return
                            self.stopping.wait(0.4)
                    if self.process.returncode == 0 and checkpoint.exists():
                        completed = read_json(checkpoint)
                        attempts.append({"backend": completed.get("runtime", {}).get("backend", backend or "cpu"),
                                         "elapsed_seconds": round(time.monotonic() - attempt_start, 2),
                                         "status": "completed", "runtime": completed.get("runtime", {}),
                                         "model_load_seconds": completed.get("model_load_seconds", {}),
                                         "peak_rss_mb": completed.get("peak_rss_mb")})
                        completed["attempts"] = attempts
                        completed["total_elapsed_seconds"] = round(sum(a["elapsed_seconds"] for a in attempts), 2)
                        write_json(checkpoint, completed)
                        write_json(folder / f"{stage}-attempts.json", attempts)
                        break
                    error = read_json(error_file) if error_file.exists() else {}
                    message = (
                        error.get("message")
                        or error.get("type")
                        or (f"The {stage} process stopped unexpectedly (exit {self.process.returncode}).")
                    )
                    runtime_file = folder / "stage-runtime.json"
                    last_runtime = read_json(runtime_file) if runtime_file.exists() else {}
                    actual = error.get("backend", last_runtime.get("backend", backend or "cpu"))
                    if self.process.returncode in (-9, -6) and not error and not last_runtime and backend is None:
                        actual = "unknown"
                    kind = error.get("kind") or acceleration.failure_kind(message, actual, self.process.returncode)
                    attempts.append({"backend": actual, "elapsed_seconds": round(time.monotonic() - attempt_start, 2),
                                     "status": "failed", "reason": message, "kind": kind,
                                     "runtime": error.get("runtime", last_runtime),
                                     "model_load_seconds": error.get("model_load_seconds", {}),
                                     "peak_rss_mb": error.get("peak_rss_mb")})
                    write_json(folder / f"{stage}-attempts.json", attempts)
                    if stage not in acceleration.AI_STAGES | {"prepare"} or kind == "application":
                        raise RuntimeError(message)
                    if actual == "unknown":
                        # A crash before capability reporting is not evidence that CPU medium ran out of memory.
                        backend, reduced = "cpu", False
                        warnings.append(f"Retried {stage} on CPU after the process stopped during startup.")
                    elif actual != "cpu":
                        if kind == "memory" and not reduced and stage != "align":
                            backend, reduced = actual, True
                            warnings.append(f"Retried {stage} with reduced memory usage.")
                        else:
                            backend, reduced = "cpu", False
                            phase = {"transcribe": "transcription", "separate": "vocal separation",
                                     "align": "lyric alignment", "pitch": "pitch detection",
                                     "prepare": "media preparation"}[stage]
                            if "quality retry" in message.lower():
                                warnings.append("Retried transcription for more reliable lyrics." if stage == "transcribe"
                                                else f"Retried {phase} for more reliable timing.")
                            else:
                                warnings.append(f"Used CPU processing for {phase} after GPU processing was unavailable.")
                    elif kind == "memory" and not low_memory and stage in acceleration.AI_STAGES:
                        backend, low_memory = "cpu", True
                        warnings.append(f"Retried {stage} with reduced memory usage.")
                    else:
                        raise RuntimeError(message)
                else:
                    raise RuntimeError(f"{stage} exhausted recovery attempts")
            result = read_json(checkpoint)
            if invalid or "input_signature" not in result:
                result["input_signature"] = expected_signature
                write_json(checkpoint, result)
            if stage in ("lyrics", "transcribe", "align") and result.get("source"):
                self.store.update(job["id"], lyric_source=result["source"])
            warnings.extend(result.get("warnings", []))
            if "metadata" in result:
                self.store.update(job["id"], title=result["metadata"]["title"])
            self.store.update(job["id"], warnings=list(dict.fromkeys(warnings)))
        report = {stage: read_json(folder / f"{stage}.json") for stage in config.STAGES}
        write_json(folder / "report.json", report)
        cancelled = self.store.get(job["id"])["cancel_requested"]
        self.store.update(job["id"], status="cancelled" if cancelled else "completed", progress=1)
