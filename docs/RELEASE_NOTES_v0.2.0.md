# Karapincho v0.2.0

October 10, 2026

This feature release adds lyric confirmation, batch song creation, and direct karaoke export to the local UltraStar workflow. It includes the changes made since v0.1.0 and remains a source-only beta for Apple Silicon Macs running macOS 14 or newer.

## Synced lyric confirmation

- Songs pause before audio analysis when LRCLIB cannot confidently provide synced lyrics, including ambiguous matches, missing matches, plain-only lyrics, lookup failures, and insufficient metadata.
- An alert asks for the URL of the correct LRCLIB record. Karapincho validates that the record contains timestamped lyrics before resuming. Supplied lyrics take priority over automatic lookup.
- Other queued songs keep processing while a song waits. Waiting songs survive restart and can be cancelled.
- **Disable waiting when a synced lyric match is uncertain** saves a preference and releases songs already waiting. A song can also continue automatically without changing the preference for other songs.
- LRCLIB lookup retries temporary server errors and can use search when the exact lookup fails.

## Batch creation and processing

- **Add multiple songs** imports up to 50 public YouTube songs from a UTF-8 CSV in file order.
- The CSV template uses `url,artist,song_name,language_code`. Language codes such as `en`, `es`, and `ja` guide processing; three-column CSVs remain supported. All rows are validated before any songs are queued.
- **Quality** retains the established transcription settings. **Fast** uses a smaller model for quicker processing, with an accuracy tradeoff.
- Karapincho keeps macOS awake during song generation and lyric rebuilds, then releases the sleep prevention when processing stops.

## Karaoke export and history

- Choose a karaoke Songs folder once and use **Add to karaoke** to copy completed songs directly into it. Name collisions offer keeping both versions or explicit replacement.
- **Move all to karaoke & remove local files** transfers completed songs, verifies each copy, and removes its local files only after verification. Failed exports retain their local files.
- Completed songs retain export receipts and cleanup status. ZIP download and lyric correction are available under **More options**; cleaned songs require the original source to process again.
- **Clear recent jobs** removes finished history and local working files after confirmation while keeping active jobs and exported karaoke copies.
- The creation interface focuses on active jobs and a paginated history, with progress, elapsed time, and less frequent refreshes while idle.

## Updating and validation

Run `Setup.command` to install dependencies and rebuild the interface, then restart with `Start.command`. The default lyric-confirmation preference is to wait; disable it for unattended processing if desired. Existing job history and the configured Songs folder remain in place.

The automated baseline comprises 239 Python tests and 56 browser checks across four viewport sizes, plus Python lint, dependency consistency, production-build, and release-integrity checks. Browser coverage includes accessibility and keyboard checks, lyric URL resumption, and saved wait preferences.

Model-backed processing, clean source-archive installation, and player checks have not been repeated for this release. The earlier v0.1.0 pipeline evidence and the outstanding manual release gate are documented in [VALIDATION.md](../VALIDATION.md). Automatic lyrics, alignment, Japanese readings, and pitch detection remain best-effort.

Licensing, network behavior, and third-party model terms continue to apply; see [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and [privacy notes](PRIVACY.md).
