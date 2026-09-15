# SPDX-License-Identifier: GPL-3.0-or-later
"""Controlled fresh CPU/GPU fixture runs. Never modifies original jobs or exports."""
import argparse
import json
import os
import statistics
import sqlite3
import time
from pathlib import Path

from karapincho import config
from karapincho.media import read_json, write_json
from karapincho.store import Store
from karapincho.worker import Worker

FIXTURES = {'es': '65d2b9fe9e0a48d9a1e4ccc27aefe92c', 'ja': '955683ba005f44c9a972748de5ac1114',
            'en': '7f1876fed53f49968275d19460b66387'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--modes', nargs='+', choices=['cpu', 'gpu', 'auto'], default=['cpu', 'gpu'])
    parser.add_argument('--languages', nargs='+', choices=list(FIXTURES), default=list(FIXTURES))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error('--runs must be positive')
    if args.resume and not (args.output / 'benchmark.json').is_file():
        parser.error('--resume requires an existing benchmark.json from this script')
    original = config.DATA.resolve()
    database = original / 'jobs.sqlite3'
    if database.exists():
        print('Waiting for the application queue to finish before benchmarking', flush=True)
        while True:
            with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as connection:
                active = connection.execute("SELECT count(*) FROM jobs WHERE status IN ('running', 'queued')").fetchone()[0]
            if not active:
                break
            time.sleep(5)
    config.DATA = args.output.resolve()
    if config.DATA.exists() and not args.resume:
        raise ValueError('Use a new output directory to avoid reusing any checkpoints')
    config.initialize()
    if not (config.DATA / 'models').is_symlink():
        (config.DATA / 'models').rmdir()
        (config.DATA / 'models').symlink_to(original / 'models', target_is_directory=True)
    # Network variability excluded; application lyric lookup itself is unchanged and tested separately.
    config.STAGES = ['prepare', 'separate', 'transcribe', 'align', 'pitch', 'chart', 'package']
    store = Store()
    rows = read_json(config.DATA / 'benchmark.json') if args.resume and (config.DATA / 'benchmark.json').exists() else []
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    for repeat in range(args.runs):
        for language in args.languages:
            for mode in args.modes:
                if any(r["mode"] == mode and r["run"] == repeat + 1 and r["language"] == language for r in rows):
                    continue
                source = original / 'jobs' / FIXTURES[language]
                job = store.create('file', 'input.mp4', f'{language}-{mode}-{repeat}')
                folder = config.DATA / 'jobs' / job['id']
                folder.mkdir()
                metadata = read_json(source / 'acquire.json')
                metadata['metadata']['input'] = str(source / 'input.mp4')
                write_json(folder / 'acquire.json', metadata)
                write_json(folder / 'lyrics.json', {'lines': [], 'source': 'transcription'})
                write_json(folder / 'lyrics-source.json', {'lines': [], 'source': 'transcription', 'metadata': metadata['metadata']})
                overrides = {stage: 'cpu' for stage in config.STAGES if stage not in ('chart', 'package')}
                if mode == 'gpu':
                    overrides.update(prepare='videotoolbox', separate='mps', transcribe='mlx', align='mps', pitch='mps')
                if mode == 'auto':
                    overrides = {}
                start = time.monotonic()
                print(f'START {mode} {repeat + 1} {language} {job["id"]}', flush=True)
                Worker(store, overrides).execute(job)
                report = read_json(folder / 'report.json')
                row = {'mode': mode, 'run': repeat + 1, 'language': language, 'job': job['id'],
                       'elapsed_seconds': round(time.monotonic()-start, 2),
                       'stages': {s: {'seconds': r['total_elapsed_seconds'], 'runtime': r.get('runtime'),
                                      'attempts': r.get('attempts')} for s, r in report.items()}}
                rows.append(row)
                write_json(config.DATA / 'benchmark.json', rows)
                print(f'DONE {mode} {repeat + 1} {language}: {row["elapsed_seconds"]} s', flush=True)
    medians = {mode: {lang: statistics.median(r['elapsed_seconds'] for r in rows
                                             if r['mode'] == mode and r['language'] == lang)
                      for lang in args.languages} for mode in args.modes}
    write_json(config.DATA / 'medians.json', medians)
    print(json.dumps(medians, indent=2))


if __name__ == '__main__':
    main()
