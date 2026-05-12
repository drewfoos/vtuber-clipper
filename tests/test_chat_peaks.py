import json
import shutil
from pathlib import Path

from clipper.chat_peaks import detect_chat_peaks, top_emotes_for_window

FIXTURES = Path(__file__).parent / "fixtures"


def test_top_emotes_counts_hype_words():
    msgs = [
        {"t": 1.0, "msg": "KEKW KEKW"},
        {"t": 2.0, "msg": "kekw"},
        {"t": 3.0, "msg": "LULW"},
        {"t": 4.0, "msg": "neutral text"},
    ]
    top = top_emotes_for_window(
        msgs,
        hype_regex=r"\b(KEKW|LULW)\b",
        max_emotes=5,
    )
    assert top[0] == "KEKW"
    assert "LULW" in top


def test_detect_chat_peaks_finds_burst(tmp_path: Path):
    chat_path = tmp_path / "chat.jsonl"
    shutil.copy(FIXTURES / "chat_stream.sample.jsonl", chat_path)
    out = detect_chat_peaks(
        chat_path,
        duration=120.0,
        work_dir=tmp_path,
        bucket_seconds=2.0,
        min_prominence_multiplier=2.0,
        min_gap_seconds=30.0,
        hype_regex=r"\b(KEKW|LULW|POG|OMEGALUL|LMAO|LOL|W|WTF|HOLY|JESUS|NO WAY|LETS GO|LETSGO|GG)\b",
    )
    peaks = json.loads(out.read_text(encoding="utf-8"))
    assert len(peaks) >= 1
    burst = peaks[0]
    assert 55.0 <= burst["t_start"] <= 62.0
    assert burst["t_end"] >= 62.0
    assert burst["msg_count"] >= 10
    assert "KEKW" in burst["top_emotes"]


def test_detect_chat_peaks_skips_if_output_exists(tmp_path: Path):
    out = tmp_path / "chat_peaks.json"
    out.write_text("[]", encoding="utf-8")
    result = detect_chat_peaks(
        tmp_path / "nonexistent_chat.jsonl",
        duration=120.0,
        work_dir=tmp_path,
        bucket_seconds=2.0,
        min_prominence_multiplier=2.0,
        min_gap_seconds=30.0,
        hype_regex=r"\bKEKW\b",
    )
    assert result == out
