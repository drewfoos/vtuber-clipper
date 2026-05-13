"""Detect hype peaks in chat by binning msg/s, regex-weighting, and scipy peak finding."""
import re
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

from clipper.util.json_io import read_jsonl, write_json
from clipper.util.logging import get_logger

logger = get_logger(__name__)


def top_emotes_for_window(messages: list[dict], hype_regex: str, max_emotes: int = 5) -> list[str]:
    """Count tokens matching hype_regex (case-insensitive) across messages; return top N by frequency."""
    pattern = re.compile(hype_regex, re.IGNORECASE)
    counter: Counter = Counter()
    for m in messages:
        text = m.get("msg", "")
        for match in pattern.findall(text):
            counter[match.upper()] += 1
    return [emote for emote, _ in counter.most_common(max_emotes)]


def _hype_weight(msg: str, hype_pattern: re.Pattern) -> float:
    weight = 1.0
    if hype_pattern.search(msg):
        weight += 2.0
    stripped = msg.strip()
    if len(stripped) > 3 and stripped.isupper():
        weight += 3.0
    return weight


def detect_chat_peaks(
    chat_path: Path,
    duration: float,
    work_dir: Path,
    *,
    bucket_seconds: float = 2.0,
    min_prominence_multiplier: float = 2.0,
    min_gap_seconds: float = 30.0,
    hype_regex: str = r"\b(KEKW|LULW|POG|OMEGALUL|LMAO|LOL|W|WTF|HOLY|JESUS)\b",
) -> Path:
    """Detect hype peaks; write chat_peaks.json."""
    out = work_dir / "chat_peaks.json"
    if out.exists():
        logger.info(f"Skipping chat peak detection; {out} exists")
        return out
    messages = list(read_jsonl(chat_path))
    if not messages:
        write_json(out, [])
        return out

    n_buckets = max(1, int(duration / bucket_seconds) + 1)
    hype_pattern = re.compile(hype_regex, re.IGNORECASE)
    weighted = np.zeros(n_buckets, dtype=float)
    bucket_messages: list[list[dict]] = [[] for _ in range(n_buckets)]
    for m in messages:
        t = float(m.get("t", 0.0))
        idx = int(t / bucket_seconds)
        if 0 <= idx < n_buckets:
            weighted[idx] += _hype_weight(m.get("msg", ""), hype_pattern)
            bucket_messages[idx].append(m)

    # Baseline floor matters a LOT for sparse chats. With a 0.5 floor, a single
    # hype-weighted message (weight ~3) easily clears the prominence threshold,
    # which yields hundreds of false peaks on low-traffic streams. We floor at
    # the larger of (median, mean) so the baseline reflects actual chat volume
    # rather than collapsing to the floor when most buckets are zero.
    baseline = max(
        2.0,
        float(np.median(weighted)),
        float(np.mean(weighted)) * 2,
    )
    peaks_idx, props = find_peaks(
        weighted,
        prominence=baseline * min_prominence_multiplier,
        distance=max(1, int(min_gap_seconds / bucket_seconds)),
    )

    peaks_out: list[dict] = []
    for pi in peaks_idx:
        peak_center = pi * bucket_seconds
        # Walk backwards to find where signal rises above baseline
        lo = pi
        while lo > 0 and weighted[lo - 1] > baseline * 1.5:
            lo -= 1
        t_start = max(0.0, lo * bucket_seconds - bucket_seconds)
        # Walk forwards to find where signal drops back to baseline
        hi = pi
        while hi + 1 < n_buckets and weighted[hi + 1] > baseline * 1.5:
            hi += 1
        t_end = (hi + 1) * bucket_seconds

        window_msgs = [m for m in messages if t_start <= float(m.get("t", 0.0)) <= t_end]
        peaks_out.append({
            "t_start": float(t_start),
            "t_end": float(t_end),
            "msg_count": len(window_msgs),
            "hype_score": float(np.sum(weighted[max(0, pi - 7): min(n_buckets, pi + 8)])),
            "top_emotes": top_emotes_for_window(window_msgs, hype_regex),
        })

    peaks_out.sort(key=lambda p: p["hype_score"], reverse=True)
    write_json(out, peaks_out)
    logger.info(f"Wrote {len(peaks_out)} chat peaks to {out}")
    return out
