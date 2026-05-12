from typing import Protocol

class FinalizeEffect(Protocol):
    name: str
    default_enabled: bool

    def apply(self, ctx: dict) -> None: ...
