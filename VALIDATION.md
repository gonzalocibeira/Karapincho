# Karapincho v0.3.0 validation

This document records the release baseline and its limits. It is evidence of tested behavior, not a guarantee that automatic lyrics, timings, or melody will be correct for every recording.

## Automated baseline

The release gate runs:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check karapincho tests scripts
.venv/bin/python -m pip check
npm ci --prefix frontend
npm run build --prefix frontend
npm run test:e2e --prefix frontend
.venv/bin/python scripts/check_release.py
```

The v0.3.0 automated baseline comprises 297 Python tests and 72 Playwright checks. Python lint, dependency consistency, release integrity, and the production TypeScript/Vite build are also checked. The browser checks cover 360 px, 768 px, standard desktop, and large desktop layouts, including keyboard navigation, exact setup diagnostics, and automated serious/critical accessibility rules. Coverage includes API/session protection, upload validation, cancellation, restart/checkpoints, deletion safety, worker isolation, acceleration recovery, lyric sources and correction, Japanese romanization, chart validation, benchmark scheduling, and media timelines. It also covers uncertain LRCLIB matches pausing before analysis, synced-lyric URL validation and resumption, persisted wait preferences, CSV metadata and language codes, karaoke transfer, and history cleanup.

New recognition regressions cover overlapping boundaries, repeated choruses, silence and quiet singing, language stability, truncated decoding, invalid timestamps, memory/backend recovery, and alignment reuse. Experimental Quality UI checks cover URL/MP4/CSV submission, per-song mode labels and rebuilds, unchanged default selection, missing-model setup, and keyboard access to scrollable setup commands. Per-song settings are exercised through isolated runtime selection, provenance, retries, lyric rebuilds, and checkpoint reuse.

## Lyric accuracy evidence for v0.3.0

The complete frozen evaluation split was run with legacy Quality, Experimental FP16, and Experimental 8-bit on a 24 GB Apple Silicon Mac. FP16 reduced language-balanced error from 44.82% to 16.99%, a 62.1% relative reduction, with fewer total omissions and insertions. Japanese CER increased from 12.15% to 12.62%, so both experimental profiles fail the agreed no-language-regression gate. The automatic default remains legacy Quality.

All three bundled recordings completed final structural/ZIP exports with the new pipeline. The pinned 8-bit model completed bundled checks in all three languages, and a CPU medium/int8 recovery export completed on the same 24 GB host. Actual 8 GB memory recovery, player visual checks for this pipeline, and clean source-archive installation remain unverified. The independent suite is small; PJS represents one singer's short, clean a cappella passages. See [LYRIC_ACCURACY.md](docs/LYRIC_ACCURACY.md) for source pins, reproduction commands, timing-reference limits, per-language failures, and [the sanitized evidence](docs/accuracy/validation-2026-10-12.json).

## Real pipeline evidence

The evidence below was collected for v0.1.0 and remains historical. It does not establish player compatibility or timing accuracy for the experimental pipeline above; the manual release gate remains outstanding.

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

Before tagging v0.3.0, test the GitHub source archive—not the development checkout—on clean Apple Silicon environments running macOS 14 and the current macOS release. Verify setup, launch, MP4 upload, a permitted public YouTube URL, LRCLIB lookup, song completion, CSV queueing with language codes, uncertain-lyric alerts and URL resumption, disabling lyric waits, direct and bulk karaoke export, cleanup, download, folder opening, cancellation, retry, rebuild, deletion, restart recovery, and benchmark cancellation. Include optional model setup, Experimental Quality selection and mode rebuilds, readable missing-model diagnostics, and playback of the new pipeline's exports. Validate memory recovery on an actual 8 GB Mac before claiming that profile supported by the new evidence.

Also verify readable failures for unsupported architecture/OS, less than 10 GB free space, missing prerequisites, unavailable network, unavailable optional MLX runtime, blocked YouTube downloads, invalid media, and empty vocals. Record the tested hardware, operating systems, setup duration, installed footprint, and any deviations in the v0.3.0 release notes. Promotion of Experimental Quality additionally requires the independent lyric accuracy gate to pass.
