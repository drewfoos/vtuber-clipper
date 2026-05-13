"""Detect audio peaks via ffmpeg astats RMS analysis."""
import re
import subprocess
from pathlib import Path
from typing import Iterator

import numpy as np

from clipper.util.json_io import write_json
from clipper.util.logging import get_logger

logger = get_logger(__name__)

_TIME_RE = re.compile(r"pts_time:([\d.]+)")
# Match a float OR "-inf"/"inf". Silent windows emit -inf from astats.
_RMS_RE = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?inf|-?\d+(?:\.\d+)?)")

# Treat silence (-inf) as a very low dB floor so it participates in baseline math
# instead of being silently dropped.
_SILENCE_DB = -100.0


def parse_rms_log(path: Path) -> Iterator[tuple[float, float]]:
    """Yield (time_s, rms_db) pairs from an ffmpeg astats+ametadata output file.

    `-inf` RMS values (complete-silence windows) are emitted as `_SILENCE_DB`
    so the time series stays evenly-sampled for rolling-median baseline math.
    """
    current_time: float | None = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            tm = _TIME_RE.search(line)
            if tm:
                current_time = float(tm.group(1))
                continue
            rm = _RMS_RE.search(line)
            if rm and current_time is not None:
                raw = rm.group(1)
                db = _SILENCE_DB if "inf" in raw else float(raw)
                yield (current_time, db)


def _detect_from_samples(
    samples: list[tuple[float, float]],
    *,
    db_above_baseline: float,
    min_duration_seconds: float,
    merge_gap_seconds: float,
) -> list[dict]:
    """Detect peaks from an in-memory (time, db) series."""
    if not samples:
        return []
    times = np.array([t for t, _ in samples])
    dbs = np.array([d for _, d in samples])

    sample_dt = times[1] - times[0] if len(times) > 1 else 0.25
    window_samples = max(4, int(60.0 / sample_dt))
    baseline = np.median(dbs[:window_samples]) if len(dbs) > 0 else 0.0
    if len(dbs) > window_samples:
        baseline_series = np.array([
            np.median(dbs[max(0, i - window_samples // 2): i + window_samples // 2 + 1])
            for i in range(len(dbs))
        ])
    else:
        baseline_series = np.full_like(dbs, baseline)

    flagged = dbs > (baseline_series + db_above_baseline)

    peaks: list[dict] = []
    i = 0
    while i < len(flagged):
        if not flagged[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(flagged) and flagged[j + 1]:
            j += 1
        t_start = float(times[i])
        t_end = float(times[j] + sample_dt)
        intensity = float(np.max(dbs[i:j + 1] - baseline_series[i:j + 1]))
        if t_end - t_start >= min_duration_seconds:
            if peaks and t_start - peaks[-1]["t_end"] <= merge_gap_seconds:
                peaks[-1]["t_end"] = t_end
                peaks[-1]["intensity"] = max(peaks[-1]["intensity"], intensity)
            else:
                peaks.append({"t_start": t_start, "t_end": t_end, "intensity": intensity})
        i = j + 1
    return peaks


def detect_audio_peaks(
    audio_path: Path,
    work_dir: Path,
    *,
    db_above_baseline: float = 6.0,
    min_duration_seconds: float = 1.0,
    merge_gap_seconds: float = 2.0,
    target_count: int = 40,
) -> Path:
    """Extract RMS, detect peaks, write audio_peaks.json.

    Caps output at `target_count` by keeping the highest-intensity peaks
    (dB above local baseline). For action games like Sekiro the raw detector
    can produce hundreds of peaks (every attack, scream, music swell) which
    floods downstream candidate-merging. The cap focuses on the loudest
    "audio moments" — screams, big reactions — without dropping the category.
    """
    out = work_dir / "audio_peaks.json"
    if out.exists():
        logger.info(f"Skipping audio peak detection; {out} exists")
        return out
    log_path = work_dir / "rms.log"
    if not log_path.exists():
        logger.info(f"Computing RMS log -> {log_path}")
        # `length=0.25` defines the sliding window over which RMS is computed;
        # `reset=1` resets cumulative stats after every frame so each emission
        # describes one 250 ms slice. Combined with `asetnsamples=n=12000`
        # (12000 samples at 48 kHz = 250 ms) we get exactly one metadata line
        # per 250 ms of audio, which is what `_detect_from_samples` expects.
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(audio_path),
            "-af",
            f"aresample=48000,asetnsamples=n=12000:p=0,"
            f"astats=metadata=1:length=0.25:reset=1,"
            f"ametadata=print:key=lavfi.astats.Overall.RMS_level:file={log_path.as_posix()}",
            "-f", "null", "-",
        ], check=True)
    samples = list(parse_rms_log(log_path))
    peaks = _detect_from_samples(
        samples,
        db_above_baseline=db_above_baseline,
        min_duration_seconds=min_duration_seconds,
        merge_gap_seconds=merge_gap_seconds,
    )

    # Cap by intensity — keep the loudest "moments" and discard the long tail of
    # mid-range peaks (especially common in action games / music streams).
    total_detected = len(peaks)
    if len(peaks) > target_count:
        peaks.sort(key=lambda p: p["intensity"], reverse=True)
        peaks = sorted(peaks[:target_count], key=lambda p: p["t_start"])

    write_json(out, peaks)
    logger.info(
        f"Wrote {len(peaks)} audio peaks to {out}"
        + (f" (capped from {total_detected})" if total_detected > len(peaks) else "")
    )
    return out
