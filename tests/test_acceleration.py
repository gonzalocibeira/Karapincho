# SPDX-License-Identifier: GPL-3.0-or-later
import sys
from types import SimpleNamespace

import pytest

from karapincho import acceleration as a
from karapincho.transcription import normalize_segment


@pytest.fixture(autouse=True)
def stable_memory(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(total=8*a.GIB, available=6*a.GIB))


@pytest.mark.parametrize('gb,batch', [(8, 8), (16, 16), (24, 32), (32, 32)])
def test_memory_profiles(gb, batch):
    actual, limit = a.profile(gb * a.GIB, gb * a.GIB)
    assert actual == batch
    assert limit == gb * a.GIB // 2
    assert a.profile(gb * a.GIB, a.GIB)[0] == max(4, batch // 2)
    assert a.profile(gb * a.GIB, a.GIB // 2)[1] == 0
    assert a.profile(gb * a.GIB, gb * a.GIB, True)[0] == max(4, batch // 2)


def test_selection_and_allocator_bound(monkeypatch):
    import psutil
    calls = []
    monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(total=8*a.GIB, available=6*a.GIB))
    monkeypatch.setattr(a.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(a.platform, 'machine', lambda: 'arm64')
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
        mps=SimpleNamespace(recommended_max_memory=lambda: 6*a.GIB,
                            set_per_process_memory_fraction=calls.append)))
    monkeypatch.setattr(a, 'VALIDATED', {'pitch'})
    monkeypatch.setenv('KARAPINCHO_ACCELERATION', 'auto')
    try:
        runtime = a.configure('pitch')
        assert runtime.backend == 'mps' and runtime.memory_limit_enforced
        assert calls == [4/6]
        assert runtime.memory_limit_bytes == 4*a.GIB
        monkeypatch.setenv('KARAPINCHO_ACCELERATION', 'cpu')
        assert a.configure('pitch').backend == 'cpu'
        assert calls == [4/6]
    finally:
        a.CURRENT = a.Runtime()


def test_unvalidated_backend_stays_cpu(monkeypatch):
    monkeypatch.setattr(a, 'VALIDATED', set())
    monkeypatch.setenv('KARAPINCHO_ACCELERATION', 'auto')
    try:
        runtime = a.configure('transcribe')
        assert runtime.backend == 'cpu'
        assert 'validation' in runtime.reason
    finally:
        a.CURRENT = a.Runtime()


@pytest.mark.parametrize('message,backend,kind', [
    ('MPS backend out of memory', 'mps', 'memory'),
    ('operation not implemented for MPS', 'mps', 'backend'),
    ('quality retry: uncertain text', 'mlx', 'backend'),
    ('invalid input audio', 'mps', 'application'),
    ('Placeholder storage has not been allocated on MPS device', 'mps', 'backend'),
    ('std::bad_alloc', 'mlx', 'memory'),
    ('unsupported language', 'cpu', 'application'),
])
def test_failure_classification(message, backend, kind):
    assert a.failure_kind(message, backend) == kind


def test_normalization_preserves_original_script_and_confidence():
    raw = {'start': 1, 'end': 2, 'text': ' 日本語', 'avg_logprob': -.3, 'compression_ratio': 1.2,
           'words': [{'word': '日本語', 'start': 1, 'end': 2, 'probability': .9}]}
    result = normalize_segment(raw, 'ja', 10)
    assert result['language'] == 'ja' and result['text'] == '日本語'
    assert result['words'] == [{'word': '日本語', 'start': 11, 'end': 12, 'score': .9}]


def test_provenance_ignores_transient_memory(monkeypatch):
    first = a.provenance('pitch')
    monkeypatch.setattr(a, 'CURRENT', a.Runtime(available_bytes=1))
    assert a.provenance('pitch') == first
    monkeypatch.setenv('KARAPINCHO_ACCELERATION', 'cpu')
    assert a.provenance('pitch')['mode'] == 'cpu'


def test_missing_mps_uses_cpu_without_allocator_calls(monkeypatch):
    monkeypatch.setattr(a.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(a.platform, 'machine', lambda: 'arm64')
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False))))
    try:
        result = a.configure('pitch', backend='mps')
        assert result.backend == 'cpu' and result.reason == 'MPS unavailable'
    finally:
        a.CURRENT = a.Runtime()


