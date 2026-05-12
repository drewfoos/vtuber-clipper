from dataclasses import dataclass, field
from pathlib import Path

from clipper.captions import AssBuilder


@dataclass
class EffectContext:
    """All the per-clip data an effect needs to render itself.

    Effects mutate `ass` (add dialogue layers, draws, etc.) and/or append to
    `extra_filters` (ffmpeg filter fragments composed left-to-right).
    They are called in registry order; each one sees the cumulative state.
    """
    clip: dict
    """The clip dict from review_state.json (id, title, t_start, t_end, kept,
    effects, caption_mode, caption_style, score, hook_quality, top_emotes, ...)."""

    transcript_words: list[dict]
    """Words within [clip.t_start, clip.t_end), in source-video seconds."""

    audio_peaks: list[dict]
    """Audio peaks overlapping the clip window. May be empty."""

    chat_peaks: list[dict]
    """Chat peaks overlapping the clip window. May be empty."""

    face_track: dict | None
    """Per-clip face track (fps_sampled + track) or None if missing."""

    output_size: tuple[int, int]
    """Final output dimensions (width, height) for ASS PlayRes math."""

    ass: AssBuilder
    """Cumulative ASS document. Effects call .add_dialogue() / .add_style()."""

    extra_filters: list[str] = field(default_factory=list)
    """ffmpeg filter fragments to compose into the encode_clip call."""

    assets_dir: Path | None = None
    """Path to the bundled assets/ directory (for emoji PNGs etc.)."""
