# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolate MPS alignment quality from upstream transcription differences."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from karapincho import config
from karapincho.media import read_json, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('benchmark', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows = read_json(args.benchmark / 'benchmark.json')
    results = []
    env = {**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
    for language in ('es', 'ja', 'en'):
        row = next(r for r in rows if r['mode'] == 'cpu' and r['language'] == language and r['run'] == 1)
        source = (args.benchmark / 'jobs' / row['job']).resolve()
        outputs = []
        for backend in ('cpu', 'mps'):
            folder = args.output / f'{language}-{backend}'
            folder.mkdir()
            for name in ('transcript.json', 'vocals.wav', 'original.wav', 'asr-reference.json'):
                (folder / name).symlink_to(source / name)
            subprocess.run([sys.executable, '-m', 'karapincho.stage', 'align', str(folder), '--backend', backend],
                           cwd=config.ROOT, env=env, check=True)
            assert read_json(folder / 'align.json')['runtime']['backend'] == backend
            outputs.append(read_json(folder / 'aligned.json')['words'])
        left, right = outputs
        labels_match = [w['word'] for w in left] == [w['word'] for w in right]
        differences = [abs(a[k]-b[k]) for a, b in zip(left, right) for k in ('start', 'end')] if labels_match else []
        result = {'language': language, 'word_sequence_equal': labels_match,
                  'max_boundary_difference_seconds': max(differences, default=None),
                  'cpu_estimated_words': sum(w.get('estimated', False) for w in left),
                  'gpu_estimated_words': sum(w.get('estimated', False) for w in right)}
        results.append(result)
        write_json(args.output / 'results.json', results)
        print(json.dumps(result), flush=True)
        assert labels_match and result['max_boundary_difference_seconds'] <= .04
        assert result['gpu_estimated_words'] <= result['cpu_estimated_words']


if __name__ == '__main__':
    main()
