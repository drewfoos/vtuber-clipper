import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from clipper.util.json_io import read_json, write_json
from clipper.util.transcript import load_transcript, words_in_window

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
    caption_style: Literal["basic", "window3"] = "window3"
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
    caption_style: Literal["basic", "window3"] | None = None
    effects: dict[str, bool] | None = None

def _initial_clips(work_dir: Path) -> dict[str, ClipState]:
    ranked = read_json(work_dir / "ranked.json")
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
        saved = read_json(state_path)
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
    write_json(work_dir / "review_state.json", payload)

def build_app(work_dir: Path, out_root: Path | None = None) -> FastAPI:
    app = FastAPI()
    app.state.work_dir = work_dir
    app.state.clips = _initial_clips(work_dir)
    app.state.should_exit = False
    import time as _time
    app.state.last_request_at = _time.monotonic()

    @app.middleware("http")
    async def track_activity(request, call_next):
        app.state.last_request_at = _time.monotonic()
        return await call_next(request)

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

    from fastapi import Request
    from clipper.util.range_response import range_or_full

    @app.get("/api/clips/{clip_id}/preview.mp4")
    def get_preview(clip_id: str, request: Request):
        if clip_id not in app.state.clips:
            raise HTTPException(404, "no such clip")
        path = work_dir / "previews" / f"{clip_id}.mp4"
        return range_or_full(request, path)

    @app.get("/api/clips/{clip_id}/transcript")
    def get_transcript(clip_id: str) -> list[dict]:
        if clip_id not in app.state.clips:
            raise HTTPException(404, "no such clip")
        clip = app.state.clips[clip_id]
        return words_in_window(load_transcript(work_dir), clip.t_start, clip.t_end)

    from fastapi.responses import StreamingResponse
    from clipper.finalize import finalize as _finalize_call

    _out_root = out_root if out_root is not None else (work_dir.parent.parent / "out" / work_dir.name)

    @app.post("/api/finalize")
    def post_finalize():
        def event_stream():
            try:
                kept_count = sum(1 for c in app.state.clips.values() if c.kept)
                yield f"data: {json.dumps({'status': 'started', 'kept_count': kept_count})}\n\n"
                manifest = _finalize_call(work_dir, _out_root)
                yield f"data: {json.dumps({'status': 'complete', 'manifest': str(manifest)})}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'status': 'error', 'msg': str(exc)})}\n\n"
        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/api/shutdown")
    def shutdown():
        app.state.should_exit = True
        return {"status": "shutting down"}

    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    web_dir = Path(__file__).parent / "web"
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/")
    def index():
        return FileResponse(web_dir / "index.html")

    return app
