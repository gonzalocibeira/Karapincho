# SPDX-License-Identifier: GPL-3.0-or-later
import json
import subprocess
import time

import pytest

from karapincho import config
from karapincho.store import Store
from karapincho.worker import Worker


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    config.initialize()
    store = Store()
    job = store.create("file", "input.mp4", "Worker test")
    folder = tmp_path / "jobs" / job["id"]
    folder.mkdir()
    (folder / "input.mp4").write_bytes(b"test")
    return store, job, folder


def fake_stages(monkeypatch, fail_stage=None, memory_stage=None, slow_stage=None):
    real_popen = subprocess.Popen
    script = """
import json, sys, time
from pathlib import Path
stage, folder, low = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
with (folder/'calls').open('a') as f: f.write(stage+':'+low+'\\n')
if stage == SLOW: time.sleep(30)
if stage == FAIL or (stage == MEMORY and low == 'False'):
    (folder/'stage-error.json').write_text(json.dumps({'message': 'out of memory' if stage == MEMORY else 'test failure'}))
    sys.exit(1)
for name in OUTPUTS[stage]: (folder/name).write_text('test')
result = {'pipeline_version': 1, 'warnings': []}
if stage == 'acquire': result['metadata'] = {'input': str(folder/'input.mp4'), 'title': 'Worker test'}
if stage == 'package':
    p=folder.parent.parent/'library'/folder.name
    p.mkdir(exist_ok=True); (p/'song.txt').write_text('test')
(folder/(stage+'.json')).write_text(json.dumps(result))
"""
    from karapincho.worker import OUTPUTS

    prefix = f"OUTPUTS={OUTPUTS!r}\nFAIL={fail_stage!r}\nMEMORY={memory_stage!r}\nSLOW={slow_stage!r}\n"

    def launch(args, **kwargs):
        return real_popen(
            [args[0], "-c", prefix + script, args[3], args[4], str("--low-memory" in args)], **kwargs
        )

    monkeypatch.setattr(subprocess, "Popen", launch)


def wait_until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Worker did not reach the expected state")


def test_checkpoints_resume_without_repeating_successful_stages(environment, monkeypatch):
    store, job, folder = environment
    fake_stages(monkeypatch, fail_stage="align")
    worker = Worker(store)
    with pytest.raises(RuntimeError, match="test failure"):
        worker.execute(job)
    first_calls = (folder / "calls").read_text().splitlines()
    assert first_calls == [f"{s}:False" for s in config.STAGES[:config.STAGES.index("align") + 1]]
    # Restore Popen before installing another wrapper around it.
    monkeypatch.undo()
    monkeypatch.setattr(config, "DATA", folder.parent.parent)
    fake_stages(monkeypatch)
    worker.execute(job)
    calls = (folder / "calls").read_text().splitlines()
    assert calls[len(first_calls) :] == [f"{s}:False" for s in config.STAGES[config.STAGES.index("align"): ]]
    assert store.get(job["id"])["status"] == "completed"
    assert json.loads((folder / "report.json").read_text())["align"]["pipeline_version"] == 1


def test_memory_failure_retries_once(environment, monkeypatch):
    store, job, folder = environment
    fake_stages(monkeypatch, memory_stage="separate")
    Worker(store).execute(job)
    calls = (folder / "calls").read_text().splitlines()
    assert calls.count("separate:False") == 1 and calls.count("separate:True") == 1
    assert any("reduced memory" in w for w in store.get(job["id"])["warnings"])


def test_cancellation_terminates_child_and_advances_queue(environment, monkeypatch):
    store, job, folder = environment
    fake_stages(monkeypatch, slow_stage="acquire")
    worker = Worker(store)
    worker.start()
    try:
        wait_until(lambda: (folder / "calls").exists())
        process = worker.process
        store.update(job["id"], cancel_requested=1)
        wait_until(lambda: store.get(job["id"])["status"] == "cancelled")
        assert process.poll() is not None
        assert not (folder / "acquire.json").exists()
    finally:
        worker.stop()


def test_shutdown_requeues_interrupted_job(environment, monkeypatch):
    store, job, folder = environment
    fake_stages(monkeypatch, slow_stage="acquire")
    worker = Worker(store)
    worker.start()
    wait_until(lambda: (folder / "calls").exists())
    worker.stop()
    assert store.get(job["id"])["status"] == "queued"
    assert worker.process.poll() is not None


def test_lyric_rebuild_reuses_audio_and_pitch(environment, monkeypatch):
    store, job, folder = environment
    fake_stages(monkeypatch)
    worker = Worker(store)
    worker.execute(job)
    first_calls = (folder / "calls").read_text().splitlines()
    updated = store.rebuild(job["id"], {"lyrics": "corrected lyrics", "language": "en"})
    worker.execute(updated)
    calls = (folder / "calls").read_text().splitlines()[len(first_calls):]
    assert calls == [f"{stage}:False" for stage in ("lyrics", "transcribe", "align", "chart", "package")]


