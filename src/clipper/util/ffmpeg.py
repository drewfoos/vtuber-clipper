import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EncodeProfile:
    width: int
    height: int
    nvenc_preset: str    # "p5", "p7"
    cq: int              # 0-51 (23 ~ good, 28 ~ preview)
    audio_bitrate: str   # "96k", "128k"


PREVIEW = EncodeProfile(540, 960, "p7", 28, "96k")
FINAL = EncodeProfile(1080, 1920, "p5", 23, "128k")


def run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg with standard prefix. Raises CalledProcessError on non-zero exit."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *args]
    subprocess.run(cmd, check=True)


def encode_clip(
    src: Path,
    t_start: float,
    duration: float,
    out: Path,
    profile: EncodeProfile,
    subtitles_path: Path | None = None,
    extra_filters: list[str] | None = None,
) -> None:
    """Encode a clip with crop+scale to profile dimensions, optional burned subtitles + extra filters."""
    crop_scale = (
        f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=increase,"
        f"crop={profile.width}:{profile.height}"
    )
    filters = [crop_scale]
    if extra_filters:
        filters.extend(extra_filters)
    if subtitles_path is not None:
        escaped = str(subtitles_path).replace("\\", "/").replace(":", "\\:")
        filters.append(f"subtitles='{escaped}'")
    vf = ",".join(filters)
    run_ffmpeg([
        "-ss", str(t_start),
        "-i", str(src),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "h264_nvenc", "-preset", profile.nvenc_preset, "-cq:v", str(profile.cq),
        "-c:a", "aac", "-b:a", profile.audio_bitrate,
        "-movflags", "+faststart",
        str(out),
    ])
