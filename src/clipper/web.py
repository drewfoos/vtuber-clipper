import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DEFAULT_EFFECTS = {
    "punch_zoom": True,
    "emoji_burst": True,
    "hook_card": True,
    "reaction_zoom": True,
}
STATE_SCHEMA_VERSION = "0.1.0"
MIN_CLIP_SECONDS = 2.0

class ClipState(BaseModel):
    id: str
    title: str
    t_start: float
    t_end: float
    kept: bool = True
    caption_mode: Literal["burned", "clean", "both"] = "burned"
    effects: dict[str, bool] = Field(default_factory=lambda: DEFAULT_EFFECTS.copy())
    score: int
    hook_quality: int
    reason: str
    top_emotes: list[str]

class ClipUpdate(BaseModel):
    title: str | None = None
    t_start: float | None = None
    t_end: float | None = None
    kept: bool | None = None
    caption_mode: Literal["burned", "clean", "both"] | None = None
    effects: dict[str, bool] | None = None

def _initial_clips(work_dir: Path) -> dict[str, ClipState]:
    ranked = json.loads((work_dir / "ranked.json").read_text())
    base = {
        c["id"]: ClipState(
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
    }
    state_path = work_dir / "review_state.json"
    if state_path.exists():
        saved = json.loads(state_path.read_text())
        for cid, overrides in saved.get("clips", {}).items():
            if cid in base:
                merged = base[cid].model_dump()
                merged.update(overrides)
                base[cid] = ClipState(**merged)
    return base

def _persist(work_dir: Path, clips: dict[str, ClipState]) -> None:
    payload = {
        "vod_id": work_dir.name,
        "schema_version": STATE_SCHEMA_VERSION,
        "last_modified": datetime.now(timezone.utc).isoformat(),
        "clips": {cid: c.model_dump() for cid, c in clips.items()},
    }
    (work_dir / "review_state.json").write_text(json.dumps(payload, indent=2))

def build_app(work_dir: Path) -> FastAPI:
    app = FastAPI()
    app.state.work_dir = work_dir
    app.state.clips = _initial_clips(work_dir)

    @app.get("/api/clips")
    def list_clips() -> list[ClipState]:
        return list(app.state.clips.values())

    @app.put("/api/clips/{clip_id}")
    def update_clip(clip_id: str, patch: ClipUpdate) -> ClipState:
        if clip_id not in app.state.clips:
            raise HTTPException(404, "no such clip")
        current = app.state.clips[clip_id]
        merged = current.model_dump()
        for k, v in patch.model_dump(exclude_none=True).items():
            merged[k] = v
        if merged["t_end"] - merged["t_start"] < MIN_CLIP_SECONDS:
            raise HTTPException(400, f"clip must be at least {MIN_CLIP_SECONDS}s")
        updated = ClipState(**merged)
        app.state.clips[clip_id] = updated
        _persist(work_dir, app.state.clips)
        return updated

    return app
