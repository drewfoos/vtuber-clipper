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
        fps = 30
        for peak in ctx.audio_peaks:
            if peak["intensity"] < PUNCH_THRESHOLD_DB:
                continue
            t_local = peak["t_start"] - clip_start
            t_end = t_local + PUNCH_DURATION_S
            # Sinusoidal ramp: 1.0 → 1.08 → 1.0 over PUNCH_DURATION_S.
            # zoompan's z= expression only supports spatial variables; use on (output
            # frame number) instead of t (time) which is not available in z=.
            n_start = t_local * fps
            n_end = t_end * fps
            n_dur = PUNCH_DURATION_S * fps
            expr = (
                f"if(between(on,{n_start:.1f},{n_end:.1f}),"
                f"1+{PUNCH_PEAK_SCALE - 1:.3f}*sin((on-{n_start:.1f})*3.14159265358979/{n_dur:.1f}),1)"
            )
            ctx.extra_filters.append(
                f"zoompan=z='{expr}':d=1:s={ctx.output_size[0]}x{ctx.output_size[1]}:fps={fps}"
            )


register(PunchZoom())
