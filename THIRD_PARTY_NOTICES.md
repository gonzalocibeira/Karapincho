# Third-party notices

Karapincho is GPL-3.0-or-later software. It uses and downloads third-party software, model weights, and recordings which retain their own copyright and license terms. This file is a practical inventory, not a replacement for the license files shipped by those projects.

## Runtime software

- **PyKakasi** — GPL-3.0-or-later. Japanese Kana/Kanji-to-romaji conversion.
- **FFmpeg** — GPL-2.0-or-later in the build currently installed through `imageio-ffmpeg`; invoked as a separate executable for media processing. Run `ffmpeg -L` on the installed binary for its complete notice.
- **FastAPI, Uvicorn, React, Vite, Lucide, yt-dlp, WhisperX, Faster Whisper, Demucs, torchcrepe, PyTorch, MLX, Fugashi, UniDic Lite, Pyphen, NumPy, SciPy, SoundFile, PyAV, and their transitive dependencies** retain their upstream licenses. The exact tested package versions are recorded in `requirements-macos.lock`, `requirements-gpu.lock`, and `frontend/package-lock.json`.
- **Downloaded model weights** — the Faster Whisper and optional MLX Whisper snapshots are MIT; the Japanese and Spanish XLSR-53 alignment snapshots are Apache-2.0; the English wav2vec 2.0 alignment weight is MIT. The torchcrepe weight is bundled with its MIT-licensed package. Exact repositories, immutable Hugging Face revisions, package-pinned filenames, provenance, and the available torchcrepe checksum are in `karapincho/model_manifest.json`.

Karapincho deliberately uses the Apache-2.0 Spanish XLSR-53 model instead of Torchaudio's otherwise convenient VoxPopuli Spanish bundle, whose upstream model license is CC BY-NC 4.0. This keeps the default model path suitable for commercial as well as personal use. Model licenses are independent of Karapincho's GPL license.

**Demucs warning:** Demucs source code is MIT, but its maintainer has stated that the pretrained weights are not covered by MIT and are provided only for scientific purposes. Setup downloads the `htdemucs` weight from Meta's model host; Karapincho does not redistribute it. Treat that weight as research-only. Commercial users must replace it with weights carrying commercial-use permission before using the separation stage. See the [upstream licensing discussion](https://github.com/facebookresearch/demucs/issues/327).

The lock files are the authoritative dependency inventory for this release. Before changing a dependency, review its package and model licenses and update this notice.

## Bundled benchmark recordings

The benchmark MP4s under `karapincho/benchmark_assets/` are a collection alongside the software and are **not relicensed under the GNU GPL**.

- **La Cucaracha** — Elisa (vocals), Sean Buss (guitar), Kenmayer (mix), CC BY-SA 3.0.
- **Sakura Sakura** — Kanohara (performance programming), anonymous synthesized vocalist, CC BY-SA 3.0.
- **Auld Lang Syne** — Frank C. Stanley, public-domain recording as identified by Wikimedia Commons.

The two CC BY-SA recordings were transcoded to AAC and combined with a solid-color video. Those derivatives remain CC BY-SA 3.0. Full source links, modifications, and hashes are recorded in `karapincho/benchmark_assets/ATTRIBUTION.md`.

## Services and formats

Karapincho is not affiliated with or endorsed by YouTube, LRCLIB, UltraStar Deluxe, or UltraStar WorldParty. Users are responsible for ensuring they have the right to download and process media.
