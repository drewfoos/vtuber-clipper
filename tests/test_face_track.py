from pathlib import Path

import pytest

from clipper.face_track import (
    _smooth_x,
    _summarize_track,
    track_face,
)


def test_smooth_x_3second_moving_average():
    xs = [0.5, 0.55, 0.6, 0.5, 0.45, 0.5]
    smoothed = _smooth_x(xs, fps=2, window_seconds=3.0)
    assert len(smoothed) == len(xs)
    assert all(0.4 <= s <= 0.65 for s in smoothed)


def test_summarize_track_reports_bbox_and_hit_rate():
    track = [
        {"t": 0.0, "x": 0.8, "y": 0.85, "bbox_w": 0.12, "bbox_h": 0.22},
        {"t": 0.5, "x": 0.8, "y": 0.85, "bbox_w": 0.12, "bbox_h": 0.22},
        {"t": 1.0, "x": None, "y": None, "bbox_w": None, "bbox_h": None},
        {"t": 1.5, "x": 0.81, "y": 0.85, "bbox_w": 0.12, "bbox_h": 0.22},
    ]
    summary = _summarize_track(track)
    assert 0.7 <= summary["avg_x"] <= 0.9
    assert 0.7 <= summary["avg_y"] <= 0.9
    assert summary["hit_rate"] == 0.75
    assert summary["avg_bbox_w"] > 0


def test_summarize_track_handles_all_misses():
    track = [{"t": t * 0.5, "x": None, "y": None, "bbox_w": None, "bbox_h": None}
             for t in range(4)]
    summary = _summarize_track(track)
    assert summary["hit_rate"] == 0.0
    assert summary["avg_x"] is None


@pytest.mark.slow
def test_track_face_writes_per_clip_json(fixture_work_dir: Path):
    out = track_face(fixture_work_dir / "video.mp4", fixture_work_dir,
                     ranked_path=fixture_work_dir / "ranked.json",
                     fps=2, min_confidence=0.3)
    assert out.exists()
    import json
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "c001" in data
    assert "track" in data["c001"]
    assert "summary" in data["c001"]
    # Fixture is testsrc (no real face); MediaPipe should miss everything.
    assert data["c001"]["summary"]["hit_rate"] == 0.0


def test_track_face_skips_if_output_exists(tmp_path: Path):
    out = tmp_path / "face_track.json"
    out.write_text("{}", encoding="utf-8")
    result = track_face(tmp_path / "nope.mp4", tmp_path,
                        ranked_path=tmp_path / "nope.json")
    assert result == out