@pytest.mark.parametrize('failure,stage,expected', [
    ('memory', 'pitch', [(None, False, False), ('mps', True, False), ('cpu', False, False), ('cpu', False, True)]),
    ('backend', 'pitch', [(None, False, False), ('cpu', False, False)]),
    ('memory', 'align', [(None, False, False), ('cpu', False, False), ('cpu', False, True)]),
])
def test_gpu_recovery_uses_fresh_processes(environment, monkeypatch, failure, stage, expected):
    store, job, folder = environment
    fake_stages(monkeypatch)
    normal = subprocess.Popen
    calls = []

    def launch(args, **kwargs):
        if args[3] != stage:
            return normal(args, **kwargs)
        backend = args[args.index('--backend') + 1] if '--backend' in args else None
        reduced, low = '--reduced' in args, '--low-memory' in args
        calls.append((backend, reduced, low))
        if len(calls) == len(expected):
            return normal(args, **kwargs)
        actual = backend or 'mps'
        kind = failure if actual != 'cpu' else 'memory'
        (folder / 'stage-error.json').write_text(json.dumps(
            {'backend': actual, 'kind': kind, 'message': 'out of memory' if kind == 'memory' else 'unsupported op'}))

        class Failed:
            returncode = 1
            def poll(self):
                return 1
        return Failed()

    monkeypatch.setattr(subprocess, 'Popen', launch)
    Worker(store).execute(job)
    assert calls == expected
    report = json.loads((folder/f'{stage}.json').read_text())
    assert len(report['attempts']) == len(expected)
    assert report['total_elapsed_seconds'] >= 0


def test_cancel_after_failed_gpu_attempt_prevents_retry(environment, monkeypatch):
    store, job, folder = environment
    fake_stages(monkeypatch)
    normal = subprocess.Popen
    calls = []

    def launch(args, **kwargs):
        if args[3] != 'pitch':
            return normal(args, **kwargs)
        calls.append(args)
        store.update(job['id'], cancel_requested=1)
        (folder/'stage-error.json').write_text(json.dumps(
            {'backend': 'mps', 'kind': 'memory', 'message': 'out of memory'}))

        class Failed:
            returncode = 1
            def poll(self):
                return 1
        return Failed()

    monkeypatch.setattr(subprocess, 'Popen', launch)
    Worker(store).execute(job)
    assert len(calls) == 1
    assert store.get(job['id'])['status'] == 'cancelled'
    assert not (folder/'pitch.json').exists()


def test_video_backend_failure_recovers_with_software_encoder(environment, monkeypatch):
    store, job, folder = environment
    fake_stages(monkeypatch)
    normal = subprocess.Popen
    calls = []

    def launch(args, **kwargs):
        if args[3] == 'prepare':
            calls.append(args)
            if '--backend' not in args:
                (folder/'stage-error.json').write_text(json.dumps(
                    {'backend': 'videotoolbox', 'kind': 'backend', 'message': 'VideoToolbox unavailable'}))

                class Failed:
                    returncode = 1
                    def poll(self):
                        return 1
                return Failed()
        return normal(args, **kwargs)

    monkeypatch.setattr(subprocess, 'Popen', launch)
    Worker(store).execute(job)
    assert len(calls) == 2
    assert calls[1][-2:] == ['--backend', 'cpu']
    assert json.loads((folder/'prepare.json').read_text())['attempts'][0]['backend'] == 'videotoolbox'


@pytest.mark.parametrize('runtime_written', [True, False])
def test_killed_gpu_child_uses_runtime_record_for_recovery(environment, monkeypatch, runtime_written):
    store, job, folder = environment
    fake_stages(monkeypatch)
    normal = subprocess.Popen
    calls = []

    def launch(args, **kwargs):
        if args[3] == 'pitch':
            calls.append(args)
            if len(calls) == 1:
                if runtime_written:
                    (folder/'stage-runtime.json').write_text('{"backend": "mps"}')
                abandoned = folder / '.attempt-killed'
                abandoned.mkdir()
                (abandoned/'pitch.npz').write_bytes(b'partial')

                class Killed:
                    returncode = -9
                    def poll(self):
                        return -9
                return Killed()
        return normal(args, **kwargs)

    monkeypatch.setattr(subprocess, 'Popen', launch)
    Worker(store).execute(job)
    assert len(calls) == 2
    assert ('--reduced' in calls[1]) == runtime_written
    assert '--low-memory' not in calls[1]
    assert calls[1][-2:] == ['--backend', 'mps' if runtime_written else 'cpu']
    assert not (folder/'.attempt-killed').exists()
