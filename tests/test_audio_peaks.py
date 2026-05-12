from pathlib import Path

from clipper.audio_peaks import detect_audio_peaks, parse_rms_log

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_rms_log_yields_time_db_pairs():
    samples = list(parse_rms_log(FIXTURES / "rms.sample.log"))
    assert len(samples) == 30
    assert samples[0] == (0.0, -30.0)
    # The big peak around t=2.25.
    assert any(t == 2.25 and -13.0 <= db <= -12.0 for t, db in samples)


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
