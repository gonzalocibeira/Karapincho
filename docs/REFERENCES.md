# References and acknowledgements

## Karaoke format and players

- [UltraStar classic file-format specification](https://github.com/UltraStar-Deluxe/format/blob/main/The%20UltraStar%20File%20Format%20%28Unversioned%29.md)
- [UltraStar España creation guide](https://ultrastar-es.org/es/ayuda/12)
- [UltraStar Deluxe](https://github.com/UltraStar-Deluxe/USDX)
- [UltraStar WorldParty](https://github.com/ultrastares/ultrastar-worldparty)

## Processing stack

- [LRCLIB](https://lrclib.net/) — synchronized lyric lookup
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — public video acquisition
- [FFmpeg](https://ffmpeg.org/) — media decoding and encoding
- [Whisper](https://github.com/openai/whisper), [Faster Whisper](https://github.com/SYSTRAN/faster-whisper), and [WhisperX](https://github.com/m-bain/whisperX) — transcription and alignment
- [Spanish XLSR-53 alignment model](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-spanish) and [Japanese XLSR-53 alignment model](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-japanese) — permissively licensed language-specific alignment weights
- [Demucs](https://github.com/facebookresearch/demucs) — analysis-only vocal separation
- [torchcrepe](https://github.com/maxrmorrison/torchcrepe) — pitch tracking
- [PyKakasi](https://github.com/miurahr/pykakasi), [Fugashi](https://github.com/polm/fugashi), and [UniDic](https://clrd.ninjal.ac.jp/unidic/) — Japanese reading and romanization
- [MLX](https://github.com/ml-explore/mlx) — optional Apple Silicon inference

Model revisions and licenses are recorded in [`karapincho/model_manifest.json`](../karapincho/model_manifest.json). Recording credits are recorded in [`karapincho/benchmark_assets/ATTRIBUTION.md`](../karapincho/benchmark_assets/ATTRIBUTION.md).
