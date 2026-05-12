from typing import Protocol

from clipper.effects.context import EffectContext


class FinalizeEffect(Protocol):
    """One step in the finalize effect chain. Concrete effects mutate the
    shared EffectContext (ass + extra_filters) based on its clip metadata,
    peaks, and face track.

    Effects should be idempotent: calling apply twice with the same context
    must produce the same result. They must gracefully no-op when their
    required inputs are missing (e.g., emoji_burst with empty chat_peaks).
    """

    name: str
    """Stable identifier matching the effects/registry key (e.g. 'punch_zoom').
    Used as the key in ClipState.effects and the manifest's effects_applied."""

    default_enabled: bool
    """Per-clip default when ClipState.effects has no override."""

    def apply(self, ctx: EffectContext) -> None: ...
