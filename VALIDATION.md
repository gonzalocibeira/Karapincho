# Karapincho v0.1.0 validation

This document records the release baseline and its limits. It is evidence of tested behavior, not a guarantee that automatic lyrics, timings, or melody will be correct for every recording.

## Automated baseline

The release gate runs:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check karapincho tests scripts
.venv/bin/python -m pip check
npm ci --prefix frontend
npm run build --prefix frontend
```

The current release tree passes 142 Python tests with two upstream Starlette deprecation warnings; Python lint, dependency consistency, and the production TypeScript/Vite build also pass. Twelve Playwright checks cover 360 px, 768 px, standard desktop, and large desktop layouts, including keyboard navigation, exact setup diagnostics, and automated serious/critical accessibility rules. Coverage also includes API/session protection, upload validation, cancellation, restart/checkpoints, deletion safety, worker isolation, acceleration recovery, lyric sources and correction, Japanese romanization, chart validation, benchmark scheduling, and media timelines.

## Real pipeline evidence

Three openly licensed recordings complete the full pipeline and are bundled in hash-verified form for repeatable benchmarks:

| Recording | Language | Prepared duration | Result |
|---|---|---:|---|
| La Cucaracha | Spanish | 43.49 s | Valid four-file package and ZIP |
| Sakura Sakura | Japanese | 28.94 s | Valid package with ASCII romaji |
| Auld Lang Syne | English/Scots | 141.55 s | Valid four-file package and ZIP |

Credits and license terms are in `karapincho/benchmark_assets/ATTRIBUTION.md`. These fixtures establish execution coverage, not catalogue-wide accuracy.

UltraStar Deluxe 2025.4.0 on macOS loaded the generated Spanish and Japanese packages in Jukebox mode; video and highlighted lyrics rendered. WorldParty was not runtime-tested. The exports follow the shared classic format, but structural validation does not replace testing in every player.

Synthetic pitch fixtures evaluate C4, E4, and G4 tones separated by silence. CPU and MPS runs kept evaluated voiced frames within 50 cents and did not voice the reference silence. Shared CPU/MPS alignment checks preserved word sequences and boundaries on the three fixtures.

The bundled M2 benchmark reports controlled CPU and accelerated medians over three fresh runs per recording. Model downloads and online lyric lookup are excluded; timing measures processing speed, not quality.

## Known limitations

- Automatic lyric lookup, transcription, forced alignment, Japanese dictionary readings, syllable/mora splitting, and pitch extraction remain best-effort.
- Names, unusual kanji, rapid vocals, overlapping singers, background speech, poor recordings, and mixed-language passages can be inaccurate.
- Simultaneous singers produce one estimated lead chart. Uncertain notes may become freestyle notes.
- Real-song pitch and alignment have not been measured against a broad independently annotated corpus.
- YouTube may block public downloads. Authentication, cookies, playlists, and live streams are intentionally unsupported.
- v0.1 supports Apple Silicon and macOS 14+. Intel Macs, Windows, Linux, remote hosting, and multi-user operation are unsupported.
- The optional MLX transcription runtime may be unavailable on older compatible macOS releases; CPU recovery remains supported.
- Setup and model-backed checks require several gigabytes of downloads and are intentionally excluded from CI.

## Manual release gate

Before tagging v0.1.0, test the GitHub source archive—not the development checkout—on clean Apple Silicon environments running macOS 14 and the current macOS release. Verify setup, launch, MP4 upload, a permitted public YouTube URL, LRCLIB lookup, song completion, download, folder opening, cancellation, retry, rebuild, deletion, restart recovery, and benchmark cancellation.

Also verify readable failures for unsupported architecture/OS, less than 10 GB free space, missing prerequisites, unavailable network, unavailable optional MLX runtime, blocked YouTube downloads, invalid media, and empty vocals. Record the tested hardware, operating systems, setup duration, installed footprint, and any deviations in the v0.1.0 release notes.
