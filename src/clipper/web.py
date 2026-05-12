import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

DEFAULT_EFFECTS = {
    "punch_zoom": True,
    "emoji_burst": True,
    "hook_card": True,
    "reaction_zoom": True,
}

class ClipState(BaseModel):
    id: str
    title: str
    t_start: float
    t_end: float
    kept: bool = True
    caption_mode: Literal["burned", "clean", "both"] = "burned"
    effects: dict[str, bool] = DEFAULT_EFFECTS.copy()
    score: int
    hook_quality: int
    reason: str
    top_emotes: list[str]

def _load_initial_clips(work_dir: Path) -> list[ClipState]:
    ranked = json.loads((work_dir / "ranked.json").read_text())
    return [
        ClipState(
            id=c["id"],
            title=c["title"],
            t_start=c["t_start_refined"],
            t_end=c["t_end_refined"],
            score=c["score"],
            hook_quality=c.get("hook_quality", 0),
            reason=c.get("reason", ""),
            top_emotes=c.get("top_emotes", []),
        )
        for c in ranked
    ]

def build_app(work_dir: Path) -> FastAPI:
    app = FastAPI()
    app.state.work_dir = work_dir
    app.state.clips = {c.id: c for c in _load_initial_clips(work_dir)}

    @app.get("/api/clips")
    def list_clips() -> list[ClipState]:
        return list(app.state.clips.values())

    return app
