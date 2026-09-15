# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import signal
import threading
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from karapincho import benchmark, config
from karapincho.app import create_app
from karapincho.media import read_json, write_json
from karapincho.store import Store
from karapincho.worker import Worker


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    config.initialize()
    return benchmark.Benchmarks()


def test_baseline_assets_and_medians():
    base = benchmark.baseline()
    assert [f['gpu']['seconds'] for f in base['fixtures']] == [111.62, 76.2, 257.47]
    for f in base['fixtures']:
        assert hashlib.sha256((benchmark.ASSETS / f'{f["language"]}.mp4').read_bytes()).hexdigest() == f['sha256']
    rows = [{"language": f['language'], "run": n, "elapsed_seconds": f['gpu']['seconds'] / 2,
             "stages": {s: {'seconds': v / 2} for s, v in f['gpu']['stages'].items()}}
            for f in base['fixtures'] for n in (1, 2, 3)]
    assert benchmark.compare(rows, 'auto')['ratio'] == 2
    assert benchmark.compare(rows[:-1], 'auto')['ratio'] is None
    assert len(benchmark.compare(rows[:-1], 'auto')['fixtures']) == 2
    assert benchmark.compare(rows, 'cpu')['ratio'] > 2


def test_api_guards_duplicate_cancel_and_persistence(environment):
    with TestClient(create_app(run_worker=False)) as client:
        assert client.get('/api/benchmarks').json()['latest']['status'] == 'idle'
        assert client.post('/api/benchmarks', json={'mode': 'auto'}).status_code == 403
        client.headers['X-Karapincho-Token'] = client.get('/api/health').json()['token']
        assert client.post('/api/benchmarks', json={'mode': 'unsafe'}).status_code == 409
        first = client.post('/api/benchmarks', json={'mode': 'auto'})
        assert first.status_code == 202 and first.json()['status'] == 'queued'
        assert client.post('/api/benchmarks', json={'mode': 'cpu'}).status_code == 409
        assert client.post('/api/benchmarks/cancel').json()['status'] == 'cancelled'
        assert client.get('/api/benchmarks/report').json()['latest']['id'] == first.json()['id']
        assert client.get('/api/jobs').json() == []
    assert benchmark.Benchmarks().snapshot()['status'] == 'cancelled'


def test_restart_marks_interrupted_and_preserves_rows(environment):
    started = environment.start('auto')
    folder = environment.root / started['id']
    folder.mkdir()
    write_json(folder / 'benchmark.json', [])
    restarted = benchmark.Benchmarks()
    restarted.recover()
    restored = restarted.snapshot()
    assert restored['status'] == 'interrupted'
    assert restored['id'] == started['id'] and restored['rows'] == []


def test_runner_isolated_nine_fresh_jobs(environment, monkeypatch):
    original = config.DATA
    store = Store()
    original_job = store.create('file', 'input.mp4', 'Keep me')
    calls = []

    def execute(worker, job):
        time.sleep(.02)
        calls.append(job['id'])
        folder = config.DATA / 'jobs' / job['id']
        assert read_json(folder / 'lyrics-source.json')['lines'] == []
        assert config.STAGES == benchmark.STAGES
        assert not (folder / 'report.json').exists()
        write_json(folder / 'report.json', {s: {'total_elapsed_seconds': 1, 'runtime': {'backend': 'cpu'}}
                                           for s in benchmark.STAGES})

    monkeypatch.setattr(Worker, 'execute', execute)
    # In production this function runs in a new process; restore process globals in this test.
    monkeypatch.setattr(config, 'STAGES', list(config.STAGES))
    for key in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'KARAPINCHO_ACCELERATION'):
        monkeypatch.setenv(key, '')
    folder = original / 'benchmarks' / 'test-run'
    folder.mkdir()
    with patch('signal.signal'):
        benchmark.run(folder, 'cpu')
    assert len(calls) == len(set(calls)) == 9
    assert Store(original / 'jobs.sqlite3').all() == [original_job]
    rows = read_json(folder / 'benchmark.json')
    assert len(rows) == 9 and read_json(folder / 'progress.json')['completed'] == 9
    assert benchmark.compare(rows, 'cpu')['ratio'] is not None


def test_runner_cancel_stops_before_next_attempt(environment, monkeypatch):
    handlers = {}
    def register(sig, handler):
        handlers[sig] = handler

    def execute(worker, job):
        handlers[signal.SIGTERM]()
        assert worker.stopping.is_set()

    monkeypatch.setattr(Worker, 'execute', execute)
    monkeypatch.setattr(config, 'STAGES', list(config.STAGES))
    for key in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'KARAPINCHO_ACCELERATION'):
        monkeypatch.setenv(key, '')
    folder = config.DATA / 'benchmarks' / 'cancel-run'
    folder.mkdir()
    with patch('signal.signal', register):
        benchmark.run(folder, 'auto')
    assert len(Store().all()) == 1
    assert not (folder / 'benchmark.json').exists()


def test_worker_schedules_benchmark_between_songs(environment, monkeypatch):
    store = Store()
    first = store.create('file', 'input.mp4', 'First')
    second = store.create('file', 'input.mp4', 'Second')
    worker = Worker(store)
    order = []

    class FakeBenchmark:
        pending = False
        def run_pending(self, stopping):
            if self.pending:
                self.pending = False
                order.append('benchmark')
                return True
            return False
        def cancel(self):
            pass

    worker.benchmarks = FakeBenchmark()
    def execute(job):
        order.append(job['id'])
        if job['id'] == first['id']:
            worker.benchmarks.pending = True
        else:
            worker.stopping.set()
    monkeypatch.setattr(worker, 'execute', execute)
    worker.loop()
    assert order == [first['id'], 'benchmark', second['id']]


def test_cancel_running_process_and_release_queue(environment, monkeypatch):
    import subprocess
    import sys
    real_popen = subprocess.Popen
    ready = config.DATA / 'ready'
    def launch(args, **kwargs):
        return real_popen([sys.executable, '-c',
                           f'from pathlib import Path; import time; Path({str(ready)!r}).touch(); time.sleep(60)'],
                          **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', launch)
    environment.start('auto')
    stopping = threading.Event()
    thread = threading.Thread(target=environment.run_pending, args=(stopping,))
    thread.start()
    deadline = time.monotonic() + 5
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(.02)
    assert ready.exists()
    environment.cancel()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert environment.snapshot()['status'] == 'cancelled'
    assert environment.process is None
    assert environment.start('cpu')['status'] == 'queued'


def test_second_app_cannot_interrupt_existing_benchmark(environment):
    first = Worker(Store())
    first.benchmarks = environment
    first.start()
    try:
        # Keep a queued state on disk without starting a real benchmark process.
        with environment.lock:
            environment.state = {'status': 'running', 'id': 'test-active', 'mode': 'auto'}
            environment.save()
        second = Worker(Store())
        second.benchmarks = benchmark.Benchmarks()
        with pytest.raises(RuntimeError, match='already running'):
            second.start()
        assert read_json(environment.path)['status'] == 'running'
    finally:
        first.stop()
