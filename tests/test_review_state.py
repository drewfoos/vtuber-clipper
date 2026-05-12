import json
from pathlib import Path

from fastapi.testclient import TestClient

from clipper.web import build_app

def test_put_updates_clip_in_memory(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    r = client.put("/api/clips/c001", json={"title": "NEW TITLE", "kept": False})
    assert r.status_code == 200
    assert r.json()["title"] == "NEW TITLE"
    assert r.json()["kept"] is False

def test_put_persists_to_review_state_json(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    client.put("/api/clips/c001", json={"title": "PERSISTED"})
    state = json.loads((fixture_work_dir / "review_state.json").read_text())
    assert state["clips"]["c001"]["title"] == "PERSISTED"

def test_state_loaded_on_startup(fixture_work_dir: Path):
    (fixture_work_dir / "review_state.json").write_text(json.dumps({
        "vod_id": "vod_test",
        "schema_version": "0.1.0",
        "last_modified": "2026-05-11T00:00:00Z",
        "clips": {"c001": {"title": "FROM DISK", "t_start": 5.0, "t_end": 15.0,
                           "kept": False, "caption_mode": "clean", "effects": {}}}
    }))
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/api/clips")
    c001 = next(c for c in r.json() if c["id"] == "c001")
    assert c001["title"] == "FROM DISK"
    assert c001["kept"] is False
    assert c001["caption_mode"] == "clean"

def test_put_rejects_invalid_trim(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    r = client.put("/api/clips/c001", json={"t_start": 14.0, "t_end": 15.0})  # 1s clip
    assert r.status_code == 400


def test_layout_field_defaults_to_auto(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/api/clips")
    assert r.json()[0]["layout"] == "auto"


def test_layout_field_can_be_overridden(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    r = client.put("/api/clips/c001", json={"layout": "stacked"})
    assert r.status_code == 200
    assert r.json()["layout"] == "stacked"
