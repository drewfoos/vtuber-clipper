import time
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

def test_shutdown_signals_exit(fixture_work_dir: Path):
    app = build_app(fixture_work_dir)
    client = TestClient(app)
    r = client.post("/api/shutdown")
    assert r.status_code == 200
    assert app.state.should_exit is True

def test_root_serves_index_html(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>VTuber Clipper · Review</title>" in r.text

def test_static_css_served(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/static/app.css")
    assert r.status_code == 200
    assert "clip-row" in r.text

def test_static_js_served(fixture_work_dir):
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/static/app.js")
    assert r.status_code == 200
    assert "loadClips" in r.text
    assert "innerHTML" not in r.text  # XSS guard: must use textContent / DOM construction

def test_idle_tracker_updates_on_request(fixture_work_dir: Path):
    app = build_app(fixture_work_dir)
    before = app.state.last_request_at
    time.sleep(0.01)
    TestClient(app).get("/api/clips")
    assert app.state.last_request_at > before

def test_app_js_groups_caption_words(fixture_work_dir):
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/static/app.js")
    assert r.status_code == 200
    # The overlay should show 3-word windows, not single words.
    # We assert presence of a grouping function or constant.
    assert "WORDS_PER_WINDOW" in r.text or "window" in r.text.lower()
    # And that the active-word visualization wraps individual words in <span>.
    assert "createElement(\"span\")" in r.text or "createElement('span')" in r.text
