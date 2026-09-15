# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise stage output isolation with injected inference, without loading models."""
import sys

import pytest

from karapincho import acceleration, ai, config, stage
from karapincho.media import read_json


def test_failed_attempt_does_not_replace_completed_artifact(tmp_path, monkeypatch):
    (tmp_path / 'vocals.wav').write_bytes(b'original input')
    (tmp_path / 'pitch.npz').write_bytes(b'previous successful output')
    monkeypatch.setattr(config, 'DATA', tmp_path / 'data')
    monkeypatch.setattr(sys, 'argv', ['stage', 'pitch', str(tmp_path), '--backend', 'cpu'])

    def failure(folder, low):
        assert (folder / 'vocals.wav').read_bytes() == b'original input'
        (folder / 'pitch.npz').write_bytes(b'partial failed output')
        raise RuntimeError('out of memory')

    monkeypatch.setattr(ai, 'pitch', failure)
    with pytest.raises(SystemExit):
        stage.main()
    assert (tmp_path / 'pitch.npz').read_bytes() == b'previous successful output'
    assert read_json(tmp_path / 'stage-error.json')['kind'] == 'memory'
    assert not list(tmp_path.glob('.attempt-*'))
    acceleration.CURRENT = acceleration.Runtime()


def test_success_publishes_outputs_and_provenance(tmp_path, monkeypatch):
    (tmp_path / 'vocals.wav').write_bytes(b'input')
    monkeypatch.setattr(config, 'DATA', tmp_path / 'data')
    monkeypatch.setattr(sys, 'argv', ['stage', 'pitch', str(tmp_path), '--backend', 'cpu'])

    def success(folder, low):
        (folder / 'pitch.npz').write_bytes(b'completed')
        return {'model': 'test', 'warnings': []}

    monkeypatch.setattr(ai, 'pitch', success)
    stage.main()
    assert (tmp_path / 'pitch.npz').read_bytes() == b'completed'
    report = read_json(tmp_path / 'pitch.json')
    assert report['runtime']['backend'] == 'cpu'
    assert report['provenance']['revision'] == 3
    assert not list(tmp_path.glob('.attempt-*'))
    acceleration.CURRENT = acceleration.Runtime()


def test_alignment_attempt_can_read_asr_reference(tmp_path, monkeypatch):
    (tmp_path / 'asr-reference.json').write_text('{"segments": []}')
    monkeypatch.setattr(config, 'DATA', tmp_path / 'data')
    monkeypatch.setattr(sys, 'argv', ['stage', 'align', str(tmp_path), '--backend', 'cpu'])

    def success(folder, low):
        assert read_json(folder / 'asr-reference.json') == {'segments': []}
        (folder / 'aligned.json').write_text('{"words": []}')
        return {'warnings': []}

    monkeypatch.setattr(ai, 'align', success)
    stage.main()
    assert (tmp_path / 'asr-reference.json').read_text() == '{"segments": []}'
    acceleration.CURRENT = acceleration.Runtime()


def test_pre_upgrade_worker_keeps_using_cpu(tmp_path, monkeypatch):
    monkeypatch.delenv('KARAPINCHO_WORKER_PROTOCOL', raising=False)
    monkeypatch.setenv('KARAPINCHO_ACCELERATION', 'auto')
    monkeypatch.setattr(config, 'DATA', tmp_path/'data')
    monkeypatch.setattr(sys, 'argv', ['stage', 'pitch', str(tmp_path)])

    def success(folder, low):
        assert acceleration.CURRENT.backend == 'cpu'
        (folder/'pitch.npz').write_bytes(b'completed')
        return {'warnings': []}

    monkeypatch.setattr(ai, 'pitch', success)
    stage.main()
    assert 'Restart' in read_json(tmp_path/'pitch.json')['runtime']['reason']
    acceleration.CURRENT = acceleration.Runtime()
