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

def test_get_transcript_returns_words_in_clip_window(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/api/clips/c001/transcript")
    assert r.status_code == 200
    words = r.json()
    # c001 is [5.0, 15.0]; first word "holy" starts at 5.0
    assert words[0]["word"] == "holy"
    # All words should fall within [5.0, 15.0]
    for w in words:
        assert 5.0 <= w["start"] < 15.0
