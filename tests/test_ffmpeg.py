import subprocess
from pathlib import Path

import pytest

from clipper.util.ffmpeg import FINAL, PREVIEW, encode_clip, run_ffmpeg


def test_profiles_have_expected_dimensions():
    assert (PREVIEW.width, PREVIEW.height) == (540, 960)
    assert (FINAL.width, FINAL.height) == (1080, 1920)
    assert PREVIEW.nvenc_preset == "p7"
    assert FINAL.nvenc_preset == "p5"


def test_run_ffmpeg_raises_on_bad_args():
    with pytest.raises(subprocess.CalledProcessError):
        run_ffmpeg(["-this-is-not-a-real-flag"])


def test_encode_clip_produces_file_at_profile_size(tmp_path: Path):
    src = tmp_path / "src.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(src),
    ], check=True)

    out = tmp_path / "out.mp4"
    encode_clip(src, t_start=0.0, duration=2.0, out=out, profile=PREVIEW)
    assert out.exists()
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )
    w, h = res.stdout.strip().split(",")
    assert (int(w), int(h)) == (540, 960)
