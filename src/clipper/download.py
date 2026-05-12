"""Download a Twitch VOD via yt-dlp Python API; extract a low-bitrate audio track via ffmpeg."""
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from clipper.util.logging import get_logger

logger = get_logger(__name__)

_VOD_ID_RE = re.compile(r"^https?://(?:www\.)?twitch\.tv/videos/(\d+)")


@dataclass
class DownloadResult:
    video_path: Path
    audio_path: Path
    vod_id: str
    duration_seconds: float
    title: str
    streamer: str


def parse_vod_id(url: str) -> str:
    m = _VOD_ID_RE.match(url)
    if not m:
        raise ValueError(f"not a Twitch VOD URL: {url!r}")
    return m.group(1)


def download_vod(url: str, work_root: Path, quality: str = "1080p60") -> DownloadResult:
    """Download the VOD video file then extract a low-bitrate Opus audio track."""
    vod_id = parse_vod_id(url)
    work_dir = work_root / vod_id
    work_dir.mkdir(parents=True, exist_ok=True)
    video_path = work_dir / "video.mp4"
    audio_path = work_dir / "audio.opus"

    # Fetch metadata even when the video already exists, so we can return a complete result.
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    duration = float(info.get("duration", 0))
    title = info.get("title", "")
    streamer = info.get("uploader") or info.get("channel") or ""

    if not video_path.exists():
        logger.info(f"Downloading {url} at {quality} -> {video_path}")
        with yt_dlp.YoutubeDL({
            "format": quality,
            "outtmpl": str(video_path),
            "quiet": True,
            "no_warnings": True,
        }) as ydl:
            ydl.download([url])
    else:
        logger.info(f"Skipping download; {video_path} exists")

    if not audio_path.exists():
        logger.info(f"Extracting audio -> {audio_path}")
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(video_path),
            "-vn", "-c:a", "libopus", "-b:a", "32k",
            str(audio_path),
        ], check=True)
    else:
        logger.info(f"Skipping audio extract; {audio_path} exists")

    return DownloadResult(
        video_path=video_path,
        audio_path=audio_path,
        vod_id=vod_id,
        duration_seconds=duration,
        title=title,
        streamer=streamer,
    )
