# SPDX-License-Identifier: GPL-3.0-or-later
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from karapincho.ai import transcribe
from karapincho.media import read_json


def test_words_across_old_window_boundary_are_not_dropped(tmp_path, monkeypatch):
    # Regression: the original fixed 25-second split omitted a word at the boundary.
    waveform = np.full(16000 * 31, 0.1, dtype=np.float32)
    sf.write(tmp_path / "vocals.wav", waveform, 16000)
    sf.write(tmp_path / "original.wav", waveform, 16000)
    inputs = []

    class Model:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio, **kwargs):
            inputs.append(len(audio))
            words = [
                SimpleNamespace(word=t, start=s, end=e, probability=0.99)
                for t, s, e in [("la", 24, 24.5), (" patita", 24.5, 25.4), (" principal", 25.4, 27)]
            ]
            return iter(
                [
                    SimpleNamespace(
                        start=24,
                        end=27,
                        text="la patita principal",
                        words=words,
                        no_speech_prob=0.01,
                        avg_logprob=-0.1,
                        compression_ratio=1.1,
                    )
                ]
            ), SimpleNamespace(language="es")

        def detect_language(self, audio):
            return "es", 0.99, [("es", 0.99)]

    monkeypatch.setattr("faster_whisper.WhisperModel", Model)
    monkeypatch.setattr("karapincho.ai.whisper_path", lambda name: name)
    transcribe(tmp_path)
    result = read_json(tmp_path / "transcript.json")
    assert inputs == [16000 * 31]
    assert result["segments"][0]["text"] == "la patita principal"
    assert len(result["segments"][0]["words"]) == 3
