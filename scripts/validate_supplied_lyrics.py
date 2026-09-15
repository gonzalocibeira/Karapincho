# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise supplied lyric alignment using the documented public-domain fixture openings.

This is assisted-text validation, not recognition accuracy or independently
annotated timing accuracy. Existing jobs and playable exports are never edited.
Use HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 when alignment models are cached.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from karapincho import acceleration, config
from karapincho.ai import align
from karapincho.chart import lyric_units
from karapincho.lyrics import compose, parse_lyrics, normalized
from karapincho.media import read_json, write_json
parser = argparse.ArgumentParser(description="Validate supplied opening lyrics against existing fixture audio.")
for language in ("japanese", "spanish", "english"):
    parser.add_argument(f"--{language}-job", required=True)
parser.add_argument("--backend", choices=("cpu", "mps"), default="cpu")
args = parser.parse_args()
config.initialize()
cases = [
    ('ja',args.japanese_job,'さくらさくら\n弥生の空は\n見渡す限り'),
    ('es',args.spanish_job,'La cucaracha la cucaracha\nya no puede caminar\nporque no tiene porque le falta\nla patita principal'),
    ('en',args.english_job,'Should auld acquaintance be forgot\nand never brought to mind\nshould auld acquaintance be forgot\nand days of auld lang syne'),
]
results = []
cache = config.ROOT / '.cache'
cache.mkdir(exist_ok=True)
root = Path(tempfile.mkdtemp(prefix='supplied-lyrics-validation-', dir=cache))
for language, job_id, text in cases:
    source_folder = config.DATA / 'jobs' / job_id
    folder = root / language
    folder.mkdir()
    for name in ('vocals.wav','original.wav'):
        (folder / name).symlink_to(source_folder / name)
    metadata = read_json(source_folder / 'prepare.json')['metadata']
    ref = read_json(source_folder / 'transcript.json')
    # Restrict anchors to the documented opening excerpt, avoiding later repeat matches.
    ref['segments'] = ref['segments'][:2 if language == 'en' else 1]
    transcript = compose({'source':'user','language':language,'lines':parse_lyrics(text)}, ref, metadata['duration'])
    write_json(folder / 'transcript.json', transcript)
    runtime = acceleration.configure("align", backend=args.backend)
    stats = align(folder)
    stats["runtime"] = runtime.report()
    assert runtime.backend == args.backend, "Requested alignment backend was unavailable"
    words = read_json(folder / 'aligned.json')['words']
    preserved = normalized(''.join(w['word'] for w in words)) == normalized(text)
    units = lyric_units(words)
    results.append({'language': language, 'text_preserved':preserved, 'alignment':stats,
                    'start':words[0]['start'], 'end':words[-1]['end'],
                    'chart_text': ''.join(u['text'] for u in units)})
    print(json.dumps(results[-1], ensure_ascii=False), flush=True)
write_json(root / 'results.json', results)
print('RESULTS', root, flush=True)
assert all(r['text_preserved'] for r in results)
