# SPDX-License-Identifier: GPL-3.0-or-later
"""Download openly licensed singing samples and wrap them in MP4 for acceptance tests.

These are test fixtures, never inputs to the transcription or alignment algorithms.
See tests/fixtures/SOURCES.md for attribution and scope.
"""

import hashlib
import urllib.request

from karapincho import config
from karapincho.media import run

SOURCES = {
    "es": ("La_Cucaracha.ogg", "La Cucaracha", "Elisa; Sean Buss; Kenmayer"),
    "ja": ("Sakura_Sakura.song.ogg", "Sakura Sakura", "Kanohara; anonymous synthesized vocalist"),
    "en": ("Auld_Lang_Syne.ogg", "Auld Lang Syne", "Frank C. Stanley"),
}


def main():
    folder = config.ROOT / ".cache" / "fixtures"
    folder.mkdir(parents=True, exist_ok=True)
    for language, (filename, title, artist) in SOURCES.items():
        source = folder / f"{language}.ogg"
        if not source.exists():
            digest = hashlib.md5(filename.encode()).hexdigest()
            url = f"https://upload.wikimedia.org/wikipedia/commons/{digest[0]}/{digest[:2]}/{filename}"
            request = urllib.request.Request(
                url, headers={"User-Agent": "Karapincho/0.1 local compatibility testing"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                source.write_bytes(response.read())
        output = folder / f"{language}.mp4"
        if not output.exists():
            run(
                [
                    config.ffmpeg(),
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=0x35412e:s=640x360:r=30",
                    "-i",
                    source,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                    "-metadata",
                    f"title={title}",
                    "-metadata",
                    f"artist={artist}",
                    output,
                ]
            )
        print(output, flush=True)


if __name__ == "__main__":
    main()
