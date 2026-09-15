# SPDX-License-Identifier: GPL-3.0-or-later
import zipfile

import av
import numpy as np
import pytest
import soundfile as sf

from karapincho import config
from karapincho.chart import render_chart
from karapincho.media import acquire, inspect_media, prepare, resolve_artist, run
from karapincho.stage import package


@pytest.mark.parametrize(
    "info,tags,expected",
    [
        ({"title": "【第75回NHK紅白歌合戦 歌唱曲】踊り子 / Vaundy：MUSIC VIDEO"}, {}, "Vaundy"),
        ({"artist": " Credited Artist ", "title": "Song / Other: MUSIC VIDEO"}, {}, "Credited Artist"),
        ({"artists": ["One", "Two"]}, {}, "One, Two"),
        ({}, {"ARTIST": "File Artist"}, "File Artist"),
        ({}, {"album_artist": "Album Artist"}, "Album Artist"),
        ({"channel": "Vaundy - Topic"}, {}, "Vaundy"),
        ({"uploader": "Record Label", "title": "Song / Live"}, {}, "Unknown Artist"),
        ({"artist": " ", "artists": [], "channel": "Fan uploads"}, {}, "Unknown Artist"),
    ],
)
def test_resolve_artist(info, tags, expected):
    assert resolve_artist(info, tags) == expected


def test_youtube_artist_fallback_reaches_chart(tmp_path, monkeypatch):
    import yt_dlp

    (tmp_path / "source.mp4").write_bytes(b"stub")
    monkeypatch.setattr(
        yt_dlp.YoutubeDL, "extract_info",
        lambda *args, **kwargs: {"title": "踊り子 / Vaundy：MUSIC VIDEO"},
    )
    monkeypatch.setattr("karapincho.media.inspect_media", lambda path: {"duration": 3, "tags": {}})
    metadata = acquire({"source_type": "youtube", "source": "https://youtu.be/7HgJIAUtICU",
                        "title": "YouTube song"}, tmp_path)
    chart = render_chart(
        [{"start": 1, "end": 2, "type": ":", "pitch": 9, "text": "la ", "phrase": 1}], metadata,
    )
    assert "#ARTIST:Vaundy\n" in chart


def synthetic_video(folder):
    rate = 44100
    sample = np.zeros(rate * 3, dtype=np.float32)
    sample[rate : rate * 2] = 0.1 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)
    sf.write(folder / "test.wav", sample, rate)
    source = folder / "input.mp4"
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
            "color=c=green:s=160x120:r=30:d=3",
            "-i",
            folder / "test.wav",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            source,
        ]
    )
    return source


def test_real_media_encode_sync_and_package(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    config.initialize()
    folder = tmp_path / "jobs" / ("a" * 32)
    folder.mkdir()
    source = synthetic_video(folder)
    metadata = {"input": str(source), "title": "Test", "artist": "Test", **inspect_media(source)}
    result = prepare(metadata, folder)
    audio, rate = sf.read(folder / "original.wav")
    energy = np.abs(audio).mean(axis=1)
    first_signal = np.flatnonzero(energy > 0.04)[0] / rate
    assert abs(first_signal - 1) < 0.05  # Introduction was preserved.
    with av.open(str(folder / "video.mp4")) as video:
        assert abs(video.duration / av.time_base - result["duration"]) < 0.1
    (folder / "song.txt").write_text(
        render_chart([{"start": 1, "end": 2, "type": ":", "pitch": 9, "text": "la ", "phrase": 1}], result)
    )
    package(folder)
    with zipfile.ZipFile(folder / "song.zip") as archive:
        assert {n.split("/")[0] for n in archive.namelist()} == {"Test - Test"}
        assert sorted(n.split("/")[-1] for n in archive.namelist()) == [
            "audio.mp3",
            "cover.jpg",
            "song.txt",
            "video.mp4",
        ]
        assert archive.testzip() is None


def test_corrupt_media(tmp_path):
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"not a video")
    with pytest.raises(ValueError, match="cannot be decoded"):
        inspect_media(source)


def test_audio_offset_and_longer_video_keep_common_timeline(tmp_path):
    source = tmp_path / "offset.mp4"
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
            "color=c=green:s=160x120:r=30:d=4",
            "-itsoffset",
            "0.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            source,
        ]
    )
    metadata = {"input": str(source), "title": "Offset", "artist": "Test", **inspect_media(source)}
    prepare(metadata, tmp_path)
    audio, rate = sf.read(tmp_path / "original.wav")
    first_signal = np.flatnonzero(np.abs(audio).mean(axis=1) > 0.04)[0] / rate
    assert 0.45 < first_signal < 0.55
    assert abs(len(audio) / rate - 4) < 0.05
    with av.open(str(tmp_path / "video.mp4")) as video:
        assert abs(video.duration / av.time_base - len(audio) / rate) < 0.05


@pytest.mark.parametrize("failure", ["validation", "archive", "replacement"])
def test_rebuild_package_preserves_previous_on_failure(tmp_path, monkeypatch, failure):
    from pathlib import Path
    monkeypatch.setattr(config, "DATA", tmp_path)
    config.initialize()
    folder = tmp_path / "jobs" / ("b" * 32)
    folder.mkdir()
    metadata = {"title": "Test", "artist": "Test", "duration": 3}
    for name in ("audio.mp3", "video.mp4", "cover.jpg"):
        (folder / name).write_bytes(b"media")
    original = render_chart([{"start": 1, "end": 2, "type": ":", "pitch": 9, "text": "old ", "phrase": 1}], metadata)
    (folder / "song.txt").write_text(original)
    package(folder)
    previous_zip = (folder / "song.zip").read_bytes()
    destination = config.DATA / "library" / folder.name
    (folder / "song.txt").write_text(original.replace("old", "new"))
    if failure == "validation":
        (folder / "song.txt").write_text("invalid chart")
    elif failure == "archive":
        def fail(*args, **kwargs):
            raise OSError("archive failed")
        monkeypatch.setattr(zipfile.ZipFile, "write", fail)
    else:
        replace = Path.replace
        def fail(self, target):
            if self.name == "song.zip.partial":
                raise OSError("replacement failed")
            return replace(self, target)
        monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises((ValueError, OSError)):
        package(folder)
    assert (destination / "song.txt").read_text() == original
    assert (folder / "song.zip").read_bytes() == previous_zip
