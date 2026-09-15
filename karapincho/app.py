# SPDX-License-Identifier: GPL-3.0-or-later
import importlib.util
import os
import secrets
import signal
import subprocess
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, config
from .benchmark import Benchmarks, baseline
from .export import download_name, update_archive_name
from .media import youtube_url
from .lyrics import LyricSettings
from .store import Store
from .worker import Worker


class URLInput(BaseModel):
    url: str = Field(max_length=2048)
    lyric_settings: LyricSettings = Field(default_factory=LyricSettings)


def create_app(run_worker=True):
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        config.initialize()
        app.state.store = Store()
        worker = Worker(app.state.store)
        app.state.benchmarks = Benchmarks()
        worker.benchmarks = app.state.benchmarks
        if run_worker:
            worker.start()
        try:
            yield
        finally:
            if run_worker:
                worker.stop()

    app = FastAPI(title="Karapincho", lifespan=lifespan)
    app.state.shutting_down = False
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse({"detail": "Cross-origin access is disabled."}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site access is disabled."}, status_code=403)
            if request.method not in ("GET", "HEAD", "OPTIONS") and not secrets.compare_digest(
                request.headers.get("x-karapincho-token", ""), token
            ):
                return JSONResponse({"detail": "Reload Karapincho to refresh your session."}, status_code=403)
            if app.state.shutting_down and request.method not in ("GET", "HEAD", "OPTIONS"):
                if request.url.path != "/api/shutdown":
                    return JSONResponse({"detail": "Karapincho is shutting down."}, status_code=503)
            if request.url.path == "/api/jobs/upload" and request.method == "POST":
                try:
                    length = int(request.headers.get("content-length", "-1"))
                except ValueError:
                    length = -1
                if length < 0:
                    return JSONResponse(
                        {"detail": "A Content-Length header is required for uploads."}, status_code=411
                    )
                if length > config.MAX_BYTES + 1024 * 1024:
                    return JSONResponse({"detail": "MP4 files must be smaller than 2 GB."}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def store():
        return app.state.store

    def get_job(job_id):
        if not __import__("re").fullmatch(r"[a-f0-9]{32}", job_id):
            raise HTTPException(404, "Song not found")
        job = store().get(job_id)
        if job is None:
            raise HTTPException(404, "Song not found")
        return job

    def song_available(job):
        # Job history and cached ZIPs can outlive a manually deleted library song.
        folder = config.DATA / "library" / job["id"]
        return all((folder / name).is_file() for name in ("song.txt", "audio.mp3", "video.mp4", "cover.jpg"))

    def ready_job(job_id):
        job = get_job(job_id)
        if job["status"] != "completed":
            raise HTTPException(409, "This song is not ready yet")
        if not song_available(job):
            raise HTTPException(404, "The song files are missing")
        return job

    @app.get("/api/health")
    def health():
        missing = [
            name
            for name in ("demucs", "whisperx", "torchcrepe", "av")
            if importlib.util.find_spec(name) is None
        ]
        return {
            "app": "karapincho",
            "version": __version__,
            "shutting_down": app.state.shutting_down,
            "ready": not missing,
            "missing": missing,
            "token": token,
            "stages": config.STAGES,
            "max_bytes": config.MAX_BYTES,
            "max_minutes": config.MAX_SECONDS // 60,
        }

    @app.post("/api/shutdown", status_code=202)
    async def shutdown(background_tasks: BackgroundTasks):
        if not app.state.shutting_down:
            app.state.shutting_down = True
            # Send the response first. Uvicorn handles SIGTERM by closing the
            # server and running lifespan cleanup, which stops worker children.
            background_tasks.add_task(os.kill, os.getpid(), signal.SIGTERM)
        return {"ok": True}

    @app.get("/api/jobs")
    def jobs():
        return [job for job in store().all() if job["status"] != "completed" or song_available(job)]

    @app.get("/api/benchmarks")
    def benchmarks():
        return {"baseline": baseline(), "latest": app.state.benchmarks.snapshot()}

    @app.post("/api/benchmarks", status_code=202)
    def start_benchmark(body: dict):
        try:
            return app.state.benchmarks.start(body.get("mode", "auto"))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/benchmarks/cancel")
    def cancel_benchmark():
        return app.state.benchmarks.cancel()

    @app.get("/api/benchmarks/report")
    def benchmark_report():
        return JSONResponse({"baseline": baseline(), "latest": app.state.benchmarks.snapshot()},
                            headers={"Content-Disposition": 'attachment; filename="karapincho-benchmark.json"'})

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        result = get_job(job_id)
        return ready_job(job_id) if result["status"] == "completed" else result

    @app.post("/api/jobs/url", status_code=202)
    def submit_url(body: URLInput):
        try:
            url = youtube_url(body.url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return store().create("youtube", url, "YouTube song", lyric_settings=body.lyric_settings.model_dump())

    @app.post("/api/jobs/upload", status_code=202)
    async def upload(file: UploadFile = File(...), lyric_settings: str = Form("{}")):
        try:
            settings = LyricSettings.model_validate_json(lyric_settings).model_dump()
        except ValidationError as exc:
            raise HTTPException(422, "Invalid song details or lyrics: " + str(exc)) from exc
        if not file.filename or Path(file.filename).suffix.lower() != ".mp4":
            raise HTTPException(422, "Choose an MP4 video")
        job_id = uuid.uuid4().hex
        folder = config.DATA / "jobs" / job_id
        folder.mkdir(parents=True)
        size = 0
        try:
            with (folder / "input.mp4").open("wb") as target:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > config.MAX_BYTES:
                        raise HTTPException(413, "MP4 files must be smaller than 2 GB")
                    target.write(chunk)
            if not size:
                raise HTTPException(422, "The MP4 file is empty")
            return store().create(
                "file", "input.mp4", Path(file.filename.replace("\\", "/")).stem[:200], job_id, lyric_settings=settings
            )
        except BaseException:
            __import__("shutil").rmtree(folder, ignore_errors=True)
            raise
        finally:
            await file.close()

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        job = get_job(job_id)
        if job["status"] not in ("queued", "running"):
            raise HTTPException(409, "This job is no longer running")
        store().request_cancel(job_id)
        return store().get(job_id)

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: str):
        job = get_job(job_id)
        if job["status"] not in ("failed", "cancelled"):
            raise HTTPException(409, "Only failed or cancelled songs can be retried")
        store().update(job_id, status="queued", cancel_requested=0, error=None)
        return store().get(job_id)

    @app.post("/api/jobs/{job_id}/rebuild", status_code=202)
    def rebuild(job_id: str, body: LyricSettings):
        get_job(job_id)
        try:
            return store().rebuild(job_id, body.model_dump())
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.delete("/api/jobs/{job_id}")
    def delete_song(job_id: str):
        get_job(job_id)
        try:
            store().delete(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Song not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, "Could not erase all song files. Check disk permissions and try again.") from exc
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/download")
    def download(job_id: str):
        ready_job(job_id)
        path = config.DATA / "jobs" / job_id / "song.zip"
        if not path.exists():
            raise HTTPException(404, "The exported ZIP is missing")
        name = download_name(config.DATA / "library" / job_id)
        update_archive_name(path, config.DATA / "library" / job_id, name)
        return FileResponse(path, media_type="application/zip", filename=f"{name}.zip")

    @app.get("/api/jobs/{job_id}/report")
    def report(job_id: str):
        ready_job(job_id)
        return FileResponse(config.DATA / "jobs" / job_id / "report.json", media_type="application/json")

    @app.post("/api/jobs/{job_id}/open-folder")
    def open_folder(job_id: str):
        ready_job(job_id)
        path = config.DATA / "library" / job_id
        if not path.is_dir():
            raise HTTPException(404, "The song folder is missing")
        subprocess.run(["open", str(path)], check=True, timeout=10)
        return {"ok": True}

    frontend = config.ROOT / "frontend" / "dist"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    else:

        @app.get("/")
        def setup_needed():
            return {"message": "Run Setup.command to build the interface, then Start.command."}

    return app


app = create_app()
