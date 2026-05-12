from pathlib import Path

from clipper.util.json_io import read_json


def load_audio_peaks(work_dir: Path) -> list[dict]:
    """Load audio_peaks.json; return [] if the file is missing."""
    p = work_dir / "audio_peaks.json"
    return read_json(p) if p.exists() else []


def load_chat_peaks(work_dir: Path) -> list[dict]:
    """Load chat_peaks.json; return [] if the file is missing."""
    p = work_dir / "chat_peaks.json"
    return read_json(p) if p.exists() else []


def peaks_in_window(peaks: list[dict], t_start: float, t_end: float) -> list[dict]:
    """Return peaks whose [t_start, t_end] overlaps the given window.

    Inclusive-start, exclusive-end on the window. A peak overlaps if its
    t_start < window_end AND its t_end > window_start.
    """
    return [p for p in peaks if p["t_start"] < t_end and p["t_end"] > t_start]
