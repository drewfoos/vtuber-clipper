"""Reaction zoom: 10% tighter crop window around the avatar at the moment of
the biggest combined audio+chat reaction in the clip."""
from dataclasses import dataclass

from clipper.effects.context import EffectContext
from clipper.effects.registry import register

ZOOM_WINDOW_S = 0.8
ZOOM_FACTOR = 1.10  # 10% tighter


@dataclass
class ReactionZoom:
    name: str = "reaction_zoom"
    default_enabled: bool = True

    def apply(self, ctx: EffectContext) -> None:
        clip_start = ctx.clip["t_start"]

        # Score every peak by source kind, then pick the timestamp with highest score.
        scored: list[tuple[float, float]] = []   # (t_center, score)
        for p in ctx.audio_peaks:
            t = (p["t_start"] + p["t_end"]) / 2 - clip_start
            scored.append((t, float(p["intensity"])))
        for p in ctx.chat_peaks:
            t = (p["t_start"] + p["t_end"]) / 2 - clip_start
            scored.append((t, float(p["hype_score"])))

        if not scored:
            return

        best_t, _ = max(scored, key=lambda x: x[1])
        zoom_start = max(0.0, best_t - ZOOM_WINDOW_S / 2)
        zoom_end = zoom_start + ZOOM_WINDOW_S
        expr = (
            f"if(between(t,{zoom_start:.3f},{zoom_end:.3f}),{ZOOM_FACTOR},1)"
        )
        ctx.extra_filters.append(
            f"zoompan=z='{expr}':d=1:s={ctx.output_size[0]}x{ctx.output_size[1]}:fps=30"
        )


register(ReactionZoom())
