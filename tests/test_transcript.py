from pathlib import Path

from clipper.util.transcript import load_transcript, words_in_window


def test_load_transcript_returns_dict(fixture_work_dir: Path):
    t = load_transcript(fixture_work_dir)
    assert "segments" in t


def test_words_in_window_filters_by_time(fixture_work_dir: Path):
    t = load_transcript(fixture_work_dir)
    # c001 is [5.0, 15.0] in the fixture
    words = words_in_window(t, 5.0, 15.0)
    assert words[0]["word"] == "holy"
    for w in words:
        assert 5.0 <= w["start"] < 15.0


def test_words_in_window_excludes_boundary_end():
    t = {"segments": [{"words": [
        {"start": 0.0, "end": 0.5, "word": "a"},
        {"start": 1.0, "end": 1.5, "word": "b"},
        {"start": 2.0, "end": 2.5, "word": "c"},
    ]}]}
    assert [w["word"] for w in words_in_window(t, 0.5, 2.0)] == ["b"]
