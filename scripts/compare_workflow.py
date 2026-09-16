# SPDX-License-Identifier: GPL-3.0-or-later
"""Summarize workflow timings and compare Quality outputs with repeated baseline runs.

Pitch differences are reported in cents on mutually voiced frames. Transcription
edit distance is a baseline comparison, not accuracy against annotated lyrics.
"""
import argparse
import json
import re
import sqlite3
import statistics
from pathlib import Path

import numpy as np

from karapincho.chart import validate_chart
from karapincho.media import read_json, write_json


def entries(root):
    rows = read_json(root / 'benchmark.json')
    with sqlite3.connect(f'file:{root / "jobs.sqlite3"}?mode=ro', uri=True) as db:
        jobs = [row[0] for row in db.execute('SELECT id FROM jobs ORDER BY created')]
    for index, row in enumerate(rows):
        row['fixture'] = row.get('fixture', row.get('language'))
        row['profile'] = row.get('profile', 'baseline')
        row['folder'] = root / 'jobs' / row.get('job', jobs[index])
    return rows


def words(folder):
    transcript = read_json(folder / 'transcript.json')
    return re.sub(r'[^\w]', '', ''.join(segment['text'] for segment in transcript['segments']).lower())


def distance(left, right):
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def compare(before, after):
    with np.load(before / 'pitch.npz') as first, np.load(after / 'pitch.npz') as second:
        same_grid = np.array_equal(first['time'], second['time'])
        result = {'same_pitch_grid': same_grid}
        if same_grid:
            first_voiced = (first['confidence'] >= .35) & (first['hz'] > 0)
            second_voiced = (second['confidence'] >= .35) & (second['hz'] > 0)
            voiced = first_voiced & second_voiced
            cents = np.abs(1200 * np.log2(second['hz'][voiced] / first['hz'][voiced]))
            result.update(same_energy=np.array_equal(first['energy'], second['energy']),
                          baseline_voiced_frames=int(first_voiced.sum()),
                          compared_voiced_frames=int(second_voiced.sum()),
                          voicing_disagreement_fraction=float(np.mean(first_voiced != second_voiced)),
                          pitch_median_cents=float(np.median(cents)) if len(cents) else None,
                          pitch_p95_cents=float(np.percentile(cents, 95)) if len(cents) else None)
    first_words, second_words = words(before), words(after)
    result['transcription_character_edit_distance'] = distance(first_words, second_words)
    result['transcription_baseline_characters'] = len(first_words)
    first_aligned = read_json(before / 'aligned.json')['words']
    second_aligned = read_json(after / 'aligned.json')['words']
    first_tokens = [re.sub(r'\W', '', word['word'].lower()) for word in first_aligned]
    second_tokens = [re.sub(r'\W', '', word['word'].lower()) for word in second_aligned]
    result['same_aligned_word_sequence'] = first_tokens == second_tokens
    if first_tokens and first_tokens == second_tokens:
        differences = [abs(left[key] - right[key]) for left, right in zip(first_aligned, second_aligned)
                       for key in ('start', 'end')]
        result['alignment_boundary_median_seconds'] = float(np.median(differences))
        result['alignment_boundary_p95_seconds'] = float(np.percentile(differences, 95))
        result['alignment_boundary_max_seconds'] = max(differences)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    before, after = entries(args.before), entries(args.after)
    fixtures = sorted({row['fixture'] for row in after})
    timings, quality = {}, {}
    for fixture in fixtures:
        reference = [row for row in before if row['fixture'] == fixture]
        if not reference:
            raise ValueError(f'Missing baseline for {fixture}')
        timings[fixture] = {'baseline': statistics.median(row['elapsed_seconds'] for row in reference)}
        for profile in sorted({row['profile'] for row in after}):
            selected = [row for row in after if row['fixture'] == fixture and row['profile'] == profile]
            if selected:
                timings[fixture][profile] = statistics.median(row['elapsed_seconds'] for row in selected)
        quality[fixture] = {
            'baseline_repeat_variation': [
                {'runs': [left['run'], right['run']], **compare(left['folder'], right['folder'])}
                for index, left in enumerate(reference) for right in reference[index + 1:]
            ],
            'quality_runs': [],
            'fast_runs': [],
        }
        for row in [row for row in after if row['fixture'] == fixture]:
            folder = row['folder']
            validate_chart((folder / 'song.txt').read_text(encoding='utf-8'), folder)
            if fixture == 'ja':
                lines = (folder / 'song.txt').read_text(encoding='utf-8').splitlines()
                assert all(line.split(' ', 4)[4].isascii() for line in lines if line.startswith((': ', 'F ')))
            if row['profile'] in ('quality', 'fast'):
                quality[fixture][row['profile'] + '_runs'].append({
                    'run': row['run'], 'comparisons': [
                        {'baseline_run': item['run'], **compare(item['folder'], folder)} for item in reference
                    ],
                    'alignment_quality': read_json(folder / 'align.json').get('alignment_quality'),
                    'warnings': row.get('warnings', []),
                })
    profiles = sorted(set.intersection(*[set(values) for values in timings.values()]))
    totals = {profile: sum(values[profile] for values in timings.values()) for profile in profiles}
    result = {'median_seconds': timings, 'sum_of_fixture_medians': totals,
              'fast_reduction_vs_baseline': 1 - totals['fast'] / totals['baseline'] if 'fast' in totals else None,
              'fast_reduction_vs_quality': 1 - totals['fast'] / totals['quality'] if 'fast' in totals else None,
              'quality_comparison': quality,
              'caution': 'Baseline comparisons do not establish accuracy against independently annotated singing.'}
    write_json(args.output, result)
    print(json.dumps({key: value for key, value in result.items() if key != 'quality_comparison'}, indent=2))


if __name__ == '__main__':
    main()
