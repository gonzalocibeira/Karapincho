# Benchmarks

The in-app benchmark runs three bundled recordings three times each with fresh outputs and cached models. It compares medians against the included Apple M2 8 GB baseline. Online lyric lookup and model downloads are excluded.

A score of `1.00×` matches the reference M2 in the selected mode; `2.00×` means twice its processing speed. The result measures processing time, not lyric, timing, or pitch accuracy. Desktop load, temperature, and power state affect results.

The bundled MP4 files are checked against the baseline hashes. Credits and licenses are in `karapincho/benchmark_assets/ATTRIBUTION.md`. Benchmark jobs live under `data/benchmarks/` and do not alter the song library.

Developers can reproduce detailed comparisons with `scripts/benchmark_acceleration.py`, `scripts/compare_acceleration.py`, `scripts/validate_shared_alignment.py`, `scripts/validate_supplied_lyrics.py`, `scripts/benchmark_pitch.py`, and `scripts/validate_accelerated_video.py`.
