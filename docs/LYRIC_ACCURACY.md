# Local lyric accuracy

The new `quality-v2` pipeline is available for evaluation. It is **not yet promoted** to the automatic Quality default. The release gate requires an independently measured 30% reduction in language-balanced error, no language regression, fewer omitted lyric units, and no increase in inserted units. Fast mode retains the existing small Whisper model.

## Install and activate

From the project directory, with Python 3.12 and the existing AI setup:

```bash
.venv/bin/python -m pip install -r requirements-gpu.lock
.venv/bin/python -m karapincho.setup_models --quality
KARAPINCHO_TRANSCRIPTION=quality-v2 ./Start.command
```

Allow approximately 8 GB of additional model downloads on Macs with at least 16 GB RAM, or 5 GB on an 8 GB Mac, beyond the existing approximately 7 GB model set. Reserve at least 20 GB free for this optional setup and 30 GB including working files. Setup downloads the profile appropriate for the Mac; it does not download both Qwen variants. The explicit `--quality` option also load-checks models. `KARAPINCHO_TRANSCRIPTION=legacy` selects the old recognizer for comparisons; `auto` remains the old default until promotion. Restart the app after changing this setting.

The existing 8 GB support remains available through CPU recovery. The new 8-bit Qwen profile must be evaluated separately; running it on a 24 GB machine is not validation of an actual 8 GB Mac. `/api/health` includes an additive `recognition` object with the selected engine, validation state, cached-model readiness, and missing optional dependencies. Basic application readiness remains separate.

## Recognition behavior

