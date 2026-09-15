# SPDX-License-Identifier: GPL-3.0-or-later
import os
import signal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from karapincho import config
from karapincho.app import create_app
from karapincho.media import youtube_url
from karapincho.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    with TestClient(create_app(run_worker=False)) as client:
        client.headers["X-Karapincho-Token"] = client.get("/api/health").json()["token"]
        yield client


@pytest.mark.parametrize(
    "url",
    [
        "https://youtu.be/abcdefghijk",
        "https://www.youtube.com/watch?v=abcdefghijk&t=3",
        "https://youtube.com/shorts/abcdefghijk",
    ],
)
def test_youtube_canonical(url):
    assert youtube_url(url) == "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "https://youtube.com.evil.test/watch?v=abcdefghijk",
        "https://www.youtube.com/watch?v=abcdefghijk&list=123",
        "https://youtube.com/live/abcdefghijk",
        "https://user@youtube.com/watch?v=abcdefghijk",
        "https://youtu.be/a;rm",
    ],
)
def test_youtube_rejects_invalid(url):
    with pytest.raises(ValueError):
        youtube_url(url)


def test_job_lifecycle_and_recovery(client):
    response = client.post("/api/jobs/url", json={"url": "https://youtu.be/abcdefghijk"})
    assert response.status_code == 202
    job_id = response.json()["id"]
    assert client.post(f"/api/jobs/{job_id}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/jobs/{job_id}/retry").json()["status"] == "queued"
    store = Store()
    assert store.next()["id"] == job_id
    store.recover()
    assert store.get(job_id)["status"] == "queued"
    assert client.get(f"/api/jobs/{job_id}/download").status_code == 409


def test_upload_empty_wrong_extension_and_size(client, monkeypatch):
    assert client.post("/api/jobs/upload", files={"file": ("x.mp4", b"")}).status_code == 422
    assert client.post("/api/jobs/upload", files={"file": ("x.txt", b"hi")}).status_code == 422
    monkeypatch.setattr(config, "MAX_BYTES", 3)
    assert client.post("/api/jobs/upload", files={"file": ("x.mp4", b"1234")}).status_code == 413
    assert list((config.DATA / "jobs").iterdir()) == []


def test_upload_sanitizes_filename(client):
    response = client.post("/api/jobs/upload", files={"file": ("../../escape.mp4", b"fixture")})
    assert response.status_code == 202
    assert response.json()["title"] == "escape"
    assert (config.DATA / "jobs" / response.json()["id"] / "input.mp4").read_bytes() == b"fixture"


def test_cross_origin_and_csrf(client):
    assert (
        client.post(
            "/api/jobs/url",
            json={"url": "https://youtu.be/abcdefghijk"},
            headers={"Origin": "https://evil.test"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/jobs/url", json={"url": "https://youtu.be/abcdefghijk"}, headers={"X-Karapincho-Token": ""}
        ).status_code
        == 403
    )
    assert client.get("/api/jobs", headers={"Host": "evil.test"}).status_code == 400
    assert client.get("/api/jobs/../secret").status_code == 404


def test_health_version_and_security_headers(client):
    response = client.get("/api/health")
    assert response.json()["version"] == "0.1.0"
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_shutdown_requires_session_and_same_origin(client):
    with patch("karapincho.app.os.kill") as kill:
        assert client.post("/api/shutdown", headers={"X-Karapincho-Token": ""}).status_code == 403
        assert client.post("/api/shutdown", headers={"Origin": "https://evil.test"}).status_code == 403
        assert client.get("/api/shutdown").status_code in (404, 405)
        kill.assert_not_called()


def test_shutdown_is_graceful_idempotent_and_blocks_new_jobs(client):
    with patch("karapincho.app.os.kill") as kill:
        assert client.post("/api/shutdown").status_code == 202
        assert client.post("/api/shutdown").status_code == 202
        kill.assert_called_once_with(os.getpid(), signal.SIGTERM)
        assert client.get("/api/health").json()["shutting_down"] is True
        assert client.post("/api/jobs/url", json={"url": "https://youtu.be/abcdefghijk"}).status_code == 503


def test_lyric_settings_creation_and_rebuild(client):
    settings = {"artist": "歌手", "title": "歌", "language": "ja", "lyrics": "[00:10]こんにちは"}
    response = client.post("/api/jobs/url", json={"url": "https://youtu.be/abcdefghijk", "lyric_settings": settings})
    assert response.status_code == 202
    job = response.json()
    assert Store().get(job["id"])["lyric_settings"] == settings
    assert client.post(f"/api/jobs/{job['id']}/rebuild", json=settings).status_code == 409
    client.post(f"/api/jobs/{job['id']}/cancel")
    updated = {**settings, "lyrics": "[00:10]さようなら"}
    response = client.post(f"/api/jobs/{job['id']}/rebuild", json=updated)
    assert response.status_code == 202 and response.json()["status"] == "queued"
    assert Store().get(job["id"])["lyric_settings"] == updated


def test_upload_lyric_settings_and_validation(client):
    import json
    settings = {"artist": "Singer", "lyrics": "hello world"}
    response = client.post("/api/jobs/upload", files={"file": ("song.mp4", b"test")},
                           data={"lyric_settings": json.dumps(settings)})
    assert response.status_code == 202
    assert response.json()["lyric_settings"]["lyrics"] == "hello world"
    response = client.post("/api/jobs/upload", files={"file": ("song.mp4", b"test")},
                           data={"lyric_settings": "invalid"})
    assert response.status_code == 422
    assert client.post("/api/jobs/url", json={"url": "https://youtu.be/abcdefghijk", "lyric_settings": {
        "lyrics": "[00:99]invalid"}}).status_code == 422
