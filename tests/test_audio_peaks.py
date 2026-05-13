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


def test_filter_to_speech_overlap_cases():
    """Verify peak/word overlap detection: contained, edge-touching, no-overlap."""
    from clipper.audio_peaks import _filter_to_speech

    peaks = [
        {"t_start": 0.0, "t_end": 2.0, "intensity": 10},   # contains word at 0.5-1.0
        {"t_start": 5.0, "t_end": 7.0, "intensity": 10},   # no words in this range
        {"t_start": 10.0, "t_end": 12.0, "intensity": 10}, # word at 11-13 (overlap)
        {"t_start": 20.0, "t_end": 22.0, "intensity": 10}, # word at 19-20.5 (overlap)
        {"t_start": 30.0, "t_end": 32.0, "intensity": 10}, # word ends at 30 EXACTLY (no overlap)
    ]
    words = [
        {"start": 0.5, "end": 1.0, "word": "in"},
        {"start": 11.0, "end": 13.0, "word": "after"},
        {"start": 19.0, "end": 20.5, "word": "before"},
        {"start": 28.0, "end": 30.0, "word": "edge"},  # ends exactly at 30; no overlap
    ]
    out = _filter_to_speech(peaks, words)
    starts = [p["t_start"] for p in out]
    assert 0.0 in starts
    assert 5.0 not in starts          # no word overlaps [5, 7)
    assert 10.0 in starts
    assert 20.0 in starts
    assert 30.0 not in starts         # word.end == peak.t_start is not overlap


def test_filter_to_speech_empty_words_passes_through():
    from clipper.audio_peaks import _filter_to_speech
    peaks = [{"t_start": 0.0, "t_end": 1.0, "intensity": 5}]
    assert _filter_to_speech(peaks, []) == peaks


def test_detect_audio_peaks_with_transcript_filters_non_speech(tmp_path: Path):
    """When transcript_path is given, peaks not overlapping speech are dropped."""
    from clipper.audio_peaks import detect_audio_peaks

    # 3 elevated peaks at t=2-3, t=5-6, t=10-11.
    # Transcript only covers t=2-3 and t=10-11 — middle peak should be filtered.
    lines = []
    t = 0.0
    for intensity in [-30, -30, -30, -30, -30, -30, -30, -30,   # 0-2s silence
                      -10, -10, -10, -10,                        # 2-3s peak
                      -30, -30, -30, -30, -30, -30, -30, -30,   # 3-5s silence
                      -10, -10, -10, -10,                        # 5-6s peak
                      -30, -30, -30, -30, -30, -30, -30, -30,
                      -30, -30, -30, -30, -30, -30, -30, -30,   # 6-10s silence
                      -10, -10, -10, -10]:                       # 10-11s peak
        lines.append(f"frame:0 pts_time:{t:.2f}\nlavfi.astats.Overall.RMS_level={intensity}")
        t += 0.25
    log = tmp_path / "rms.log"
    log.write_text("\n".join(lines), encoding="utf-8")

    transcript_path = tmp_path / "transcript.json"
    import json
    transcript_path.write_text(json.dumps({
        "segments": [
            {"start": 2.0, "end": 3.0, "text": "hello", "words": [
                {"start": 2.2, "end": 2.8, "word": "hello"},
            ]},
            {"start": 10.0, "end": 11.0, "text": "wow", "words": [
                {"start": 10.3, "end": 10.7, "word": "wow"},
            ]},
        ],
    }), encoding="utf-8")

    out = detect_audio_peaks(
        tmp_path / "nope.opus", tmp_path,
        db_above_baseline=6.0,
        min_duration_seconds=0.5,
        merge_gap_seconds=0.5,
        target_count=40,
        transcript_path=transcript_path,
    )
    peaks = json.loads(out.read_text(encoding="utf-8"))
    # Expect 2 peaks — the middle one (5-6s, no speech) dropped.
    assert len(peaks) == 2
    starts = sorted(p["t_start"] for p in peaks)
    assert 1.9 <= starts[0] <= 2.1
    assert 9.9 <= starts[1] <= 10.1


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
