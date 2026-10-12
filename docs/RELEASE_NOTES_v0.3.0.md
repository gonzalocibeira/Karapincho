# Karapincho v0.3.0

October 12, 2026

This feature release adds experimental local lyric recognition and a per-song UI choice, with reproducible accuracy measurements. It remains a source-only beta for Apple Silicon Macs running macOS 14 or newer. **Quality remains the default**; the new recognizer has not passed its promotion gate.

## Experimental Quality in the UI

- Select **Experimental Quality** under **Processing mode** for a YouTube link, MP4 upload, or CSV batch. The choice is saved per song and survives retries, restart, and lyric corrections.
- Existing songs can opt in through **More options → Rebuild in Experimental Quality mode**. Changing modes reuses prepared media, vocal separation, and pitch while rebuilding transcription and its dependent stages.
- The UI explains the English/Spanish improvements, possible Japanese regression, longer processing, and any missing model setup. Ordinary Quality and Fast remain available without the additional models.
- Supplied lyrics and LRCLIB retain precedence, including lyric confirmation and pause/resume behavior. Completed songs are not automatically reprocessed.

## Local lyric recognition

- Pinned Qwen3-ASR-1.7B runs locally through MLX, recognizing both the original mix and separated vocals. Macs with at least 16 GB RAM use FP16; smaller or reduced-memory profiles use the pinned 8-bit checkpoint.
- Bounded, overlapping passages use low-energy boundaries. Reconciliation preserves repeated choruses at distinct timestamps and marks uncertain boundaries.
- Supplied language is honored. Otherwise, independent recording-level language detection and sustained evidence reduce short-segment language flips.
- Disagreement, truncated decoding, alignment failures, and uncovered vocal activity trigger independent Whisper large-v3 CPU recovery. Memory recovery can use medium/int8 with an explicit degradation notice.
- Shared WhisperX alignment checks help select candidates without comparing confidence across recognizers. All returned sentences and character timings are retained, fixing the loss of later sentences. Estimated timings and unresolved wording remain marked.
- Model revisions, recognition settings, and per-song engine choice participate in checkpoint signatures. Optional readiness and passage diagnostics identify models, audio sources, retries, and uncertainty.

## Measured accuracy and remaining gates

The frozen evaluation split contains ten recordings from English/Spanish Jam-ALT and human Japanese PJS, separate from tuning recordings. Reference lyrics stay outside inference. On the 24 GB Apple Silicon Mac:

| Metric | Previous Quality | Experimental FP16 | Experimental 8-bit |
|---|---:|---:|---:|
| English WER | 49.74% | 26.60% | 29.03% |
| Spanish WER | 72.58% | 11.75% | 12.67% |
| Japanese CER | 12.15% | 12.62% | 12.62% |
| Language-balanced error | 44.82% | 16.99% | 18.11% |

FP16 reduced language-balanced error by **62.1%** and reduced total omissions and insertions. Both precision profiles nevertheless **fail the promotion gate** because Japanese error rose from 26 to 27 units out of 214. Some songs and per-language insertion counts still regress. This small suite does not establish catalogue-wide accuracy. Full per-language results, timing coverage, and remaining failures are in [Lyric accuracy](LYRIC_ACCURACY.md) and [the validation artifact](accuracy/validation-2026-10-12.json).

The automated baseline comprises **297 Python tests and 72 browser checks** across four viewport sizes, plus lint, dependency consistency, production build, and release integrity. All three bundled recordings completed structural/ZIP export checks on the 24 GB Mac. Actual 8 GB memory recovery, player checks for the new pipeline, and clean source-archive installation remain unverified. Running 8-bit inference on the 24 GB Mac does not validate 8 GB hardware.

## Updating

Run `Setup.command` to update dependencies and rebuild the interface, then restart with `Start.command`. Existing history, completed songs, and the configured karaoke Songs folder remain in place.

Experimental Quality needs optional setup from the Karapincho folder:

```bash
.venv/bin/python -m pip install -r requirements-gpu.lock
.venv/bin/python -m karapincho.setup_models --quality
```

Restart normally, then select **Experimental Quality** in the UI. Additional model downloads are approximately 8 GB on Macs with at least 16 GB RAM, or 5 GB on an 8 GB Mac. Reserve at least 20 GB free for optional setup and 30 GB including working files. Substantially longer processing is expected. The existing environment override remains supported for evaluation scripts; see [setup details](LYRIC_ACCURACY.md).

Licensing, network behavior, and model terms continue to apply; see [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md), [privacy notes](PRIVACY.md), and [VALIDATION.md](../VALIDATION.md).
