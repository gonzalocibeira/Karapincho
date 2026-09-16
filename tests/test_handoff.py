# SPDX-License-Identifier: GPL-3.0-or-later
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from karapincho import config, handoff
from karapincho.app import create_app
from karapincho.store import Store


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA', tmp_path / 'data')
    with TestClient(create_app(run_worker=False)) as client:
        client.headers['X-Karapincho-Token'] = client.get('/api/health').json()['token']
        yield client


@pytest.fixture
def ready(session, tmp_path):
    store = Store()
    job = store.create('file', 'input.mp4', 'Song')
    folder = config.DATA / 'library' / job['id']
    folder.mkdir()
    for name in handoff.FILES:
        (folder / name).write_bytes(b'example-media')
    (folder / 'song.txt').write_text('#TITLE:Song\n#ARTIST:Artist\n#MP3:audio.mp3\n#VIDEO:video.mp4\n#COVER:cover.jpg\n#BPM:300\n#GAP:0\n: 0 4 0 hello\nE\n')
    working = config.DATA / 'jobs' / job['id']
    working.mkdir()
    (working / 'input.mp4').write_bytes(b'original')
    store.update(job['id'], status='completed')
    destination = tmp_path / 'Songs'
    destination.mkdir()
    store.set_setting('songs_folder', str(destination))
    return store, job['id'], folder, destination


def test_export_idempotence_and_cleanup_keeps_external_copy(session, ready):
    store, job_id, folder, root = ready
    endpoint = f'/api/jobs/{job_id}'
    first = session.post(endpoint + '/export', json={})
    assert first.status_code == 200, first.text
    receipt = first.json()['export_receipt']
    target = Path(receipt['path'])
    assert target == root / 'Artist - Song'
    before = (target / 'song.txt').stat().st_mtime_ns
    assert session.post(endpoint + '/export', json={}).json()['export_receipt'] == receipt
    assert (target / 'song.txt').stat().st_mtime_ns == before
    expected_size = sum(p.stat().st_size for p in folder.iterdir()) + len(b'original')
    assert session.get(endpoint + '/cleanup').json()['bytes'] == expected_size
    assert session.post(endpoint + '/cleanup').status_code == 200
    assert not folder.exists()
    assert handoff.fingerprint(target) == receipt['fingerprint']
    assert Store().get(job_id)['export_receipt'] == receipt
    assert session.get(endpoint).json()['cleaned_at'] is not None
    assert session.get('/api/jobs/feed').json()['recent'][0]['cleaned_at'] is not None
    for action, body in [('retry', {}), ('rebuild', {}), ('processing-mode', {'processing_mode': 'fast'})]:
        assert session.post(endpoint + '/' + action, json=body).status_code == 409
    assert session.post(endpoint + '/cleanup').status_code == 200


def test_collision_keep_both_and_explicit_replacement(session, ready):
    _, job_id, _, root = ready
    existing = root / 'Artist - Song'
    existing.mkdir()
    (existing / 'mine.txt').write_text('Keep me')
    url = f'/api/jobs/{job_id}/export'
    assert session.post(url, json={}).json()['detail']['code'] == 'destination_exists'
    response = session.post(url, json={'collision': 'keep_both'})
    assert Path(response.json()['export_receipt']['path']).name == 'Artist - Song (2)'
    assert (existing / 'mine.txt').read_text() == 'Keep me'
    # Changed local output needs a new publication; explicit replace acts on canonical destination.
    (config.DATA / 'library' / job_id / 'audio.mp3').write_bytes(b'new version')
    assert session.post(url, json={'collision': 'replace'}).status_code == 200
    assert (existing / 'audio.mp3').read_bytes() == b'new version'
    assert not (existing / 'mine.txt').exists()


