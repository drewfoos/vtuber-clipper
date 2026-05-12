"""Punch zoom: scale 1.0 → 1.08 → 1.0 over ~0.4s on audio peaks."""
from dataclasses import dataclass

from clipper.effects.context import EffectContext
from clipper.effects.registry import register

PUNCH_THRESHOLD_DB = 8.0
PUNCH_DURATION_S = 0.4
PUNCH_PEAK_SCALE = 1.08


@dataclass
class PunchZoom:
    name: str = "punch_zoom"
    default_enabled: bool = True

    def apply(self, ctx: EffectContext) -> None:
        clip_start = ctx.clip["t_start"]
        for peak in ctx.audio_peaks:
            if peak["intensity"] < PUNCH_THRESHOLD_DB:
                continue
            t_local = peak["t_start"] - clip_start
            t_end = t_local + PUNCH_DURATION_S
            # Sinusoidal ramp: 1.0 → 1.08 → 1.0 over PUNCH_DURATION_S using sin(PI*x).
            # zoompan with z expression keyed on t (input timestamp).
            expr = (
                f"if(between(t,{t_local:.3f},{t_end:.3f}),"
                f"1+{PUNCH_PEAK_SCALE - 1:.3f}*sin((t-{t_local:.3f})*PI/{PUNCH_DURATION_S}),1)"
            )
            ctx.extra_filters.append(
                f"zoompan=z='{expr}':d=1:s={ctx.output_size[0]}x{ctx.output_size[1]}:fps=30"
            )


register(PunchZoom())
