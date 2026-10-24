# SPDX-License-Identifier: GPL-3.0-or-later
from types import SimpleNamespace

import pytest

from karapincho import config
from karapincho.media import inspect_media


@pytest.fixture(autouse=True)
def clear_ffmpeg_cache():
    config.ffmpeg.cache_clear()
    yield
    config.ffmpeg.cache_clear()


def test_missing_ffmpeg_does_not_fall_back_to_bundled_binary(monkeypatch):
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="brew install ffmpeg"):
        config.ffmpeg()


@pytest.mark.parametrize("version", ["7.1", "8.1.2", "9.0.1", "N-123456-custom"])
def test_outdated_or_unidentified_ffmpeg_is_rejected(monkeypatch, version):
    monkeypatch.setattr(config.shutil, "which", lambda name: "/test/ffmpeg")
    monkeypatch.setattr(config.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        stdout=f"ffmpeg version {version} Copyright"))
    with pytest.raises(RuntimeError, match="brew upgrade ffmpeg"):
        config.ffmpeg()


def test_current_ffmpeg_is_accepted(monkeypatch):
    monkeypatch.setattr(config.shutil, "which", lambda name: "/test/ffmpeg")
    monkeypatch.setattr(config.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        stdout="ffmpeg version 9.0.2 Copyright"))
    assert config.ffmpeg() == "/test/ffmpeg"


def test_playlist_disguised_as_mp4_is_rejected(tmp_path):
    source = tmp_path / "playlist.mp4"
    source.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nhttp://127.0.0.1/private.ts\n")
    with pytest.raises(ValueError, match="cannot be decoded"):
        inspect_media(source)
