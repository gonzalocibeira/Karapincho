# Karapincho v0.1.0

Karapincho turns a permitted public YouTube video or an uploaded MP4 into a ready-to-sing classic UltraStar package. This first public release is source-only.

## Compatibility and installation

- Apple Silicon Mac with macOS 14 or newer.
- Python 3.12, Node.js 22+, at least 10 GB free, and 20 GB recommended.
- Download the source archive, move it to a permanent folder, then open `Setup.command` followed by `Start.command`.
- Setup downloads roughly 7 GB of dependencies and model weights. A signed/notarized app or DMG is not included.
- CPU processing is supported. MPS acceleration is supported where available; optional MLX transcription can be unavailable on some otherwise supported macOS versions without preventing CPU use.

## Free-software rights

Karapincho source code is licensed under GPL-3.0-or-later. Personal and commercial use, modification, forks, and redistribution are permitted under the GPL's terms, including the corresponding-source requirements for distributed derivatives. The software is provided without warranty or a support commitment.

Third-party media, dependencies, and downloaded weights retain independent terms. The default Demucs pretrained weight is research-only according to its upstream maintainer; commercial users must substitute separation weights carrying commercial-use permission. See `THIRD_PARTY_NOTICES.md`.

## Privacy and network activity

Uploaded files and AI inference remain on the Mac, and Karapincho includes no telemetry. YouTube URL ingestion contacts YouTube. Automatic lyric lookup sends available song metadata, but not audio, to LRCLIB. Setup downloads packages and model weights from their upstream hosts.

## Accuracy limits

Lyrics, word alignment, Japanese readings, syllable and mora boundaries, and melody detection are automatic and best-effort. Unusual names, rapid or overlapping vocals, noisy recordings, and mixed-language passages may need correction. YouTube can reject downloads; uploading an MP4 is the fallback.

## Development disclosure

Karapincho was created by Gonzalo Cibeira with substantial assistance from AI tools, including support with product design, implementation, testing, research, and documentation. Gonzalo directed the project and remains its maintainer.

## Validation

The release tree passes 142 Python tests and 12 responsive browser/accessibility/keyboard checks, plus Python lint, dependency, production-build, and release-integrity checks. Model-backed pipelines remain a manual release gate and must be run from the actual source archive before publishing this release.
