from pathlib import Path

from clipper.captions import AssBuilder
from clipper.effects.context import EffectContext
from clipper.effects.emoji_burst import EmojiBurst


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "assets"


def _ctx(chat_peaks):
    return EffectContext(
        clip={"id": "c001", "t_start": 5.0, "t_end": 15.0},
        transcript_words=[],
        audio_peaks=[],
        chat_peaks=chat_peaks,
        face_track=None,
        output_size=(1080, 1920),
        ass=AssBuilder(1080, 1920),
        assets_dir=ASSETS,
    )


def test_no_chat_peaks_no_filter():
    ctx = _ctx(chat_peaks=[])
    EmojiBurst().apply(ctx)
    assert ctx.extra_filters == []


def test_one_chat_peak_appends_overlay_filter():
    chat = [{"t_start": 5.8, "t_end": 8.2, "msg_count": 142, "hype_score": 87.0, "top_emotes": ["KEKW"]}]
    ctx = _ctx(chat_peaks=chat)
    EmojiBurst().apply(ctx)
    # Expect one overlay filter referencing a PNG.
    assert len(ctx.extra_filters) >= 1
    assert any("overlay=" in f and ".png" in f for f in ctx.extra_filters)


def test_picks_deterministic_emoji_for_same_emote():
    # Same input emote → same emoji choice across runs.
    chat = [{"t_start": 5.8, "t_end": 8.2, "msg_count": 142, "hype_score": 87.0, "top_emotes": ["KEKW"]}]
    ctx_a = _ctx(chat_peaks=chat)
    ctx_b = _ctx(chat_peaks=chat)
    EmojiBurst().apply(ctx_a)
    EmojiBurst().apply(ctx_b)
    assert ctx_a.extra_filters == ctx_b.extra_filters


def test_missing_assets_dir_skips():
    chat = [{"t_start": 5.8, "t_end": 8.2, "msg_count": 142, "hype_score": 87.0, "top_emotes": ["KEKW"]}]
    ctx = _ctx(chat_peaks=chat)
    ctx.assets_dir = None
    EmojiBurst().apply(ctx)
    assert ctx.extra_filters == []


def test_name_and_default_enabled():
    e = EmojiBurst()
    assert e.name == "emoji_burst"
    assert e.default_enabled is True
