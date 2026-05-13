"""Detect hype peaks in chat by binning msg/s, regex-weighting, and scipy peak finding.

Uses an adaptive rolling-baseline approach so the same algorithm works across the
streamer-size spectrum — from coffeejg (~0.07 msg/s) to Ironmouse (~100 msg/s).
Peaks are detected as surges above the LOCAL recent baseline rather than against
a single global threshold.
"""
import re
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

from clipper.util.json_io import read_jsonl, write_json
from clipper.util.logging import get_logger

logger = get_logger(__name__)


def top_emotes_for_window(messages: list[dict], hype_regex: str, max_emotes: int = 5) -> list[str]:
    """Count tokens matching hype_regex (case-insensitive); return top N by frequency."""
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


def _rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
    """Centered moving average. Edges use shorter windows (mode='same' with convolve)."""
    if window <= 1 or len(arr) <= 1:
        return arr.copy()
    # Pad with edge values so the boundary baseline reflects local activity, not
    # zero-padded artificial dead air.
    half = window // 2
    padded = np.pad(arr, half, mode="edge")
    kernel = np.ones(window) / window
    return np.convolve(padded, kernel, mode="valid")[: len(arr)]


def detect_chat_peaks(
    chat_path: Path,
    duration: float,
    work_dir: Path,
    *,
    bucket_seconds: float = 2.0,
    rolling_baseline_seconds: float = 300.0,
    surge_multiplier: float = 3.0,
    absolute_floor: float = 3.0,
    min_gap_seconds: float = 60.0,
    target_count: int = 40,
    hype_regex: str = r"\b(KEKW|LULW|POG|OMEGALUL|LMAO|LOL|W|WTF|HOLY|JESUS)\b",
) -> Path:
    """Detect hype peaks; write chat_peaks.json.

    Algorithm:
    1. Bin messages into `bucket_seconds` buckets, weight by hype regex + ALL CAPS.
    2. Compute a centered rolling mean over `rolling_baseline_seconds` as the
       per-bucket "what's normal lately" baseline.
    3. A peak must clear BOTH: `rolling_baseline * surge_multiplier` (relative
       surge over local recent activity) AND `absolute_floor` (don't fire on
       dead-air micro-bumps when the baseline is near zero).
    4. After scipy.find_peaks, cap to `target_count` by keeping the biggest
       surges (peak_height - local_baseline). Bounded candidate volume keeps
       the LLM ranker fast regardless of streamer size.

    Defaults are tuned for the streamer-size spectrum:
    - On low-traffic streams: rolling baseline near zero, absolute_floor catches
      genuine bursts while ignoring single hype-tagged messages.
    - On high-traffic streams: rolling baseline is high, only true surges
      (3x recent activity) qualify, target_count cap prevents flooding.
    """
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
    for m in messages:
        t = float(m.get("t", 0.0))
        idx = int(t / bucket_seconds)
        if 0 <= idx < n_buckets:
            weighted[idx] += _hype_weight(m.get("msg", ""), hype_pattern)

    # Adaptive rolling baseline — "what's normal in the last 5 minutes here".
    rolling_window = max(1, int(rolling_baseline_seconds / bucket_seconds))
    rolling_baseline = _rolling_mean(weighted, rolling_window)

    # Threshold per bucket: surge over local baseline OR absolute floor, whichever's higher.
    threshold = np.maximum(absolute_floor, rolling_baseline * surge_multiplier)

    peaks_idx, _ = find_peaks(
        weighted,
        height=threshold,
        distance=max(1, int(min_gap_seconds / bucket_seconds)),
    )

    # Cap by surge intensity — keep the biggest spikes above local baseline.
    if len(peaks_idx) > target_count:
        surges = weighted[peaks_idx] - rolling_baseline[peaks_idx]
        keep = np.argsort(surges)[-target_count:]
        peaks_idx = np.sort(peaks_idx[keep])

    peaks_out: list[dict] = []
    for pi in peaks_idx:
        # Walk backwards: extend t_start while signal is still elevated above local baseline.
        lo = int(pi)
        while lo > 0 and weighted[lo - 1] > rolling_baseline[lo - 1] * 1.5:
            lo -= 1
        t_start = max(0.0, lo * bucket_seconds - bucket_seconds)
        # Walk forward: extend t_end while signal is still elevated.
        hi = int(pi)
        while hi + 1 < n_buckets and weighted[hi + 1] > rolling_baseline[hi + 1] * 1.5:
            hi += 1
        t_end = (hi + 1) * bucket_seconds

        window_msgs = [m for m in messages if t_start <= float(m.get("t", 0.0)) <= t_end]
        peaks_out.append({
            "t_start": float(t_start),
            "t_end": float(t_end),
            "msg_count": len(window_msgs),
            "hype_score": float(np.sum(weighted[max(0, int(pi) - 7): min(n_buckets, int(pi) + 8)])),
            "top_emotes": top_emotes_for_window(window_msgs, hype_regex),
        })

    peaks_out.sort(key=lambda p: p["hype_score"], reverse=True)
    write_json(out, peaks_out)
    logger.info(
        f"Wrote {len(peaks_out)} chat peaks to {out} "
        f"(rolling baseline mean: {float(np.mean(rolling_baseline)):.1f})"
    )
    return out
