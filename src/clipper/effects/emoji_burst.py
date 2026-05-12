"""Emoji burst: overlay a Twemoji PNG at chat-peak moments.

Picks a deterministic emoji per peak based on a hash of the top emote so
that re-runs of finalize on the same clip produce the same overlay choices.
"""
import hashlib
from dataclasses import dataclass

from clipper.effects.context import EffectContext
from clipper.effects.registry import register

EMOJI_FILES = ["1f602.png", "1f480.png", "1f525.png", "1f631.png", "2728.png", "1f44f.png"]
EMOJI_SIZE = 180   # px in the 1080x1920 frame
EMOJI_VISIBLE_S = 0.8


def _pick_emoji_for(top_emote: str) -> str:
    h = hashlib.sha1(top_emote.encode("utf-8")).digest()
    return EMOJI_FILES[h[0] % len(EMOJI_FILES)]


@dataclass
class EmojiBurst:
    name: str = "emoji_burst"
    default_enabled: bool = True

    def apply(self, ctx: EffectContext) -> None:
        if ctx.assets_dir is None:
            return
        clip_start = ctx.clip["t_start"]
        for peak in ctx.chat_peaks:
            emotes = peak.get("top_emotes", [])
            if not emotes:
                continue
            emoji_path = ctx.assets_dir / "emojis" / _pick_emoji_for(emotes[0])
            if not emoji_path.exists():
                continue
            t_local = (peak["t_start"] + peak["t_end"]) / 2 - clip_start
            t_end = t_local + EMOJI_VISIBLE_S
            # Position based on hash → upper-left, upper-right, mid-right.
            h = hashlib.sha1(emotes[0].encode("utf-8")).digest()[1] % 3
            x = {0: "main_w*0.10", 1: "main_w*0.65", 2: "main_w*0.70"}[h]
            y = {0: "main_h*0.15", 1: "main_h*0.18", 2: "main_h*0.55"}[h]
            # ffmpeg overlay enable expr: between(t, t_local, t_end).
            esc = str(emoji_path).replace("\\", "/").replace(":", "\\:")
            # movie filter to source the PNG, scaled, then overlay onto the main stream.
            ctx.extra_filters.append(
                f"movie='{esc}',scale={EMOJI_SIZE}:{EMOJI_SIZE}[em{int(t_local * 1000)}];"
                f"[in][em{int(t_local * 1000)}]overlay={x}:{y}:"
                f"enable='between(t,{t_local:.3f},{t_end:.3f})'[out]"
            )


register(EmojiBurst())
