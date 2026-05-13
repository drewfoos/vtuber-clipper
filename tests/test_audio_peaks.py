from pathlib import Path

from clipper.audio_peaks import detect_audio_peaks, parse_rms_log

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_rms_log_yields_time_db_pairs():
    samples = list(parse_rms_log(FIXTURES / "rms.sample.log"))
    assert len(samples) == 30
    assert samples[0] == (0.0, -30.0)
    # The big peak around t=2.25.
    assert any(t == 2.25 and -13.0 <= db <= -12.0 for t, db in samples)


def test_parse_rms_log_handles_inf_silence(tmp_path: Path):
    """Silent windows emit `-inf` from astats; parser maps them to a low dB floor."""
    log = tmp_path / "silent.log"
    log.write_text(
        "frame:0 pts_time:0\n"
        "lavfi.astats.Overall.RMS_level=-inf\n"
        "frame:1 pts_time:0.25\n"
        "lavfi.astats.Overall.RMS_level=-20.0\n"
        "frame:2 pts_time:0.5\n"
        "lavfi.astats.Overall.RMS_level=-inf\n",
        encoding="utf-8",
    )
    samples = list(parse_rms_log(log))
    assert len(samples) == 3
    assert samples[0][1] < -50  # silence floor
    assert samples[1][1] == -20.0
    assert samples[2][1] < -50


def test_detect_audio_peaks_finds_obvious_peak(tmp_path: Path):
    import shutil
    audio_log = tmp_path / "rms.log"
    shutil.copy(FIXTURES / "rms.sample.log", audio_log)
    peaks = _detect_from_log(audio_log, db_above_baseline=6.0,
                             min_duration_seconds=0.5, merge_gap_seconds=1.0)
    # Single contiguous peak around t=2.0-2.5.
    assert len(peaks) == 1
    p = peaks[0]
    assert 1.9 <= p["t_start"] <= 2.1
    assert 2.4 <= p["t_end"] <= 2.8
    assert p["intensity"] > 10


def test_detect_audio_peaks_empty_when_flat(tmp_path: Path):
    flat = tmp_path / "rms.log"
    flat.write_text("\n".join(
        f"frame:{i} pts_time:{i * 0.25}\nlavfi.astats.Overall.RMS_level=-30.0"
        for i in range(30)
    ), encoding="utf-8")
    peaks = _detect_from_log(flat, db_above_baseline=6.0,
                             min_duration_seconds=0.5, merge_gap_seconds=1.0)
    assert peaks == []


def test_target_count_caps_audio_peaks_by_intensity(tmp_path: Path):
    """When the detector finds many peaks, only the loudest target_count survive."""
    from clipper.audio_peaks import detect_audio_peaks

    # Build a synthetic rms.log with 10 distinct peaks of varying intensity over
    # a long-enough silence so each peak is independently detected (>=1s).
    lines = []
    t = 0.0
    # Each "block" has 8 baseline samples then 4 elevated samples (1 second elevated).
    intensities = [-10, -8, -6, -4, -12, -14, -16, -18, -20, -22]
    for intensity in intensities:
        for _ in range(8):
            lines.append(f"frame:0 pts_time:{t:.2f}\nlavfi.astats.Overall.RMS_level=-30.0")
            t += 0.25
        for _ in range(4):
            lines.append(f"frame:0 pts_time:{t:.2f}\nlavfi.astats.Overall.RMS_level={intensity}")
            t += 0.25

    log = tmp_path / "rms.log"
    log.write_text("\n".join(lines), encoding="utf-8")

    # Pre-stage the rms.log so detect_audio_peaks doesn't invoke ffmpeg.
    # Use a non-existent audio path; the function only runs ffmpeg if rms.log is missing.
    out = detect_audio_peaks(
        tmp_path / "nope.opus", tmp_path,
        db_above_baseline=6.0,
        min_duration_seconds=0.5,
        merge_gap_seconds=0.5,
        target_count=3,
    )
    import json
    peaks = json.loads(out.read_text(encoding="utf-8"))
    assert len(peaks) == 3
    # Peaks should be the loudest three (intensities ~24, 22, 20 dB above baseline).
    intensities_kept = sorted(p["intensity"] for p in peaks)
    assert intensities_kept[-1] >= 23.0  # the -4 dB sample = 26 above -30 baseline
    # Output is sorted by t_start, so verify chronological order.
    starts = [p["t_start"] for p in peaks]
    assert starts == sorted(starts)


def _detect_from_log(log_path, *, db_above_baseline, min_duration_seconds, merge_gap_seconds):
    """Helper: bypass detect_audio_peaks's ffmpeg call to test detection logic directly."""
    from clipper.audio_peaks import _detect_from_samples
    samples = list(parse_rms_log(log_path))
    return _detect_from_samples(
        samples,
        db_above_baseline=db_above_baseline,
        min_duration_seconds=min_duration_seconds,
        merge_gap_seconds=merge_gap_seconds,
    )