@pytest.mark.parametrize('failure', ['copy', 'publish', 'space', 'missing'])
def test_export_failure_preserves_previous_song_and_processing(session, ready, monkeypatch, failure):
    store, job_id, _, root = ready
    target = root / 'Artist - Song'
    target.mkdir()
    (target / 'previous.txt').write_text('previous')
    if failure == 'copy':
        def copy(*args, **kwargs):
            raise OSError('interrupted copy')
        monkeypatch.setattr(handoff.shutil, 'copyfile', copy)
    elif failure == 'publish':
        publish = handoff.publish_new
        def fail_publish(source, destination):
            if source.name.startswith('.karapincho-') and not source.name.endswith('.previous'):
                raise OSError('interrupted publication')
            return publish(source, destination)
        monkeypatch.setattr(handoff, 'publish_new', fail_publish)
    elif failure == 'space':
        monkeypatch.setattr(handoff.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    else:
        store.set_setting('songs_folder', str(root / 'disconnected'))
    response = session.post(f'/api/jobs/{job_id}/export', json={'collision': 'replace'})
    assert response.status_code == 400
    assert (target / 'previous.txt').read_text() == 'previous'
    assert store.get(job_id)['status'] == 'completed'
    assert not store.get(job_id)['export_receipt']
    assert not list(root.glob('.karapincho-*'))


def test_replacement_recovers_after_process_interruption(session, ready):
    _, job_id, folder, root = ready
    target = root / 'Artist - Song'
    backup = root / '.karapincho-interrupted.previous'
    backup.mkdir()
    (backup / 'old.txt').write_text('old')
    staging = root / '.karapincho-interrupted'
    staging.mkdir()
    journal = config.DATA / 'exports' / f'{job_id}.json'
    journal.parent.mkdir()
    journal.write_text(json.dumps({'target': str(target), 'backup': str(backup), 'staging': str(staging),
                                  'fingerprint': handoff.fingerprint(folder)}))
    response = session.post(f'/api/jobs/{job_id}/export', json={})
    assert response.status_code == 409
    assert (target / 'old.txt').read_text() == 'old'
    assert not backup.exists() and not staging.exists()


def test_unrelated_external_edits_break_idempotence(session, ready):
    _, job_id, _, _ = ready
    url = f'/api/jobs/{job_id}/export'
    response = session.post(url, json={})
    target = Path(response.json()['export_receipt']['path'])
    (target / 'audio.mp3').write_bytes(b'edited externally')
    assert session.post(url, json={}).status_code == 409
    assert (target / 'audio.mp3').read_bytes() == b'edited externally'


def test_picker_cancel_persistence_and_unsafe_destination(session, ready, monkeypatch):
    _, _, _, root = ready
    monkeypatch.setattr(handoff, 'choose_folder', lambda: None)
    assert session.post('/api/settings/choose-folder').json() == {'songs_folder': str(root), 'cancelled': True}
    new = root.parent / 'Another folder'
    new.mkdir()
    monkeypatch.setattr(handoff, 'choose_folder', lambda: str(new))
    assert session.post('/api/settings/choose-folder').json()['songs_folder'] == str(new)
    assert Store().settings()['songs_folder'] == str(new)
    monkeypatch.setattr(handoff, 'choose_folder', lambda: str(config.DATA / 'jobs'))
    assert session.post('/api/settings/choose-folder').status_code == 400
    assert Store().settings()['songs_folder'] == str(new)


def test_native_picker_cancel_and_failure(monkeypatch):
    monkeypatch.setattr(handoff.sys, 'platform', 'darwin')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0, stdout='\n'))
    assert handoff.choose_folder() is None
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1, stdout=''))
    with pytest.raises(ValueError, match='picker'):
        handoff.choose_folder()


def test_new_mutations_require_token(session, ready):
    _, job_id, _, _ = ready
    for route in ['/api/settings/choose-folder', *[f'/api/jobs/{job_id}/{a}' for a in ('export', 'cleanup', 'processing-mode')]]:
        assert session.post(route, json={}, headers={'X-Karapincho-Token': ''}).status_code == 403


def test_cleanup_active_rejected_and_failure_retry(session, ready, monkeypatch):
    store, job_id, _, root = ready
    store.update(job_id, status='queued')
    assert session.post(f'/api/jobs/{job_id}/cleanup').status_code == 409
    store.update(job_id, status='completed')
    actual = shutil.rmtree
    def deny(path, *args, **kwargs):
        raise PermissionError('test')
    monkeypatch.setattr(shutil, 'rmtree', deny)
    assert session.post(f'/api/jobs/{job_id}/cleanup').status_code == 500
    assert store.get(job_id)['cleaned_at'] is None
    monkeypatch.setattr(shutil, 'rmtree', actual)
    assert session.post(f'/api/jobs/{job_id}/cleanup').status_code == 200
    assert root.is_dir()


