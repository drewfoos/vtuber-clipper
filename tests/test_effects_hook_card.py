from clipper.captions import AssBuilder
from clipper.effects.context import EffectContext
from clipper.effects.hook_card import HookCard


def _ctx(hook_quality):
    return EffectContext(
        clip={"id": "c001", "t_start": 5.0, "t_end": 15.0, "hook_quality": hook_quality},
        transcript_words=[],
        audio_peaks=[],
        chat_peaks=[],
        face_track=None,
        output_size=(1080, 1920),
        ass=AssBuilder(1080, 1920),
    )


def test_low_hook_quality_no_card():
    ctx = _ctx(hook_quality=5)
    HookCard().apply(ctx)
    assert ctx.ass.event_lines == []


def test_high_hook_quality_adds_dialogue():
    ctx = _ctx(hook_quality=9)
    HookCard().apply(ctx)
    assert len(ctx.ass.event_lines) >= 1
    # Card text appears in the rendered ASS.
    rendered = ctx.ass.render()
    assert "WAIT FOR IT" in rendered


def test_card_only_in_first_1p5_seconds():
    ctx = _ctx(hook_quality=9)
    HookCard().apply(ctx)
    line = ctx.ass.event_lines[0]
    # End time should be at or before 0:00:01.50 clip-local.
    assert "0:00:01.50" in line or "0:00:01.4" in line or "0:00:01.5" in line


def test_threshold_exclusive_at_7():
    ctx = _ctx(hook_quality=7)
    HookCard().apply(ctx)
    # >=7 triggers.
    assert ctx.ass.event_lines != []


def test_name_and_default_enabled():
    e = HookCard()
    assert e.name == "hook_card"
    assert e.default_enabled is True
