"""Hook card: "WAIT FOR IT" overlay on the first 1.5s when hook_quality >= 7."""
from dataclasses import dataclass

from clipper.effects.context import EffectContext
from clipper.effects.registry import register

HOOK_QUALITY_THRESHOLD = 7
HOOK_CARD_DURATION_S = 1.5
HOOK_CARD_TEXT = "WAIT FOR IT"


@dataclass
class HookCard:
    name: str = "hook_card"
    default_enabled: bool = True

    def apply(self, ctx: EffectContext) -> None:
        if ctx.clip.get("hook_quality", 0) < HOOK_QUALITY_THRESHOLD:
            return
        ctx.ass.add_style(
            name="HookCard",
            fontname="Arial Black",
            fontsize=64,
            primary="&H00FFFFFF&",
            outline="&H006633FF&",   # pink-red outline
            outline_width=6,
            margin_v=1500,           # near top of 9:16 frame
            alignment=8,             # top-center
        )
        # \fad(150,300): 150ms fade-in, 300ms fade-out.
        text = "{\\fad(150,300)}" + HOOK_CARD_TEXT
        ctx.ass.add_dialogue(0.0, HOOK_CARD_DURATION_S, text, style="HookCard")


register(HookCard())
