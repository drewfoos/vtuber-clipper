import json
import subprocess
from pathlib import Path

from clipper.finalize import finalize
from clipper.preview_export import preview_export
from clipper.web import build_app
from fastapi.testclient import TestClient

def _mark_only_c001_kept(work: Path) -> None:
    client = TestClient(build_app(work))
    client.put("/api/clips/c002", json={"kept": False})
    client.put("/api/clips/c003", json={"kept": False})

def test_only_kept_clips_are_encoded(fixture_work_dir: Path, fixture_out_dir: Path):
    preview_export(fixture_work_dir)
    _mark_only_c001_kept(fixture_work_dir)
    finalize(fixture_work_dir, fixture_out_dir)
    final = fixture_out_dir / "final"
    files = sorted(p.name for p in final.glob("*.mp4"))
    assert len(files) == 1
    assert files[0].startswith("01_")

def test_final_is_1080x1920(fixture_work_dir: Path, fixture_out_dir: Path):
    preview_export(fixture_work_dir)
    _mark_only_c001_kept(fixture_work_dir)
    finalize(fixture_work_dir, fixture_out_dir)
    mp4 = next((fixture_out_dir / "final").glob("*.mp4"))
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(mp4)],
        capture_output=True, text=True, check=True,
    )
    w, h = res.stdout.strip().split(",")
    assert int(w) == 1080 and int(h) == 1920

def test_manifest_written(fixture_work_dir: Path, fixture_out_dir: Path):
    preview_export(fixture_work_dir)
    _mark_only_c001_kept(fixture_work_dir)
    finalize(fixture_work_dir, fixture_out_dir)
    manifest = json.loads((fixture_out_dir / "final" / "manifest.json").read_text())
    assert len(manifest["clips"]) == 1
    assert manifest["clips"][0]["title"] == "HOLY NO WAY THAT JUST HAPPENED"
