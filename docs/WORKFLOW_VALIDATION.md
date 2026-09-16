# Creation and karaoke handoff validation

## Automated checks

Validated on Apple M2, 8 GB memory, macOS 27:

- Backend: 174 tests passed, including 19 handoff tests. Coverage includes checkpoint reuse across mode changes, restart, cancellation, retry, lyric rebuild, migration of existing jobs, and session-token protection.
- Browser: 32 checks passed across 360, 768, 1440, and 1920 pixel widths. Checks include keyboard navigation, accessible names and contrast, creation, queue activity, export collisions, cleanup, pagination, and adaptive polling with hidden-page suspension.
- Python lint, dependency consistency, frontend production build, and release asset integrity checks passed.
- Real completed English, Spanish, and Japanese packages from both updated modes were exported twice and then cleaned locally. All six export receipts remained stable; external package fingerprints were unchanged after cleanup. Fast packages also exercised Keep both against existing Quality exports of the same songs.

Export failure tests cover picker cancellation, unavailable folders, insufficient space, interrupted copies, replacement rollback, interrupted publication recovery, concurrent destination creation, external edits, and repeated export. These automated picker tests substitute the native dialog; they do not establish native UI behavior.

## Runtime release gates

Native folder-picker interaction and UltraStar Deluxe playback remain unverified: the Mac was locked during this validation session. UltraStar Deluxe 2025.4.0 is installed. WorldParty has not been runtime-tested. Package validation alone is not a playback compatibility claim.

Live YouTube acquisition has not been exercised in this session. URL and MP4 submission contracts are covered by tests; processing comparisons use the licensed bundled recordings with cached models and no online lyric lookup.

## Performance and quality evidence

The controlled original-pipeline baseline and updated Quality/Fast measurements are run sequentially on the same Mac. See [BENCHMARKS.md](BENCHMARKS.md) for reproduction and comparison commands. The longer fixture repeats the English recording twice and tests duration handling, not another independent song.

### Three-run medians

| Recording | Original pipeline | Quality | Fast |
|---|---:|---:|---:|
| Spanish, La Cucaracha | 153.92 s | 121.34 s | 64.67 s |
| Japanese, Sakura Sakura | 87.32 s | 70.38 s | 53.19 s |
| English, Auld Lang Syne | 269.98 s | 243.44 s | 150.27 s |
| Sum of recording medians | 511.22 s | 435.16 s | 268.13 s |

Fast reduced the aggregate by **47.6% against the original pipeline** and **38.4% against updated Quality**, passing the 20% target for these fixtures. Quality was **14.9% lower** in this run set. These are observed results on this Mac, not guarantees for other songs or hardware. Individual timings, memory, backend attempts, model-loading measurements, and output comparisons are retained in [the benchmark evidence](benchmarks/workflow-2026-09-16.json).

Transcription and pitch stage medians improved in all three recordings. The original pipeline attempted MLX transcription and then retried on CPU in every reference run; the updated 8 GB profile avoids that first attempt. Quality retains the medium model and beam size 5. The pitch model and decoding policy are unchanged.

Each of the nine Quality outputs matched the normalized lyric text of at least one repeated baseline output. Every comparison had identical pitch timestamps, RMS energy, and voiced-frame counts. Pitch differences were approximately 15–18 cents at the 95th percentile, close to the baseline's own repeated-run variation. All 18 updated packages passed validation; Japanese note text was ASCII romaji. Spanish occasionally misdetected a short segment's language and estimated its alignment in both original and updated Quality runs; that existing limitation remains visible in quality notices.

English and Japanese Quality word boundaries were identical to baseline. Two Spanish Quality runs exactly matched a baseline timing variant; the other had a 52 ms 95th-percentile boundary difference (181 ms maximum) against its matching lyric sequence. The baseline itself varied by up to 1.008 seconds on an estimated Spanish boundary. The comparison reports timing only when the normalized word sequence matches, so Fast's missing lyrics are not mistaken for alignment improvements.

Transcription agreement with baseline is distinct from independently annotated lyric accuracy. Original reports expose stage timing and peak RSS but no separate model-loading breakdown; updated reports include that breakdown. Peak RSS is per subprocess, not total application plus GPU shared memory. Early runs with incomplete caches were excluded and the full baseline was repeated with caches complete.

Fast omitted repeated Spanish lines, changed several Japanese words/readings, and substituted or omitted English phrases (including spurious “I'm sorry” text). These are material lyric differences, not merely punctuation changes. Quality remains the default; Fast users should review the lyrics and use correction or rebuild in Quality before export when needed. Existing baseline lyric errors also remain, especially in the historical English recording and inferred Japanese readings.

### Longer recording and independent pitch check

The doubled English recording completed and passed package validation in all three configurations: original pipeline 402.84 seconds, Quality 369.36 seconds, Fast 261.14 seconds. Quality also matched the original normalized lyric text and word boundaries exactly. These are single stress runs, not three-run medians or an additional independent accuracy sample.

Real CPU and Metal torchcrepe checks on synthetic C4/E4/G4 harmonic tones passed: all 390 evaluated voiced frames were within 50 cents, voiced-reference coverage was 100%, and there were no falsely voiced silence frames. Median errors were 5.82 cents on CPU and 5.54 cents on Metal. This checks pitch implementation behavior, not accuracy on all human singing.
