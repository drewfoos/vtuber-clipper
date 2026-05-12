"""Decide per-clip finalize layout from face-track summary."""
from typing import Literal

LayoutMode = Literal["tracking", "stacked", "static"]

MIN_HIT_RATE = 0.50
DEFAULT_TRACKING_BBOX_THRESHOLD = 0.25


def classify_layout(
    summary: dict,
    *,
    tracking_bbox_threshold: float = DEFAULT_TRACKING_BBOX_THRESHOLD,
    min_hit_rate: float = MIN_HIT_RATE,
) -> LayoutMode:
    """Pick a finalize layout for one clip given its face-track summary."""
    if summary.get("hit_rate", 0.0) < min_hit_rate or summary.get("avg_x") is None:
        return "static"
    if summary.get("avg_bbox_w", 0.0) >= tracking_bbox_threshold:
        return "tracking"
    return "stacked"
