import tempfile
from datetime import datetime, timezone
from pathlib import Path

from clipper.captions import generate_basic_ass, generate_srt
from clipper.util.ffmpeg import FINAL, encode_clip
from clipper.util.json_io import read_json, write_json
from clipper.util.logging import get_logger
from clipper.util.slug import slugify
from clipper.util.transcript import load_transcript, words_in_window

logger = get_logger(__name__)


def _kept_clips(work_dir: Path) -> list[dict]:
    state = read_json(work_dir / "review_state.json")
    return [
        {"id": cid, **data} for cid, data in state["clips"].items() if data.get("kept", True)
    ]


def finalize(work_dir: Path, out_root: Path) -> Path:
    final_dir = out_root / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    video = work_dir / "video.mp4"
    transcript = load_transcript(work_dir)
    kept = _kept_clips(work_dir)

    manifest_clips = []
    for idx, clip in enumerate(kept, start=1):
        slug = slugify(clip["title"], index=idx)
        base = final_dir / slug
        words = words_in_window(transcript, clip["t_start"], clip["t_end"])
        duration = clip["t_end"] - clip["t_start"]
        mode = clip.get("caption_mode", "burned")

        burned_path = None
        clean_path = None
        srt_path = None

        if mode in ("burned", "both"):
            with tempfile.NamedTemporaryFile(
                "w", suffix=".ass", delete=False, encoding="utf-8"
            ) as f:
                f.write(generate_basic_ass(words, clip["t_start"], (FINAL.width, FINAL.height)))
                ass_path = Path(f.name)
            try:
                burned_path = base.with_suffix(".mp4")
                encode_clip(video, clip["t_start"], duration, burned_path, FINAL,
                            subtitles_path=ass_path)
            finally:
                ass_path.unlink(missing_ok=True)

        if mode in ("clean", "both"):
            if mode == "both":
                clean_path = base.with_name(base.name + "_clean").with_suffix(".mp4")
            else:
                clean_path = base.with_suffix(".mp4")
            encode_clip(video, clip["t_start"], duration, clean_path, FINAL)
            srt_path = base.with_suffix(".srt")
            srt_path.write_text(generate_srt(words, clip["t_start"]))

        manifest_clips.append({
            "filename": burned_path.name if burned_path else clean_path.name,
            "clean_filename": clean_path.name if (mode == "both" and clean_path) else None,
            "srt_filename": srt_path.name if srt_path else None,
            "title": clip["title"],
            "t_start_source": clip["t_start"],
            "t_end_source": clip["t_end"],
            "duration": duration,
            "caption_mode": mode,
            "effects_applied": ["captions"] if mode != "clean" else [],
            "score": clip.get("score", 0),
            "hook_quality": clip.get("hook_quality", 0),
            "reason": clip.get("reason", ""),
            "top_emotes": clip.get("top_emotes", []),
        })

    manifest = {
        "vod_id": work_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "clips": manifest_clips,
    }
    write_json(final_dir / "manifest.json", manifest)
    logger.info(f"Finalized {len(manifest_clips)} clips to {final_dir}")
    return final_dir / "manifest.json"
