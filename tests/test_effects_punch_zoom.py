from clipper.captions import AssBuilder
from clipper.effects.context import EffectContext
from clipper.effects.punch_zoom import PunchZoom


def _ctx_with_peaks(audio_peaks, clip_start=5.0, clip_end=15.0):
    return EffectContext(
        clip={"id": "c001", "t_start": clip_start, "t_end": clip_end},
        transcript_words=[],
        audio_peaks=audio_peaks,
        chat_peaks=[],
        face_track=None,
        output_size=(1080, 1920),
        ass=AssBuilder(1080, 1920),
    )


def test_no_audio_peaks_means_no_filter_appended():
    ctx = _ctx_with_peaks(audio_peaks=[])
    PunchZoom().apply(ctx)
    assert ctx.extra_filters == []


def test_audio_peak_above_threshold_appends_zoompan_filter():
    # Peak at t=5.5 with intensity 14.2 (> 8 dB threshold). Window is [5.0, 15.0],
    # so clip-local peak start is 0.5s.
    ctx = _ctx_with_peaks(audio_peaks=[{"t_start": 5.5, "t_end": 6.1, "intensity": 14.2}])
    PunchZoom().apply(ctx)
    assert len(ctx.extra_filters) == 1
    f = ctx.extra_filters[0]
    assert "zoompan" in f or "scale" in f
    # The expression should reference clip-local time (0.5s), not source-relative (5.5s).
    assert "0.5" in f


def test_subthreshold_peak_is_ignored():
    ctx = _ctx_with_peaks(audio_peaks=[{"t_start": 5.5, "t_end": 6.1, "intensity": 4.0}])
    PunchZoom().apply(ctx)
    assert ctx.extra_filters == []


def test_multiple_peaks_emit_multiple_filters():
    ctx = _ctx_with_peaks(audio_peaks=[
        {"t_start": 5.5, "t_end": 6.1, "intensity": 14.2},
        {"t_start": 12.0, "t_end": 12.4, "intensity": 9.5},
    ])
    PunchZoom().apply(ctx)
    assert len(ctx.extra_filters) == 2


def test_name_and_default_enabled():
    e = PunchZoom()
    assert e.name == "punch_zoom"
    assert e.default_enabled is True
