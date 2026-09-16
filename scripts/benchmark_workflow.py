# SPDX-License-Identifier: GPL-3.0-or-later
"""Fresh Quality/Fast runs with cached models, including an optional longer stress recording.

Run sequentially on an otherwise idle Mac. No source jobs or external exports are changed.
The long fixture repeats the licensed English recording twice; it is a duration stress test,
not an additional independent accuracy sample.
"""
import argparse
import json
import inspect
import os
import signal
import statistics
import time
from pathlib import Path

from karapincho import config
from karapincho.benchmark import ASSETS, STAGES, baseline
from karapincho.media import read_json, run, write_json
from karapincho.models import japanese_alignment_path, spanish_alignment_path, whisper_path
from karapincho.store import Store
from karapincho.worker import Worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--profiles', nargs='+', choices=['quality', 'fast'], default=['quality', 'fast'])
    parser.add_argument('--fixtures', nargs='+', choices=['es', 'ja', 'en', 'long'], default=['es', 'ja', 'en', 'long'])
    args = parser.parse_args()
    if args.runs < 1 or args.output.exists():
        parser.error('Use a fresh output directory and at least one run.')
    # Fail before creating a run directory or starting timed work if setup is incomplete.
    for profile in args.profiles:
        whisper_path('small' if profile == 'fast' else 'medium')
    if 'es' in args.fixtures:
        spanish_alignment_path()
    if 'ja' in args.fixtures:
        japanese_alignment_path()
    original = config.DATA
    config.initialize()
    config.DATA = args.output.resolve()
    config.initialize()
    (config.DATA / 'models').rmdir()
    (config.DATA / 'models').symlink_to(original / 'models', target_is_directory=True)
    config.STAGES = STAGES
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    fixtures = {fixture['language']: fixture for fixture in baseline()['fixtures']}
    if 'long' in args.fixtures:
        long_video = config.DATA / 'long.mp4'
        run([config.ffmpeg(), '-v', 'error', '-stream_loop', '1', '-i', ASSETS / 'en.mp4', '-c', 'copy', long_video])
        fixtures['long'] = {**fixtures['en'], 'title': 'Auld Lang Syne — repeated duration stress test',
                            'duration': fixtures['en']['duration'] * 2}
    store = Store()
    supports_profile = 'processing_mode' in inspect.signature(Store.create).parameters
    worker = Worker(store)
    def stop(*_):
        worker.stopping.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    rows = []
    for repeat in range(1, args.runs + 1):
        for language in args.fixtures:
            for profile in args.profiles:
                if worker.stopping.is_set():
                    return
                fixture = fixtures[language]
                job = store.create('file', 'input.mp4', fixture['title'],
                                   **({'processing_mode': profile} if supports_profile else {}))
                # Passing mode in the execution snapshot also permits comparison with older Store versions.
                job['processing_mode'] = profile
                folder = config.DATA / 'jobs' / job['id']
                folder.mkdir()
                metadata = {key: fixture[key] for key in ('title', 'artist', 'duration')}
                metadata['input'] = str(config.DATA / 'long.mp4' if language == 'long' else ASSETS / f'{language}.mp4')
                write_json(folder / 'acquire.json', {'metadata': metadata, 'pipeline_version': 1})
                write_json(folder / 'lyrics.json', {'lines': [], 'source': 'transcription'})
                write_json(folder / 'lyrics-source.json', {'lines': [], 'source': 'transcription', 'metadata': metadata})
                write_json(config.DATA / 'progress.json', {'profile': profile, 'fixture': language, 'run': repeat,
                                                          'completed': len(rows), 'job': job['id']})
                print(f'START {repeat} {profile} {language}', flush=True)
                started = time.monotonic()
                try:
                    worker.execute(job)
                finally:
                    worker.terminate()
                if worker.stopping.is_set():
                    return
                report = read_json(folder / 'report.json')
                rows.append({'run': repeat, 'profile': profile, 'fixture': language, 'job': job['id'],
                             'elapsed_seconds': round(time.monotonic() - started, 2),
                             'warnings': store.get(job['id'])['warnings'],
                             'stages': {stage: {'seconds': item['total_elapsed_seconds'],
                                        'model_load_seconds': item.get('model_load_seconds', {}),
                                        'peak_rss_mb': item.get('peak_rss_mb'), 'runtime': item.get('runtime'),
                                        'attempts': item.get('attempts')} for stage, item in report.items()}})
                write_json(config.DATA / 'benchmark.json', rows)
                print(f'DONE {repeat} {profile} {language}: {rows[-1]["elapsed_seconds"]}s', flush=True)
    medians = {profile: {fixture: statistics.median(row['elapsed_seconds'] for row in rows
               if row['profile'] == profile and row['fixture'] == fixture) for fixture in args.fixtures}
               for profile in args.profiles}
    write_json(config.DATA / 'medians.json', medians)
    print(json.dumps(medians, indent=2), flush=True)


if __name__ == '__main__':
    main()
