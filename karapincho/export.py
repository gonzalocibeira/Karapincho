# SPDX-License-Identifier: GPL-3.0-or-later
"""Names shared by song archives and browser downloads."""

import re
import os
import tempfile
import zipfile


def download_name(folder):
    headers = {}
    for line in (folder / "song.txt").read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("#") and ":" in line:
            key, value = line[1:].split(":", 1)
            headers[key] = value.strip()

    def safe(value, fallback):
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", value)
        # Bound UTF-8 bytes as well as characters for filesystem compatibility.
        return value.encode("utf-8")[:100].decode("utf-8", errors="ignore").strip(" .") or fallback

    artist = safe(headers.get("ARTIST", ""), "Unknown Artist")
    title = safe(headers.get("TITLE", ""), "Unknown Song")
    return f"{artist} - {title}"


def update_archive_name(path, folder, name):
    """Refresh older cached exports when they are downloaded."""
    files = ("song.txt", "audio.mp3", "video.mp4", "cover.jpg")
    with zipfile.ZipFile(path) as archive:
        if set(archive.namelist()) == {f"{name}/{file}" for file in files}:
            return
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".zip.partial")
    try:
        with os.fdopen(descriptor, "wb") as target:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as archive:
                for file in files:
                    archive.write(folder / file, f"{name}/{file}")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
