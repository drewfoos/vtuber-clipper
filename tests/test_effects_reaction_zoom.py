from clipper.captions import AssBuilder
from clipper.effects.context import EffectContext
from clipper.effects.reaction_zoom import ReactionZoom


def _ctx(audio_peaks=None, chat_peaks=None):
    return EffectContext(
        clip={"id": "c001", "t_start": 5.0, "t_end": 15.0},
        transcript_words=[],
        audio_peaks=audio_peaks or [],
        chat_peaks=chat_peaks or [],
        face_track=None,
        output_size=(1080, 1920),
        ass=AssBuilder(1080, 1920),
    )


def test_no_peaks_no_filter():
    ctx = _ctx()
    ReactionZoom().apply(ctx)
    assert ctx.extra_filters == []


def test_combines_audio_and_chat_to_pick_biggest():
    # Audio peak at t=6.0 (intensity 5.0) → score 5
    # Chat peak at t=10.0 (hype 90.0)   → score 90
    # The biggest single-source score wins; the chat peak.
    # Chat peak center = (10.0 + 10.5) / 2 - 5.0 = 5.25 (clip-local)
    # zoom_start = 5.25 - 0.4 = 4.850, zoom_end = 5.250 + 0.4 = 5.650
    audio = [{"t_start": 6.0, "t_end": 6.5, "intensity": 5.0}]
    chat = [{"t_start": 10.0, "t_end": 10.5, "msg_count": 90, "hype_score": 90.0, "top_emotes": []}]
    ctx = _ctx(audio_peaks=audio, chat_peaks=chat)
    ReactionZoom().apply(ctx)
    assert len(ctx.extra_filters) == 1
    # Filter uses frame-number (on) variable at 30fps.
    # zoom_start = 4.850s → 145.5 frames; zoom_end = 5.650s → 169.5 frames.
    f = ctx.extra_filters[0]
    assert "145.5" in f or "169.5" in f


def test_combined_audio_and_chat_at_same_time_wins():
    audio = [{"t_start": 9.0, "t_end": 9.5, "intensity": 12.0}]
    chat = [{"t_start": 9.0, "t_end": 9.5, "msg_count": 50, "hype_score": 60.0, "top_emotes": []}]
    ctx = _ctx(audio_peaks=audio, chat_peaks=chat)
    ReactionZoom().apply(ctx)
    assert len(ctx.extra_filters) == 1


def test_name_and_default_enabled():
    e = ReactionZoom()
    assert e.name == "reaction_zoom"
    assert e.default_enabled is True
