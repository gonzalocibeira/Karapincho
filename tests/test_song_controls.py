# SPDX-License-Identifier: GPL-3.0-or-later
import sqlite3
import shutil
import io
import zipfile
from urllib.parse import unquote

import pytest

from karapincho import config
from karapincho.store import Store
from fastapi.testclient import TestClient
from karapincho.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    with TestClient(create_app(run_worker=False)) as session:
        session.headers["X-Karapincho-Token"] = session.get("/api/health").json()["token"]
        yield session


def test_processing_time_pauses_and_survives_reload(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr('karapincho.store.time.time', lambda: clock[0])
    store = Store(tmp_path / 'jobs.sqlite3')
    job = store.create('file', 'input.mp4', 'Timing')
    clock[0] = 200
    assert store.next()['started_at'] == 200
    clock[0] = 215
    store.update(job['id'], status='failed')
    assert store.get(job['id'])['elapsed_seconds'] == 15
    clock[0] = 300
    store.update(job['id'], status='queued')
    store.next()
    clock[0] = 320
    store.update(job['id'], status='completed')
    result = Store(store.path).get(job['id'])
    assert result['elapsed_seconds'] == 35
    assert result['started_at'] is None


def test_recovery_excludes_downtime(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr('karapincho.store.time.time', lambda: clock[0])
    store = Store(tmp_path / 'jobs.sqlite3')
    job = store.create('file', 'input.mp4', 'Recovery')
    store.next()
    clock[0] = 110
    store.update(job['id'], progress=0.5)
    clock[0] = 500
    store.recover()
    assert store.get(job['id'])['elapsed_seconds'] == 10
    assert store.get(job['id'])['started_at'] is None


def test_existing_database_migrates_without_inventing_timings(tmp_path):
    path = tmp_path / 'old.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('''CREATE TABLE jobs (
            id TEXT PRIMARY KEY, created REAL, updated REAL, status TEXT, stage TEXT,
            title TEXT, source TEXT, source_type TEXT, warnings TEXT DEFAULT '[]',
            error TEXT, cancel_requested INTEGER DEFAULT 0, progress REAL DEFAULT 0)''')
        db.execute("INSERT INTO jobs (id,status) VALUES ('old','completed')")
    assert Store(path).get('old')['elapsed_seconds'] is None
    assert Store(path).get('old')['started_at'] is None
    assert Store(path).get('old')['processing_mode'] == 'quality'
    assert Store(path).get('old')['export_receipt'] == {}
    assert Store(path).get('old')['cleaned_at'] is None


@pytest.mark.parametrize('status', ['completed', 'failed', 'cancelled'])
def test_delete_erases_only_selected_song(client, status):
    store = Store()
    job = store.create('file', 'input.mp4', 'Delete me')
    store.update(job['id'], status=status)
    other = store.create('file', 'input.mp4', 'Keep me')
    for category in ('jobs', 'library'):
        for entry in (job, other):
            folder = config.DATA / category / entry['id']
            folder.mkdir()
            (folder / 'song.mp4').write_bytes(b'fixture')
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 200
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
    for category in ('jobs', 'library'):
        assert not (config.DATA / category / job['id']).exists()
        assert (config.DATA / category / other['id'] / 'song.mp4').exists()


@pytest.mark.parametrize('running', [False, True])
def test_delete_rejects_active_song(client, running):
    store = Store()
    job = store.create('file', 'input.mp4', 'Active')
    if running:
        store.next()
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 409
    assert store.get(job['id']) is not None


def test_delete_requires_session_token(client):
    job = Store().create('file', 'input.mp4', 'Protected')
    assert client.delete(f"/api/jobs/{job['id']}", headers={'X-Karapincho-Token': ''}).status_code == 403


def test_delete_failure_keeps_record_for_retry(client, monkeypatch):
    store = Store()
    job = store.create('file', 'input.mp4', 'Retry deletion')
    store.update(job['id'], status='completed')
    (config.DATA / 'jobs' / job['id']).mkdir()
    def denied(*args, **kwargs):
        raise PermissionError('denied')
    monkeypatch.setattr('karapincho.store.shutil.rmtree', denied)
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 500
    assert store.get(job['id']) is not None


def test_cancellation_of_just_claimed_song_cannot_enable_deletion(client):
    store = Store()
    job = store.create('file', 'input.mp4', 'Claimed')
    store.next()
    store.request_cancel(job['id'])
    assert store.get(job['id'])['status'] == 'running'
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 409
    store.update(job['id'], status='cancelled')
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 200


@pytest.mark.parametrize('removed', ['folder', 'song.txt', 'audio.mp3', 'video.mp4', 'cover.jpg'])
def test_disk_deletion_hides_song_and_blocks_cached_download(client, removed):
    store = Store()
    job = store.create('file', 'input.mp4', 'Deleted externally')
    folder = config.DATA / 'library' / job['id']
    folder.mkdir()
    for name in ('song.txt', 'audio.mp3', 'video.mp4', 'cover.jpg'):
        (folder / name).write_bytes(b'fixture')
    cache = config.DATA / 'jobs' / job['id']
    cache.mkdir()
    (folder / 'song.txt').write_text('#ARTIST:Björk\n#TITLE:Jóga\n', encoding='utf-8')
    with zipfile.ZipFile(cache / 'song.zip', 'w') as archive:
        for file in folder.iterdir():
            archive.write(file, f'Karapincho-{job["id"][:8]}/{file.name}')
    (cache / 'report.json').write_text('{}')
    store.update(job['id'], status='completed')
    url = f"/api/jobs/{job['id']}"
    assert client.get(url).status_code == 200
    assert job['id'] in {item['id'] for item in client.get('/api/jobs').json()}
    download = client.get(f'{url}/download')
    assert 'Björk - Jóga.zip' in unquote(download.headers['content-disposition'])
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert {name.split('/')[0] for name in archive.namelist()} == {'Björk - Jóga'}
    assert download.headers['Cache-Control'] == 'no-store'

    if removed == 'folder':
        shutil.rmtree(folder)
    else:
        (folder / removed).unlink()

    assert client.get('/api/jobs').json() == []
    for endpoint in ('', '/download', '/report'):
        assert client.get(url + endpoint).status_code == 404
    assert client.post(f'{url}/open-folder').status_code == 404
    assert (cache / 'song.zip').exists()
    # History remains available for explicit cleanup, without deleting files on a read.
    assert store.get(job['id'])['status'] == 'completed'
    assert client.delete(url).status_code == 200
    assert not cache.exists()


@pytest.mark.parametrize('status', ['queued', 'running', 'failed', 'cancelled'])
def test_unfinished_jobs_remain_visible_without_library_files(client, status):
    store = Store()
    job = store.create('file', 'input.mp4', 'No output yet')
    store.update(job['id'], status=status)
    assert [item['id'] for item in client.get('/api/jobs').json()] == [job['id']]
    assert client.get(f"/api/jobs/{job['id']}").json()['status'] == status


def test_clear_recent_removes_all_pages_and_local_files_keeps_karaoke_and_active(client, tmp_path):
    store = Store()
    karaoke = tmp_path.parent / f'{tmp_path.name}-Songs'
    karaoke.mkdir()
    song = karaoke / 'song.txt'
    song.write_text('Keep karaoke')
    queued = store.create('file', 'input.mp4', 'Queued')
    running = store.next()
    queued = store.create('file', 'input.mp4', 'Still queued')
    recent = []
    for index in range(25):
        job = store.create('file', 'input.mp4', f'Recent {index}')
        store.update(job['id'], status=('completed', 'failed', 'cancelled')[index % 3],
                     export_receipt={'path': str(karaoke)})
        recent.append(job['id'])
        # Include already removed files and jobs previously cleaned up.
        if index % 2:
            for category in ('jobs', 'library'):
                folder = config.DATA / category / job['id']
                folder.mkdir()
                (folder / 'local.mp4').write_bytes(b'working files')
        else:
            store.update(job['id'], cleaned_at=123)
    for job in (queued, running):
        folder = config.DATA / 'jobs' / job['id']
        folder.mkdir()
        (folder / 'input.mp4').write_bytes(b'active')
    response = client.post('/api/jobs/clear-recent')
    assert response.status_code == 200
    assert set(response.json()['deleted']) == set(recent)
    assert response.json()['failed'] == []
    assert {job['id'] for job in store.all()} == {queued['id'], running['id']}
    assert client.get('/api/jobs/feed').json()['recent'] == []
    assert song.read_text() == 'Keep karaoke'
    for job_id in recent:
        for category in ('jobs', 'library'):
            assert not (config.DATA / category / job_id).exists()
    for job in (queued, running):
        assert (config.DATA / 'jobs' / job['id'] / 'input.mp4').exists()
    assert client.post('/api/jobs/clear-recent').json() == {'deleted': [], 'failed': []}


def test_clear_recent_keeps_failed_deletions_for_retry(client, monkeypatch):
    store = Store()
    blocked = store.create('file', 'input.mp4', 'Blocked')
    missing = store.create('file', 'input.mp4', 'Already missing')
    for job in (blocked, missing):
        store.update(job['id'], status='completed')
    (config.DATA / 'jobs' / blocked['id']).mkdir()
    original = shutil.rmtree
    def denied(*args, **kwargs):
        raise PermissionError('denied')
    monkeypatch.setattr('karapincho.store.shutil.rmtree', denied)
    result = client.post('/api/jobs/clear-recent').json()
    assert result['deleted'] == [missing['id']]
    assert result['failed'] == [{'id': blocked['id'], 'title': 'Blocked', 'error': 'denied'}]
    assert store.get(blocked['id']) is not None
    monkeypatch.setattr('karapincho.store.shutil.rmtree', original)
    assert client.post('/api/jobs/clear-recent').json()['deleted'] == [blocked['id']]


def test_clear_recent_requires_session_token(client):
    assert client.post('/api/jobs/clear-recent', headers={'X-Karapincho-Token': ''}).status_code == 403
