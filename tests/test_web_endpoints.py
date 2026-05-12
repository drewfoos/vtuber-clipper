from pathlib import Path

from fastapi.testclient import TestClient

from clipper.web import build_app

def test_get_clips_returns_ranked_list(fixture_work_dir: Path):
    app = build_app(fixture_work_dir)
    client = TestClient(app)
    r = client.get("/api/clips")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    assert body[0]["id"] == "c001"
    assert body[0]["title"] == "HOLY NO WAY THAT JUST HAPPENED"
    assert body[0]["kept"] is True   # default-kept
    assert body[0]["caption_mode"] == "burned"
