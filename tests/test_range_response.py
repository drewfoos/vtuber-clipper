from pathlib import Path

from fastapi.testclient import TestClient

from clipper.preview_export import preview_export
from clipper.web import build_app

def test_full_file_returns_200(fixture_work_dir: Path):
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/api/clips/c001/preview.mp4")
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"

def test_range_returns_206_and_partial(fixture_work_dir: Path):
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/api/clips/c001/preview.mp4", headers={"Range": "bytes=0-1023"})
    assert r.status_code == 206
    assert len(r.content) == 1024
    assert r.headers["content-range"].startswith("bytes 0-1023/")

def test_missing_preview_returns_404(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/api/clips/c001/preview.mp4")
    assert r.status_code == 404