def test_feed_pages_are_bounded_and_active_is_separate(session):
    store = Store()
    for index in range(25):
        job = store.create('file', 'input.mp4', str(index))
        store.update(job['id'], status='failed')
    active = store.create('file', 'input.mp4', 'Active')
    first = session.get('/api/jobs/feed?limit=20').json()
    second = session.get('/api/jobs/feed', params={'limit': 20, 'before': first['next']}).json()
    assert [j['id'] for j in first['active']] == [active['id']]
    assert len(first['recent']) == 20 and len(second['recent']) == 5
    assert len({j['id'] for j in first['recent'] + second['recent']}) == 25
    assert second['next'] is None


def test_processing_modes_on_url_and_upload(session):
    fast = session.post('/api/jobs/url', json={'url': 'https://youtube.com/watch?v=abcdefghijk', 'processing_mode': 'fast'})
    assert fast.status_code == 202
    assert fast.json()['processing_mode'] == 'fast'
    uploaded = session.post('/api/jobs/upload', files={'file': ('song.mp4', b'media', 'video/mp4')}, data={'processing_mode': 'fast'})
    assert uploaded.status_code == 202 and uploaded.json()['processing_mode'] == 'fast'
    invalid = session.post('/api/jobs/url', json={'url': 'https://youtube.com/watch?v=abcdefghijk', 'processing_mode': 'turbo'})
    assert invalid.status_code == 422


def test_collision_created_during_publication_is_never_overwritten(session, ready, monkeypatch):
    _, job_id, _, root = ready
    original = handoff.publish_new
    def concurrent_writer(source, target):
        target.mkdir()
        (target / 'external.txt').write_text('created by another app')
        return original(source, target)
    monkeypatch.setattr(handoff, 'publish_new', concurrent_writer)
    result = session.post(f'/api/jobs/{job_id}/export', json={})
    assert result.status_code == 409
    assert (root / 'Artist - Song' / 'external.txt').read_text() == 'created by another app'


def test_cleanup_recovers_published_receipt_after_interruption(session, ready):
    store, job_id, source, root = ready
    target = root / 'Artist - Song (2)'
    shutil.copytree(source, target)
    staging = root / '.karapincho-crashed'
    backup = root / '.karapincho-crashed.previous'
    signature = handoff.fingerprint(target)
    journal = config.DATA / 'exports' / f'{job_id}.json'
    journal.parent.mkdir()
    journal.write_text(json.dumps({'target': str(target), 'staging': str(staging), 'backup': str(backup),
                                  'fingerprint': signature}))
    assert session.post(f'/api/jobs/{job_id}/cleanup').status_code == 200
    assert store.get(job_id)['export_receipt']['path'] == str(target)
    assert handoff.fingerprint(target) == signature


def test_cleanup_does_not_follow_link_to_external_folder(session, ready):
    _, job_id, source, root = ready
    (root / 'keep.txt').write_text('keep')
    shutil.rmtree(source)
    source.symlink_to(root, target_is_directory=True)
    assert session.post(f'/api/jobs/{job_id}/cleanup').status_code == 200
    assert (root / 'keep.txt').read_text() == 'keep'


def test_replacement_rejects_changed_destination_identity(session, ready, monkeypatch):
    _, job_id, _, root = ready
    target = root / 'Artist - Song'
    target.mkdir()
    (target / 'previous.txt').write_text('original')
    validate = handoff.validate_chart
    count = 0
    def external_replacement(*args):
        nonlocal count
        count += 1
        if count == 2:
            target.rename(root / 'Moved original')
            target.mkdir()
            (target / 'new.txt').write_text('external replacement')
        return validate(*args)
    monkeypatch.setattr(handoff, 'validate_chart', external_replacement)
    result = session.post(f'/api/jobs/{job_id}/export', json={'collision': 'replace'})
    assert result.status_code == 409
    assert (target / 'new.txt').read_text() == 'external replacement'
    assert (root / 'Moved original' / 'previous.txt').read_text() == 'original'


def test_partial_copy_is_tracked_before_any_bytes_are_written(session, ready, monkeypatch):
    _, job_id, _, root = ready
    journal = config.DATA / 'exports' / f'{job_id}.json'
    def interrupted_copy(source, target):
        entry = json.loads(journal.read_text())
        assert Path(entry['staging']) == target.parent
        target.write_bytes(b'partial')
        raise OSError('interrupted copy')
    monkeypatch.setattr(shutil, 'copyfile', interrupted_copy)
    assert session.post(f'/api/jobs/{job_id}/export', json={}).status_code == 400
    assert not (root / 'Artist - Song').exists()
    assert handoff.recover_publication(journal) is None
    assert not journal.exists()
    assert not list(root.glob('.karapincho-*'))
