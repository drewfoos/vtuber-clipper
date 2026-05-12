"""Registry of available finalize effects.

Concrete effect implementations register themselves here. The finalize stage
iterates the registry, asks each effect whether it's enabled for the current
clip (per-clip override > registry default), and calls apply() in order.
"""
from clipper.effects.base import FinalizeEffect

# Filled in as effect modules are added (Tasks B10-B14).
REGISTRY: dict[str, FinalizeEffect] = {}


def register(effect: FinalizeEffect) -> FinalizeEffect:
    REGISTRY[effect.name] = effect
    return effect


def default_effects_config() -> dict[str, bool]:
    """Default per-clip effects flags built from REGISTRY."""
    return {name: e.default_enabled for name, e in REGISTRY.items()}
