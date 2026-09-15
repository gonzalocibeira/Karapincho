# Privacy and network activity

Karapincho has no accounts, analytics, advertising, crash reporter, or telemetry.

## What stays local

- Uploaded MP4 files, extracted audio, model inference, charts, exports, logs, and diagnostics.
- The local SQLite job history and cached model files under `data/`.

## When Karapincho uses the network

- Setup installs dependencies and downloads model weights from their upstream hosts.
- YouTube input contacts YouTube through yt-dlp to retrieve public media and metadata.
- Automatic lyric lookup sends title, artist, album when known, and duration to LRCLIB. Audio is never sent to LRCLIB.

Use `KARAPINCHO_DATA=/absolute/path` to move the local data directory. Stop Karapincho before deleting it.