The pinned [Qwen3-ASR-1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) recognizer runs through [mlx-qwen3-asr](https://github.com/moona3k/mlx-qwen3-asr) 0.4.4. Macs with at least 16 GB RAM use unquantized FP16 weights; smaller and reduced-memory profiles use the pinned 8-bit conversion. Published singing evaluations motivate this choice, but do not establish accuracy on this app's inputs.

An independent Whisper encoder establishes the recording language before Qwen decoding, unless the user supplied it. This avoids an observed failure in unconstrained Qwen singing recognition: English translations or English language labels on Spanish/Japanese vocals. Switching languages requires two consecutive substantive windows. Short mixed-language phrases remain a limitation.

Quality v2 decodes original audio and separated vocals in bounded windows with shared low-energy boundaries and overlapping context. It releases the recognition model, then evaluates candidates with the existing CPU WhisperX aligners. Disagreement, incomplete decoding, failed alignment, or uncovered vocal activity triggers independent large-v3 CPU beam-search recovery. Models are loaded sequentially. MLX/backend failures use the worker's existing isolated CPU recovery; memory recovery can fall back to medium, with a visible degradation warning.

Selection prefers agreement between independent recognizers, then agreement across audio views, followed by shared alignment coverage and scores, with original-mix Qwen winning ties. This prevents a lone, confidently aligned hallucination from displacing wording supported by both audio views. It never compares confidence values from different recognizers. Agreement between two passes of Qwen is correlated evidence; successful alignment is timing evidence, not proof of correct wording. Unresolved wording and estimated timings remain marked. Repeated lyrics at distinct times are preserved; only matching words with overlapping times are deduplicated. WhisperX can split one input into several sentences; all returned sentences and their character timings are retained.

Existing supplied lyrics and LRCLIB retain precedence. Recognition metadata and passage diagnostics appear in the transcript, ASR reference, and stage reports. Cached, verified word/character alignment can be reused; externally supplied text still follows the existing alignment path. Recognition policy and immutable model revisions participate in checkpoint signatures. Completed songs are not rewritten automatically.

## Independent accuracy suite

`docs/accuracy/corpus.json` freezes disjoint tuning/evaluation IDs before tuning. The initial suite has eight modern English/Spanish Jam-ALT songs and ten human Japanese PJS recordings: eight tuning recordings and ten evaluation recordings. The three bundled recordings separately check full exports; Sakura is synthesized and is not a substitute for human Japanese evaluation. This is a small release regression suite, not a catalogue-wide accuracy guarantee.

Sources:

- [Jam-ALT](https://huggingface.co/datasets/jamendolyrics/jam-alt), revision `28302224954ef050fe752d1628dd9bac4fc8c02b`, provides lyrics and manually corrected line timings. It does not provide word-level reference times.
- [PJS v1.1](https://sites.google.com/site/shinnosuketakamichi/research-topics/pjs_corpus), archive SHA-256 `683c00253ee35a62d50de0375bb9d8e003a74338d4ce3495ac3f7ad096abc1ca`, provides human singing. Original-script text is from the pinned [Voice Statistics sentences](https://github.com/voice-statistics/voice-statistics.github.com/blob/22923912010c358a4a044702e78b343f3ba8123f/assets/doc/balance_sentences.txt); [Wikipedia source attribution and modifications](https://github.com/voice-statistics/voice-statistics.github.com/blob/22923912010c358a4a044702e78b343f3ba8123f/assets/doc/sentence_id_wikipedia_urls.txt). PJS is one singer performing short, clean a cappella passages and does not represent modern Japanese mixes.

```bash
.venv/bin/python scripts/prepare_lyric_accuracy.py
.venv/bin/python scripts/benchmark_lyric_accuracy.py --profile legacy --output .cache/accuracy-before
.venv/bin/python scripts/benchmark_lyric_accuracy.py --profile quality-v2 --output .cache/accuracy-after
.venv/bin/python scripts/evaluate_lyric_accuracy.py --before .cache/accuracy-before/accuracy.json --after .cache/accuracy-after/accuracy.json --output .cache/accuracy-comparison.json
```

Use `--split tuning` to develop heuristics. `--ids` supports smoke subsets; incomplete or tuning runs cannot pass the gate. Use a fresh output directory each time. Preparation and separation are shared across recognizers. References stay in a separate corpus manifest and are read for scoring only after inference exits; inference jobs contain audio and language codes, never reference lyrics. Runtime processing uses cached models with network access disabled.

On a larger Mac, use `--profile quality-v2 --reduced` with a fresh output folder to evaluate the pinned 8-bit recognizer on the same split. Install that checkpoint separately if necessary with `qwen_path(True, download=True)` from `karapincho.models`. This measures quantization accuracy and runtime on the actual host; it does not simulate an 8 GB Mac or validate its memory recovery. An 8 GB Mac selects this checkpoint automatically. Explicit reduced-profile requests also participate in checkpoint signatures.

Reports contain English/Spanish WER, Japanese original-script CER, substitutions, deletions, insertions, and matched-line boundary errors with reference coverage. Accents and original spelling are retained. Japanese orthographic variants count as errors; CER is not a measure of romaji pronunciation quality. Missing lyrics remain in the denominator. PJS has no lexical word-time reference in this suite, so no word-timing accuracy is claimed.

Corpus fingerprints include immutable source versions, audio hashes, reference text, and annotations, while excluding machine-specific cache paths. Both reports must contain every frozen evaluation ID exactly once. Comparing the wrong profiles, different reference counts, incomplete subsets, or tuning results cannot satisfy the release gate.

Promotion requires the complete frozen evaluation split to pass. An actual 8 GB Mac remains a separate runtime validation requirement. Detailed measurements and remaining failures are recorded alongside the accuracy reports before promotion.

## Measured results — 2026-10-12

The complete frozen evaluation split was run on a 24 GB Apple Silicon Mac. Full results, edit counts, per-recording timing coverage, pinned models, and runtime diagnostics are in [the validation artifact](accuracy/validation-2026-10-12.json). No reference lyrics were passed to inference.

| Metric | Legacy Quality | Qwen FP16 pipeline | Qwen 8-bit pipeline |
|---|---:|---:|---:|
| English WER | 49.74% | 26.60% | 29.03% |
| Spanish WER | 72.58% | 11.75% | 12.67% |
| Japanese CER | 12.15% | 12.62% | 12.62% |
| Language-balanced error | 44.82% | 16.99% | 18.11% |

FP16 reduced language-balanced error by **62.1%**. The release gate **failed** because Japanese error increased from 26 to 27 units out of 214. This violates the agreed no-regression criterion; the new default remains unpromoted.

- legacy: 482 omitted units; 79 inserted units.
- fp16: 181 omitted units; 35 inserted units.
- 8bit: 185 omitted units; 56 inserted units.

The omission/insertion gate compares corpus-wide counts. Per-language counts are published in the artifact: FP16 English insertions increased from 9 to 17, and Japanese insertions from 3 to 7, despite the lower corpus-wide insertion count.

8-bit reduced language-balanced error by **59.6%**. Its release gate also **failed** because Japanese error regressed. These results do not validate 8 GB hardware.

| Evaluation recording | Legacy error | FP16 error | 8-bit error |
|---|---:|---:|---:|
| `jam-en-Cortez_-_Feel__Stripped_` | 27.53% | 9.55% | 13.76% |
| `jam-en-Explosive_Ear_Candy_-_Like_The_Sun` | 68.31% | 40.85% | 41.78% |
| `jam-es-Besando_Sapos_-_Dream_Tabu` | 73.68% | 15.79% | 16.23% |
| `jam-es-CLUB_DESTINO__-_Pensando_en_ti_-_CLUB_DESTINO` | 71.36% | 7.28% | 8.74% |
| `pjs005` | 15.79% | 19.30% | 19.30% |
| `pjs006` | 12.50% | 8.33% | 8.33% |
| `pjs007` | 0.00% | 5.13% | 5.13% |
| `pjs008` | 18.92% | 8.11% | 8.11% |
| `pjs009` | 25.93% | 33.33% | 33.33% |
| `pjs010` | 0.00% | 0.00% | 0.00% |

The harder English pop recording still has 40.85% FP16 WER, so the improvement is not sufficient for unchecked exports. Japanese `pjs005`, `pjs007`, and `pjs009` regress relative to legacy in the FP16 run; other Japanese utterances improve or stay unchanged. Uncertain passages and estimated timings remain marked rather than rewritten.

All three bundled recordings completed final structural/ZIP export checks. The pinned 8-bit model completed bundled smoke checks in all three languages, and an actual CPU medium/int8 low-memory recovery export completed on the 24 GB host. All 290 backend tests, lint, dependency checks, release integrity checks, and the frontend production build passed. Actual 8 GB memory recovery and karaoke-player visual checks for this new policy remain unverified.
