from pathlib import Path

from clipper.util.json_io import read_json


def load_transcript(work_dir: Path) -> dict:
    return read_json(work_dir / "transcript.json")


def words_in_window(transcript: dict, t_start: float, t_end: float) -> list[dict]:
    out = []
    for seg in transcript["segments"]:
        for w in seg.get("words", []):
            if t_start <= w["start"] < t_end:
                out.append(w)
    return out
