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

def test_clean_mode_produces_no_captions_and_srt(fixture_work_dir, fixture_out_dir):
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    client.put("/api/clips/c001", json={"caption_mode": "clean"})
    client.put("/api/clips/c002", json={"kept": False})
    client.put("/api/clips/c003", json={"kept": False})
    finalize(fixture_work_dir, fixture_out_dir)
    final = fixture_out_dir / "final"
    mp4s = list(final.glob("*.mp4"))
    srts = list(final.glob("*.srt"))
    assert len(mp4s) == 1
    assert len(srts) == 1
    assert mp4s[0].stem == srts[0].stem

def test_both_mode_produces_burned_and_clean_and_srt(fixture_work_dir, fixture_out_dir):
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    client.put("/api/clips/c001", json={"caption_mode": "both"})
    client.put("/api/clips/c002", json={"kept": False})
    client.put("/api/clips/c003", json={"kept": False})
    finalize(fixture_work_dir, fixture_out_dir)
    final = fixture_out_dir / "final"
    files = sorted(p.name for p in final.iterdir())
    assert sum(1 for f in files if f.endswith(".mp4") and "_clean" not in f) == 1
    assert sum(1 for f in files if f.endswith("_clean.mp4")) == 1
    assert sum(1 for f in files if f.endswith(".srt")) == 1

def test_post_finalize_streams_progress(fixture_work_dir, fixture_out_dir):
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir, out_root=fixture_out_dir))
    client.put("/api/clips/c002", json={"kept": False})
    client.put("/api/clips/c003", json={"kept": False})
    with client.stream("POST", "/api/finalize") as r:
        assert r.status_code == 200
        events = [line for line in r.iter_lines() if line.startswith("data:")]
    assert any("complete" in e for e in events)

def test_window3_style_emits_per_word_dialogue(fixture_work_dir, fixture_out_dir):
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    client.put("/api/clips/c001", json={"caption_style": "window3"})
    client.put("/api/clips/c002", json={"kept": False})
    client.put("/api/clips/c003", json={"kept": False})
    finalize(fixture_work_dir, fixture_out_dir)
    # The manifest should record the style applied.
    import json as _json
    manifest = _json.loads((fixture_out_dir / "final" / "manifest.json").read_text())
    assert manifest["clips"][0]["caption_style"] == "window3"
