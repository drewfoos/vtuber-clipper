import json
from pathlib import Path

from clipper.preview_export import preview_export

def test_emits_one_mp4_per_ranked_clip(fixture_work_dir: Path):
    out = preview_export(fixture_work_dir)
    assert out.exists()
    previews = fixture_work_dir / "previews"
    assert (previews / "c001.mp4").exists()
    assert (previews / "c002.mp4").exists()
    assert (previews / "c003.mp4").exists()

def test_preview_is_540x960(fixture_work_dir: Path):
    import subprocess
    preview_export(fixture_work_dir)
    p = fixture_work_dir / "previews" / "c001.mp4"
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, check=True,
    )
    w, h = res.stdout.strip().split(",")
    assert int(w) == 540 and int(h) == 960

def test_idempotent_skip(fixture_work_dir: Path):
    preview_export(fixture_work_dir)
    p = fixture_work_dir / "previews" / "c001.mp4"
    mtime = p.stat().st_mtime
    preview_export(fixture_work_dir)
    assert p.stat().st_mtime == mtime  # unchanged
