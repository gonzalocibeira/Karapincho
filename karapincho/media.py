# SPDX-License-Identifier: GPL-3.0-or-later
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config


def youtube_url(value):
    try:
        url = urlparse(value.strip())
        if url.scheme != "https" or url.username or url.password or url.port not in (None, 443):
            raise ValueError
        query = parse_qs(url.query)
        if "list" in query:
            raise ValueError
        if url.hostname in ("youtu.be", "www.youtu.be"):
            video_id = url.path.strip("/")
        elif url.hostname in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
            if url.path == "/watch":
                video_id = query.get("v", [""])[0]
            elif url.path.startswith(("/shorts/", "/embed/")):
                video_id = url.path.split("/")[2]
            else:
                raise ValueError
        else:
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise ValueError
        return f"https://www.youtube.com/watch?v={video_id}"
    except ValueError:
        raise ValueError(
            "Enter a single public YouTube video URL (https). Playlists and live links are not supported."
        ) from None


def run(args):
    result = subprocess.run([str(x) for x in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-3000:] or "Media command failed")
    return result.stdout


def inspect_media(path):
    # PyAV ships with faster-whisper and avoids depending on a separately installed ffprobe.
    import av

    try:
        with av.open(str(path)) as container:
            if not container.streams.audio or not container.streams.video:
                raise ValueError("The video must contain both audio and video tracks.")
            duration = container.duration / av.time_base if container.duration else 0
            if not duration:
                duration = max(float(s.duration * s.time_base) for s in container.streams if s.duration)
            if not 0 < duration <= config.MAX_SECONDS:
                raise ValueError("Please use a single song shorter than 20 minutes.")
            return {"duration": duration, "tags": dict(container.metadata)}
    except av.error.FFmpegError as exc:
        raise ValueError(
            "This MP4 cannot be decoded. Please provide a playable video with an audio track."
        ) from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            "This MP4 cannot be decoded. Please provide a playable video with an audio track."
        ) from exc


def resolve_artist(info, tags=None):
    """Prefer explicit credits; use only recognizable title/channel conventions."""
    tags = {key.lower(): value for key, value in (tags or {}).items()}
    for value in (info.get("artist"), info.get("artists"), tags.get("artist"), tags.get("album_artist")):
        if isinstance(value, (list, tuple)):
            value = ", ".join(item.strip() for item in value if isinstance(item, str) and item.strip())
        if isinstance(value, str) and value.strip():
            return value.strip()

    # Japanese official videos commonly use "Song / Artist：MUSIC VIDEO".
    title = info.get("title") or tags.get("title") or ""
    match = re.search(
        r"\s[/／]\s*(?P<artist>[^/／:：]+?)\s*[:：]\s*(?:official\s+)?music\s+video\s*$",
        title,
        re.IGNORECASE,
    )
    if match:
        return match["artist"].strip()
    # A generic uploader may be a label or fan account, so do not use it as a credit.
    for key in ("channel", "uploader"):
        channel = info.get(key) or ""
        if channel.endswith(" - Topic") and channel[:-8].strip():
            return channel[:-8].strip()
    return "Unknown Artist"


def acquire(job, folder):
    if job["source_type"] == "file":
        source = folder / "input.mp4"
        if not source.exists():
            raise ValueError("The uploaded MP4 is missing.")
        info = inspect_media(source)
        tags = {key.lower(): value for key, value in info["tags"].items()}
        return {
            "input": str(source),
            "duration": info["duration"],
            "title": tags.get("title") or job["title"],
            "artist": resolve_artist({}, tags),
            "album": tags.get("album", ""),
        }

    import yt_dlp

    def reject(info, *, incomplete=False):
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            return "Live streams are not supported."
        if info.get("duration", 0) > config.MAX_SECONDS:
            return "Please use a single song shorter than 20 minutes."
        if info.get("availability") in ("private", "premium_only", "subscriber_only", "needs_auth"):
            return "This video requires an account. Please supply an MP4 instead."
        return None

    opts = {
        "outtmpl": str(folder / "source.%(ext)s"),
        "noplaylist": True,
        "format": "bv*[height<=1080]+ba/b[height<=1080]",
        "merge_output_format": "mp4",
        "ffmpeg_location": config.ffmpeg(),
        "max_filesize": config.MAX_BYTES,
        "match_filter": reject,
        "socket_timeout": 25,
        "retries": 2,
        "fragment_retries": 2,
        "quiet": True,
        "no_warnings": True,
        "js_runtimes": {"node": {}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as downloader:
            info = downloader.extract_info(youtube_url(job["source"]), download=True)
        candidates = [p for p in folder.glob("source.*") if p.suffix in (".mp4", ".mkv", ".webm", ".mov")]
        if not info or not candidates:
            raise ValueError("No downloadable video was returned.")
        source = max(candidates, key=lambda p: p.stat().st_size)
        if source.stat().st_size > config.MAX_BYTES:
            raise ValueError("The downloaded song exceeds the 2 GB limit.")
        metadata = inspect_media(source)
        return {
            "input": str(source),
            "duration": metadata["duration"],
            "title": info.get("track") or info.get("title") or job["title"],
            "artist": resolve_artist(info, metadata["tags"]),
            "album": info.get("album") or metadata["tags"].get("album", ""),
        }
    except Exception as exc:
        raise ValueError(
            f"YouTube download failed. Try dropping an MP4 instead. Details: {str(exc)[-500:]}"
        ) from exc


def prepare(metadata, folder):
    import soundfile as sf
    from . import acceleration

    ff = config.ffmpeg()
    source = Path(metadata["input"])
    base = [ff, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", source]
    # A single normalized, untrimmed timeline feeds both playback audio and video.
    run(
        [
            *base,
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            f"aresample=async=1:first_pts=0,apad=whole_dur={metadata['duration']}",
            "-t",
            str(metadata["duration"]),
            "-ar",
            "44100",
            "-ac",
            "2",
            folder / "original.wav",
        ]
    )
    run(
        [
            ff,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            folder / "original.wav",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "192k",
            folder / "audio.mp3",
        ]
    )
    video_options = (["-c:v", "h264_videotoolbox", "-allow_sw", "0", "-b:v", "12M"]
                     if acceleration.CURRENT.backend == "videotoolbox" else
                     ["-c:v", "libx264", "-preset", "fast", "-crf", "21"])
    run(
        [
            *base,
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            f"scale='min(1920,iw)':-2,setsar=1,tpad=stop_mode=clone:stop_duration={metadata['duration']}",
            "-t",
            str(metadata["duration"]),
            *video_options,
            "-pix_fmt",
            "yuv420p",
            "-fps_mode",
            "cfr",
            "-r",
            "30",
            "-movflags",
            "+faststart",
            folder / "video.mp4",
        ]
    )
    run(
        [
            ff,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            str(min(10, metadata["duration"] / 3)),
            "-i",
            folder / "video.mp4",
            "-frames:v",
            "1",
            "-vf",
            "scale=640:-2",
            "-update",
            "1",
            folder / "cover.jpg",
        ]
    )
    details = sf.info(folder / "original.wav")
    metadata["duration"] = details.duration
    return metadata


def write_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))
