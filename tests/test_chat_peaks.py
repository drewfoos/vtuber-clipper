import json
import shutil
from pathlib import Path

from clipper.chat_peaks import detect_chat_peaks, top_emotes_for_window

FIXTURES = Path(__file__).parent / "fixtures"

HYPE_REGEX = (
    r"\b(KEKW|LULW|POG|OMEGALUL|LMAO|LOL|W|WTF|HOLY|JESUS|"
    r"NO WAY|LETS GO|LETSGO|GG)\b"
)


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
        rolling_baseline_seconds=60.0,
        surge_multiplier=3.0,
        absolute_floor=3.0,
        min_gap_seconds=30.0,
        target_count=10,
        hype_regex=HYPE_REGEX,
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
        hype_regex=r"\bKEKW\b",
    )
    assert result == out


def test_adaptive_baseline_handles_sparse_chat(tmp_path: Path):
    """Sparse low-traffic chat: rolling baseline near zero, only real bursts qualify.

    Simulates a coffeejg-style stream: a few isolated messages, one real burst.
    Without adaptive baseline, the old algorithm flagged every modest message
    as a peak. The new algorithm should produce 1 peak (the burst).
    """
    msgs = []
    # Sparse background chatter: 1 message every 30 seconds for 30 minutes.
    for i in range(60):
        msgs.append({"t": float(i * 30), "user": f"u{i}", "msg": "ok"})
    # One real KEKW burst around t=900.
    for i in range(8):
        msgs.append({"t": 900.0 + i * 0.3, "user": f"hype{i}", "msg": "KEKW KEKW KEKW"})

    chat_path = tmp_path / "chat.jsonl"
    with chat_path.open("w", encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps(m) + "\n")

    out = detect_chat_peaks(
        chat_path,
        duration=1800.0,
        work_dir=tmp_path,
        hype_regex=HYPE_REGEX,
    )
    peaks = json.loads(out.read_text(encoding="utf-8"))
    # Only the burst should be picked up; not the sparse background.
    assert 1 <= len(peaks) <= 3
    assert any(880.0 <= p["t_start"] <= 920.0 for p in peaks)


def test_adaptive_baseline_handles_dense_chat(tmp_path: Path):
    """Dense high-traffic chat: rolling baseline is high, only surges qualify.

    Simulates an Ironmouse-style stream: 50 msg/s baseline with one true spike.
    The old fixed-multiplier algorithm would flag dozens of small fluctuations;
    the new adaptive one should focus on the real surge.
    """
    import random
    rng = random.Random(42)
    msgs = []
    # 50 msg/s steady chatter for 10 minutes.
    for sec in range(600):
        for _ in range(rng.randint(45, 55)):
            msgs.append({"t": float(sec) + rng.random(), "user": "u", "msg": "lol"})
    # A 4x burst around t=300.
    for i in range(800):
        msgs.append({"t": 298.0 + i * 0.005, "user": "hype", "msg": "KEKW HOLY"})

    chat_path = tmp_path / "chat.jsonl"
    with chat_path.open("w", encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps(m) + "\n")

    out = detect_chat_peaks(
        chat_path,
        duration=600.0,
        work_dir=tmp_path,
        target_count=20,
        hype_regex=HYPE_REGEX,
    )
    peaks = json.loads(out.read_text(encoding="utf-8"))
    # Adaptive baseline focuses on real surges, not noise.
    assert len(peaks) <= 20
    # The big burst at t=298 should be the top-scored peak.
    top = peaks[0]
    assert 290.0 <= top["t_start"] <= 320.0


def test_target_count_caps_peak_volume(tmp_path: Path):
    """target_count must cap the output even when many buckets qualify."""
    msgs = []
    # Many small "bursts" of 4 KEKWs each, every 70 seconds, for 1 hour.
    # All qualify above absolute_floor; we should still get <=target_count.
    for burst_num in range(50):
        t = burst_num * 70.0
        for j in range(4):
            msgs.append({"t": t + j * 0.5, "user": f"u{j}", "msg": "KEKW"})

    chat_path = tmp_path / "chat.jsonl"
    with chat_path.open("w", encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps(m) + "\n")

    out = detect_chat_peaks(
        chat_path,
        duration=3600.0,
        work_dir=tmp_path,
        target_count=10,
        hype_regex=HYPE_REGEX,
    )
    peaks = json.loads(out.read_text(encoding="utf-8"))
    assert len(peaks) <= 10
