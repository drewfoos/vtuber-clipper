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
_RMS_RE = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?\d+(?:\.\d+)?)")


def parse_rms_log(path: Path) -> Iterator[tuple[float, float]]:
    """Yield (time_s, rms_db) pairs from an ffmpeg astats+ametadata output file."""
    current_time: float | None = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            tm = _TIME_RE.search(line)
            if tm:
                current_time = float(tm.group(1))
                continue
            rm = _RMS_RE.search(line)
            if rm and current_time is not None:
                yield (current_time, float(rm.group(1)))


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
) -> Path:
    """Extract RMS, detect peaks, write audio_peaks.json."""
    out = work_dir / "audio_peaks.json"
    if out.exists():
        logger.info(f"Skipping audio peak detection; {out} exists")
        return out
    log_path = work_dir / "rms.log"
    if not log_path.exists():
        logger.info(f"Computing RMS log -> {log_path}")
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(audio_path),
            "-af",
            f"astats=metadata=1:reset=0.25,ametadata=print:key=lavfi.astats.Overall.RMS_level:file={log_path.as_posix()}",
            "-f", "null", "-",
        ], check=True)
    samples = list(parse_rms_log(log_path))
    peaks = _detect_from_samples(
        samples,
        db_above_baseline=db_above_baseline,
        min_duration_seconds=min_duration_seconds,
        merge_gap_seconds=merge_gap_seconds,
    )
    write_json(out, peaks)
    logger.info(f"Wrote {len(peaks)} audio peaks to {out}")
    return out
