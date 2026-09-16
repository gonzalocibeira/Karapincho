# SPDX-License-Identifier: GPL-3.0-or-later
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from karapincho import ai, acceleration
from karapincho.media import write_json


@pytest.mark.parametrize('length', [1, 80, 160, 319, 320, 321, 16001, 240000])
def test_vectorized_pitch_energy_preserves_original_windows(length):
    audio = np.random.default_rng(7).normal(size=length).astype(np.float32)
    count = 1 + length // 160
    expected = []
    for index in range(count):
        sample = audio[max(0, index * 160 - 160):min(len(audio), index * 160 + 160)]
        expected.append(float(np.sqrt(np.mean(sample ** 2))) if len(sample) else 0)
    np.testing.assert_array_equal(ai.pitch_energy(audio, count), np.array(expected, dtype=np.float32))


@pytest.mark.parametrize('mode,model,beam', [('quality', 'medium', 5), ('fast', 'small', 1)])
def test_mode_selects_model_and_beam_without_changing_other_decoding(tmp_path, monkeypatch, mode, model, beam):
    import soundfile as sf
    sf.write(tmp_path / 'vocals.wav', np.ones(32000) * .1, 16000)
    write_json(tmp_path / 'job.json', {'processing_mode': mode, 'lyric_settings': {'language': 'en'}})
    calls = []
    class Whisper:
        def __init__(self, source, **kwargs):
            calls.append(source)
        def transcribe(self, audio, **kwargs):
            calls.append(kwargs)
            word = SimpleNamespace(word=' hello', start=0, end=1, probability=.99)
            segment = SimpleNamespace(start=0, end=1, text='hello', no_speech_prob=0,
                                      avg_logprob=0, compression_ratio=1, words=[word])
            return iter([segment]), SimpleNamespace(language='en')
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Whisper))
    monkeypatch.setattr(ai, 'whisper_path', lambda value: value)
    monkeypatch.setattr(acceleration, 'CURRENT', acceleration.Runtime(backend='cpu'))
    monkeypatch.delenv('KARAPINCHO_WHISPER_MODEL', raising=False)
    result = ai.transcribe_audio(tmp_path)
    assert calls[0] == model
    assert calls[1] == {'language': 'en', 'task': 'transcribe', 'beam_size': beam,
                        'word_timestamps': True, 'vad_filter': False,
                        'condition_on_previous_text': False, 'temperature': 0.0}
    assert any('Fast mode' in warning for warning in result['warnings']) == (mode == 'fast')