def test_missing_mlx_uses_cpu(monkeypatch):
    monkeypatch.setattr(a.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(a.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(a.importlib.util, 'find_spec', lambda name: None)
    try:
        result = a.configure('transcribe', backend='mlx')
        assert result.backend == 'cpu' and 'dependency unavailable' in result.reason
    finally:
        a.CURRENT = a.Runtime()


def test_low_confidence_word_requests_cpu_even_when_segment_score_is_good():
    from karapincho.transcription import needs_cpu_retry
    raw = {'no_speech_prob': .01, 'avg_logprob': -.3, 'compression_ratio': 1.1,
           'words': [{'probability': .35}]}
    assert needs_cpu_retry(raw)
    raw['words'][0]['probability'] = .9
    assert not needs_cpu_retry(raw)
    raw['avg_logprob'] = float('nan')
    assert needs_cpu_retry(raw)


@pytest.mark.parametrize('batch', [4, 8, 16, 32])
def test_gpu_batch_tuning_preserves_decoder_boundaries(monkeypatch, batch):
    import torch
    import torchcrepe
    from karapincho.transcription import predict_pitch
    boundaries = []
    # Simulate GPU transfers on CPU, but exercise the real batching adapter.
    original_to = torch.Tensor.to

    def transfer(self, *args, **kwargs):
        if args and args[0] == 'mps':
            return self
        return original_to(self, *args, **kwargs)

    monkeypatch.setattr(torch.Tensor, 'to', transfer)
    monkeypatch.setattr(torchcrepe, 'infer', lambda frames, model, device: torch.zeros(len(frames), 360))

    def postprocess(probabilities, *args, **kwargs):
        count = probabilities.shape[-1]
        boundaries.append(count)
        return torch.ones(1, count), torch.ones(1, count)

    monkeypatch.setattr(torchcrepe, 'postprocess', postprocess)
    result = predict_pitch(torch.zeros(1, 160*34), 16000, 160, 50, 1100, 'full', batch, 'mps', True)
    assert boundaries == [16, 16, 3]
    assert result[0].shape == (1, 35)


def test_mlx_respects_lower_framework_memory_recommendation(monkeypatch):
    from karapincho import transcription
    calls = []
    mx = SimpleNamespace(metal=SimpleNamespace(is_available=lambda: True),
                         device_info=lambda: {'max_recommended_working_set_size': 3*a.GIB},
                         set_memory_limit=lambda size: calls.append(('limit', size)),
                         set_cache_limit=lambda size: calls.append(('cache', size)))
    monkeypatch.setitem(sys.modules, 'mlx', SimpleNamespace(core=mx))
    monkeypatch.setitem(sys.modules, 'mlx.core', mx)
    monkeypatch.setattr(a.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(a.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(a.importlib.util, 'find_spec', lambda name: True)
    monkeypatch.setattr(transcription, 'model_path', lambda: 'cached-model')
    try:
        result = a.configure('transcribe', backend='mlx')
        assert result.backend == 'mlx' and result.memory_limit_enforced
        assert result.memory_limit_bytes == 3*a.GIB
        assert calls[0] == ('limit', 3*a.GIB)
        assert calls[1][1] <= 256*1024**2
        a.configure('transcribe', reduced=True, backend='mlx')
        assert calls[-1] == ('cache', 0)
    finally:
        a.CURRENT = a.Runtime()


def test_gpu_alignment_quality_failure_requests_cpu_before_estimates(tmp_path, monkeypatch):
    from karapincho import ai
    from karapincho.media import write_json
    monkeypatch.setattr(a, 'CURRENT', a.Runtime(backend='mps'))
    monkeypatch.setattr(ai, 'audio_window', lambda *args: [])
    monkeypatch.setitem(sys.modules, 'whisperx.alignment', SimpleNamespace(
        load_align_model=lambda *args, **kwargs: (object(), {}),
        align=lambda *args, **kwargs: {'segments': [{'words': []}]}))
    write_json(tmp_path/'transcript.json', {'segments': [
        {'language': 'en', 'start': 0, 'end': 1, 'text': 'hello',
         'words': [{'word': 'hello', 'start': 0, 'end': 1}]}]})
    with pytest.raises(RuntimeError, match='quality retry'):
        ai.align(tmp_path)
    assert not (tmp_path/'aligned.json').exists()


def test_eight_gb_auto_transcription_avoids_speculative_model_load(monkeypatch):
    monkeypatch.setattr(a.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(a.platform, 'machine', lambda: 'arm64')
    monkeypatch.setenv('KARAPINCHO_ACCELERATION', 'auto')
    try:
        result = a.configure('transcribe')
        assert result.backend == 'cpu'
        assert result.selected_backend == 'cpu'
        assert '8 GB' in result.reason
    finally:
        a.CURRENT = a.Runtime()


def test_pitch_batch_uses_available_headroom_but_keeps_pressure_recovery(monkeypatch):
    import psutil
    monkeypatch.setattr(a.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(a.platform, 'machine', lambda: 'arm64')
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
        mps=SimpleNamespace(recommended_max_memory=lambda: 6*a.GIB,
                            set_per_process_memory_fraction=lambda value: None)))
    try:
        assert a.configure('pitch', backend='mps').batch_size == 16
        assert a.configure('pitch', reduced=True, backend='mps').batch_size == 4
        monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(total=8*a.GIB, available=a.GIB))
        assert a.configure('pitch', backend='mps').batch_size == 4
    finally:
        a.CURRENT = a.Runtime()
