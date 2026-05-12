from pathlib import Path

from clipper.util.peaks import load_audio_peaks, load_chat_peaks, peaks_in_window


def test_load_audio_peaks_returns_list(fixture_work_dir: Path):
    peaks = load_audio_peaks(fixture_work_dir)
    assert len(peaks) >= 1
    assert "t_start" in peaks[0]
    assert "intensity" in peaks[0]


def test_load_audio_peaks_missing_returns_empty(tmp_path: Path):
    assert load_audio_peaks(tmp_path) == []


def test_load_chat_peaks_returns_list(fixture_work_dir: Path):
    peaks = load_chat_peaks(fixture_work_dir)
    assert len(peaks) >= 1
    assert "top_emotes" in peaks[0]


def test_load_chat_peaks_missing_returns_empty(tmp_path: Path):
    assert load_chat_peaks(tmp_path) == []


def test_peaks_in_window_filters_by_overlap():
    peaks = [
        {"t_start": 0.0, "t_end": 1.0},
        {"t_start": 5.0, "t_end": 6.0},
        {"t_start": 9.5, "t_end": 10.5},
        {"t_start": 20.0, "t_end": 21.0},
    ]
    # Window [5, 10) should include peaks that overlap, excluding pure-edge cases.
    inside = peaks_in_window(peaks, 5.0, 10.0)
    assert len(inside) == 2
    assert inside[0]["t_start"] == 5.0
    assert inside[1]["t_start"] == 9.5
