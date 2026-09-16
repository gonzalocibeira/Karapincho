# Benchmarks

The in-app benchmark runs three bundled recordings three times each with fresh outputs and cached models. It compares medians against the included Apple M2 8 GB baseline. Online lyric lookup and model downloads are excluded.

A score of `1.00×` matches the reference M2 in the selected mode; `2.00×` means twice its processing speed. The result measures processing time, not lyric, timing, or pitch accuracy. Desktop load, temperature, and power state affect results.

The bundled MP4 files are checked against the baseline hashes. Credits and licenses are in `karapincho/benchmark_assets/ATTRIBUTION.md`. Benchmark jobs live under `data/benchmarks/` and do not alter the song library.

Developers can reproduce detailed comparisons with `scripts/benchmark_acceleration.py`, `scripts/compare_acceleration.py`, `scripts/validate_shared_alignment.py`, `scripts/validate_supplied_lyrics.py`, `scripts/benchmark_pitch.py`, and `scripts/validate_accelerated_video.py`.

## Quality and Fast workflow comparison

Run on an otherwise idle Mac with cached models:

```bash
.venv/bin/python scripts/benchmark_workflow.py --output /tmp/karapincho-workflow-benchmark
```

This performs three fresh runs per profile and recording. `--profiles quality fast`, `--fixtures es ja en long`, and `--runs 3` are the defaults. Output contains per-stage time, model-loading time, peak memory, backend/recovery information, warnings, and median total processing times. Use a new output directory for each comparison. Online lyrics and model downloads are excluded. The `long` recording repeats the licensed English fixture twice as a duration stress test; it is not an independent accuracy sample.

Fast targets a 20% reduction in median total time, but model selection alone does not guarantee it on every recording or Mac. Compare lyric content, timing, pitch, and valid UltraStar output as well as speed. Keep baseline results from the same hardware and environment; the bundled historic M2 result is not a substitute for a controlled before/after run.

After completing both runs, summarize timings and compare Quality outputs:

```bash
.venv/bin/python scripts/compare_workflow.py --before /tmp/karapincho-before --after /tmp/karapincho-after --output /tmp/karapincho-comparison.json
```

The comparison validates packages and Japanese romanization, reports transcription character differences, and compares pitch variation with repeated baseline runs. Character differences measure agreement with the baseline, not accuracy against annotated lyrics. The aggregate speed comparison uses the sum of each recording's three-run median; retain the per-recording results when reporting it.
