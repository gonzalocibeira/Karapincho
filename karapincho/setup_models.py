# SPDX-License-Identifier: GPL-3.0-or-later
"""Download models sequentially and smoke-test loading without requiring any song input."""

import subprocess
import sys

from . import config

SCRIPTS = [
    "from karapincho.config import ffmpeg; print(ffmpeg())",
    "from demucs.pretrained import get_model; get_model('htdemucs'); print('Demucs ready')",
    "from faster_whisper import WhisperModel; from karapincho.models import whisper_path; "
    "WhisperModel(str(whisper_path('medium', download=True)), device='cpu', compute_type='int8'); print('Whisper ready')",
    "from faster_whisper import WhisperModel; from karapincho.models import whisper_path; "
    "WhisperModel(str(whisper_path('small', download=True)), device='cpu', compute_type='int8'); print('Recovery Whisper ready')",
    *[
        f"from whisperx.alignment import load_align_model; from karapincho.config import DATA; "
        f"from karapincho.models import japanese_alignment_path, spanish_alignment_path; "
        f"name=(str(japanese_alignment_path(download=True)) if '{language}' == 'ja' else "
        f"str(spanish_alignment_path(download=True)) if '{language}' == 'es' else None); "
        f"load_align_model('{language}', 'cpu', model_name=name, model_dir=str(DATA/'models'/'alignment')); print('{language} alignment ready')"
        for language in ("en", "es", "ja")
    ],
    "import torch, torchcrepe; torch.set_num_threads(2); "
    "torchcrepe.predict(torch.zeros(1,1600),16000,160,50,1100,'full',batch_size=8,device='cpu'); print('Pitch model ready')",
    "import fugashi, pykakasi; print([w.surface for w in fugashi.Tagger()('日本語')]); print('Romaji ready')",
]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--quality", action="store_true", help="Also download and load-check accuracy-first models")
    args = parser.parse_args()
    config.initialize()
    for index, script in enumerate(SCRIPTS):
        print(f"Setup {index + 1}/{len(SCRIPTS)}", flush=True)
        subprocess.run([sys.executable, "-c", script], check=True)
    import importlib.util
    if importlib.util.find_spec("mlx_whisper"):
        result = subprocess.run([sys.executable, "-c",
                                 "from karapincho.transcription import model_path; print(model_path(download=True))"])
        if result.returncode:
            print("Optional GPU model unavailable; CPU processing remains available.", flush=True)
    if args.quality:
        subprocess.run([sys.executable, "-c",
                        "from faster_whisper import WhisperModel; from karapincho.models import whisper_path; "
                        "WhisperModel(str(whisper_path('large-v3', download=True)), device='cpu', "
                        "compute_type='int8'); print('Quality CPU recovery ready')"], check=True)
        if importlib.util.find_spec("mlx_qwen3_asr"):
            subprocess.run([sys.executable, "-c",
                            "import psutil; from karapincho.models import qwen_path; "
                            "from karapincho.recognition import quantized; from mlx_qwen3_asr import Session; "
                            "Session(model=str(qwen_path(quantized(psutil.virtual_memory().total), download=True))); "
                            "print('Quality Qwen ready')"], check=True)
        else:
            print("Install requirements-gpu.lock for Qwen; quality CPU recovery is ready.", flush=True)


if __name__ == "__main__":
    main()
