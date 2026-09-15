# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare controlled fixture runs, including lyric regressions and pitch differences."""
import argparse
import json
import re
from pathlib import Path

import numpy as np
from karapincho.media import read_json, write_json
from karapincho.lyrics import normalized
from evaluate_excerpts import distance, words

REFERENCES = {
    'es': 'La cucaracha la cucaracha ya no puede caminar porque no tiene porque le falta la patita principal',
    'en': 'Should auld acquaintance be forgot and never brought to mind should auld acquaintance be forgot and days of auld lang syne',
    'ja': 'sakurasakurayayoinosorawamiwatasukagiri',
}


def lyric_errors(folder, language):
    if language == 'ja':
        units = read_json(folder / 'notes.json')['units']
        text = ''.join(u['text'] for u in units if u['phrase'] == units[0]['phrase'])
        hypothesis = re.sub('[^a-z]', '', text.lower())
        reference = REFERENCES[language]
    else:
        transcript = read_json(folder / 'asr-reference.json')
        text = ' '.join(s['text'] for s in transcript['segments'][:2 if language == 'en' else 1])
        hypothesis, reference = words(text), words(REFERENCES[language])
    return {'errors': distance(reference, hypothesis), 'text': text}


def compare(root):
    rows = read_json(root / 'benchmark.json')
    result = []
    for gpu in (r for r in rows if r['mode'] == 'gpu'):
        cpu = next(r for r in rows if r['mode'] == 'cpu' and r['language'] == gpu['language'] and r['run'] == gpu['run'])
        left, right = [root / 'jobs' / row['job'] for row in (cpu, gpu)]
        cpu_errors, gpu_errors = [lyric_errors(folder, gpu['language']) for folder in (left, right)]
        with np.load(left / 'pitch.npz') as a, np.load(right / 'pitch.npz') as b:
            same_time = a['time'].shape == b['time'].shape and np.allclose(a['time'], b['time'], atol=1e-6)
            if same_time:
                mask_a, mask_b = a['confidence'] >= .35, b['confidence'] >= .35
                voiced = mask_a & mask_b & (a['hz'] > 0) & (b['hz'] > 0)
                cents = abs(1200 * np.log2(a['hz'][voiced] / b['hz'][voiced]))
                pitch = {'matching_timeline': True, 'median_difference_cents': float(np.median(cents)),
                         'fraction_within_50_cents': float(np.mean(cents < 50)),
                         'voicing_disagreement_fraction': float(np.mean(mask_a != mask_b))}
            else:
                pitch = {'matching_timeline': False}
        aligned_cpu, aligned_gpu = [read_json(folder / 'aligned.json')['words'] for folder in (left, right)]
        labels_cpu = [normalized(w['word']) for w in aligned_cpu]
        labels_gpu = [normalized(w['word']) for w in aligned_gpu]
        alignment = {'text_preserved': ''.join(labels_cpu) == ''.join(labels_gpu),
                     'cpu_estimated_words': sum(w.get('estimated', False) for w in aligned_cpu),
                     'gpu_estimated_words': sum(w.get('estimated', False) for w in aligned_gpu)}
        if labels_cpu == labels_gpu:
            differences = [abs(a[k] - b[k]) for a, b in zip(aligned_cpu, aligned_gpu) for k in ('start', 'end')]
            alignment['max_boundary_difference_seconds'] = max(differences, default=0)
        result.append({'language': gpu['language'], 'run': gpu['run'], 'cpu_lyrics': cpu_errors,
                       'gpu_lyrics': gpu_errors, 'lyrics_pass': gpu_errors['errors'] <= cpu_errors['errors'],
                       'speedup': cpu['elapsed_seconds'] / gpu['elapsed_seconds'], 'pitch_comparison': pitch,
                       'alignment_comparison': alignment})
    write_json(root / 'comparison.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.root), ensure_ascii=False, indent=2))
