import tempfile
from datetime import datetime, timezone
from pathlib import Path

from clipper.captions import AssBuilder, generate_ass, generate_srt
from clipper.effects import REGISTRY, EffectContext, default_effects_config
# Force-import effect modules so they self-register.
from clipper.effects import emoji_burst as _eb  # noqa: F401
from clipper.effects import hook_card as _hc    # noqa: F401
from clipper.effects import punch_zoom as _pz   # noqa: F401
from clipper.effects import reaction_zoom as _rz  # noqa: F401
from clipper.layout import LayoutMode, classify_layout
from clipper.util.ffmpeg import FINAL, encode_clip
from clipper.util.json_io import read_json, write_json
from clipper.util.logging import get_logger
from clipper.util.peaks import load_audio_peaks, load_chat_peaks, peaks_in_window
from clipper.util.slug import slugify
from clipper.util.transcript import load_transcript, words_in_window

logger = get_logger(__name__)


def _kept_clips(work_dir: Path) -> list[dict]:
    state = read_json(work_dir / "review_state.json")
    return [
        {"id": cid, **data} for cid, data in state["clips"].items() if data.get("kept", True)
    ]


def _stacked_filter(face_x: float, face_y: float, bbox_w: float,
                    source_w: int = 1920, source_h: int = 1080,
                    out_w: int = 1080, out_h: int = 1920) -> str:
    """Build ffmpeg complex-filter graph for stacked layout."""
    game_h = 608
    avatar_h = out_h - game_h
    crop_size = max(int(0.4 * source_w), int(3.0 * bbox_w * source_w))
    crop_size = min(crop_size, source_h)
    fx = max(crop_size // 2, min(source_w - crop_size // 2, int(face_x * source_w)))
    fy = max(crop_size // 2, min(source_h - crop_size // 2, int(face_y * source_h)))
    return (
        f"[0:v]split=2[g][a];"
        f"[g]scale={out_w}:{game_h}:force_original_aspect_ratio=decrease,"
        f"pad={out_w}:{game_h}:(ow-iw)/2:(oh-ih)/2[game];"
        f"[a]crop={crop_size}:{crop_size}:{fx - crop_size // 2}:{fy - crop_size // 2},"
        f"scale={out_w}:{avatar_h}[avatar];"
        f"[game][avatar]vstack[v]"
    )


def _encode_stacked(
    src: Path, t_start: float, duration: float, out: Path,
    face_x: float, face_y: float, bbox_w: float,
    subtitles_path: Path | None = None,
) -> None:
    """Encode a stacked-layout clip via -filter_complex."""
    import subprocess
    filter_complex = _stacked_filter(face_x, face_y, bbox_w)
    if subtitles_path is not None:
        escaped = str(subtitles_path).replace("\\", "/").replace(":", "\\:")
        filter_complex = filter_complex.replace("[v]", "[stacked]")
        filter_complex += f";[stacked]subtitles='{escaped}'[v]"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(t_start),
        "-i", str(src),
        "-t", str(duration),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "0:a",
        "-c:v", "h264_nvenc", "-preset", FINAL.nvenc_preset, "-cq:v", str(FINAL.cq),
        "-c:a", "aac", "-b:a", FINAL.audio_bitrate,
        "-movflags", "+faststart",
        str(out),
    ], check=True)


def finalize(work_dir: Path, out_root: Path) -> Path:
    final_dir = out_root / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    video = work_dir / "video.mp4"
    transcript = load_transcript(work_dir)
    audio_peaks = load_audio_peaks(work_dir)
    chat_peaks = load_chat_peaks(work_dir)
    face_track_data: dict = (read_json(work_dir / "face_track.json")
                              if (work_dir / "face_track.json").exists() else {})
    assets_dir = Path(__file__).resolve().parent / "assets"
    kept = _kept_clips(work_dir)

    manifest_clips = []
    for idx, clip in enumerate(kept, start=1):
        try:
            slug = slugify(clip["title"], index=idx)
            base = final_dir / slug
            words = words_in_window(transcript, clip["t_start"], clip["t_end"])
            duration = clip["t_end"] - clip["t_start"]
            mode = clip.get("caption_mode", "burned")
            style = clip.get("caption_style", "window3")

            # Build EffectContext and run the chain.
            clip_audio_peaks = peaks_in_window(audio_peaks, clip["t_start"], clip["t_end"])
            clip_chat_peaks = peaks_in_window(chat_peaks, clip["t_start"], clip["t_end"])
            clip_face = face_track_data.get(clip["id"])
            ass = AssBuilder(FINAL.width, FINAL.height)
            # Register Default style first so caption Dialogue lines (style=Default) resolve
            # correctly when effects later add their own named styles (e.g. HookCard).
            # Without this, render() would auto-add Default ONLY when style_lines is empty,
            # which fails after HookCard.add_style() runs.
            ass.add_style()
            # Seed captions into ass (the captions "effect" is special — always-on unless mode=clean).
            if mode in ("burned", "both"):
                seeded = generate_ass(style, words, clip["t_start"], (FINAL.width, FINAL.height))
                # The dispatcher returns a full ASS document. Parse out its Dialogue lines and
                # re-add them to our shared AssBuilder so effects can layer in.
                for line in seeded.splitlines():
                    if line.startswith("Dialogue:"):
                        ass.event_lines.append(line)
            ctx = EffectContext(
                clip=clip,
                transcript_words=words,
                audio_peaks=clip_audio_peaks,
                chat_peaks=clip_chat_peaks,
                face_track=clip_face,
                output_size=(FINAL.width, FINAL.height),
                ass=ass,
                assets_dir=assets_dir,
            )

            # Resolve effect-enabled flags: registry default <-- per-clip override.
            per_clip_overrides = clip.get("effects", {})
            effects_enabled = {**default_effects_config(), **per_clip_overrides}
            applied: list[str] = []
            for effect_name, on in effects_enabled.items():
                if not on:
                    continue
                effect = REGISTRY.get(effect_name)
                if effect is None:
                    continue
                before_filters = len(ctx.extra_filters)
                before_events = len(ctx.ass.event_lines)
                effect.apply(ctx)
                if len(ctx.extra_filters) > before_filters or len(ctx.ass.event_lines) > before_events:
                    applied.append(effect_name)
            if mode != "clean":
                applied.insert(0, "captions")

            # Layout decision (Plan D)
            layout_pref = clip.get("layout", "auto")
            clip_face_data = face_track_data.get(clip["id"], {})
            face_summary = clip_face_data.get("summary", {
                "avg_x": None, "avg_y": None, "avg_bbox_w": 0.0, "avg_bbox_h": 0.0,
                "hit_rate": 0.0,
            })
            if layout_pref == "auto":
                layout_mode = classify_layout(face_summary)
            else:
                layout_mode = layout_pref

            burned_path = None
            clean_path = None
            srt_path = None

            if layout_mode == "stacked":
                face_x = face_summary["avg_x"] if face_summary["avg_x"] is not None else 0.82
                face_y = face_summary["avg_y"] if face_summary["avg_y"] is not None else 0.85
                bbox_w = face_summary["avg_bbox_w"] or 0.15

                if mode in ("burned", "both"):
                    with tempfile.NamedTemporaryFile(
                        "w", suffix=".ass", delete=False, encoding="utf-8"
                    ) as f:
                        f.write(ctx.ass.render())
                        ass_path = Path(f.name)
                    try:
                        burned_path = base.with_suffix(".mp4")
                        _encode_stacked(video, clip["t_start"], duration, burned_path,
                                        face_x, face_y, bbox_w, subtitles_path=ass_path)
                    finally:
                        ass_path.unlink(missing_ok=True)

                if mode in ("clean", "both"):
                    if mode == "both":
                        clean_path = base.with_name(base.name + "_clean").with_suffix(".mp4")
                    else:
                        clean_path = base.with_suffix(".mp4")
                    _encode_stacked(video, clip["t_start"], duration, clean_path,
                                    face_x, face_y, bbox_w, subtitles_path=None)
                    srt_path = base.with_suffix(".srt")
                    srt_path.write_text(generate_srt(words, clip["t_start"]), encoding="utf-8")
            else:
                # tracking/static: use encode_clip with profile-based vertical-stripe crop.
                if mode in ("burned", "both"):
                    with tempfile.NamedTemporaryFile(
                        "w", suffix=".ass", delete=False, encoding="utf-8"
                    ) as f:
                        f.write(ctx.ass.render())
                        ass_path = Path(f.name)
                    try:
                        burned_path = base.with_suffix(".mp4")
                        encode_clip(
                            video, clip["t_start"], duration, burned_path, FINAL,
                            subtitles_path=ass_path,
                            extra_filters=ctx.extra_filters or None,
                        )
                    finally:
                        ass_path.unlink(missing_ok=True)

                if mode in ("clean", "both"):
                    if mode == "both":
                        clean_path = base.with_name(base.name + "_clean").with_suffix(".mp4")
                    else:
                        clean_path = base.with_suffix(".mp4")
                    # Clean output still gets non-caption effects (zoompan, overlays).
                    encode_clip(
                        video, clip["t_start"], duration, clean_path, FINAL,
                        extra_filters=ctx.extra_filters or None,
                    )
                    srt_path = base.with_suffix(".srt")
                    srt_path.write_text(generate_srt(words, clip["t_start"]), encoding="utf-8")

            manifest_clips.append({
                "filename": burned_path.name if burned_path else clean_path.name,
                "clean_filename": clean_path.name if (mode == "both" and clean_path) else None,
                "srt_filename": srt_path.name if srt_path else None,
                "title": clip["title"],
                "t_start_source": clip["t_start"],
                "t_end_source": clip["t_end"],
                "duration": duration,
                "caption_mode": mode,
                "caption_style": style,
                "layout": layout_mode,
                "effects_applied": applied,
                "score": clip.get("score", 0),
                "hook_quality": clip.get("hook_quality", 0),
                "reason": clip.get("reason", ""),
                "top_emotes": clip.get("top_emotes", []),
            })
        except Exception as exc:
            logger.warning(f"Skipping clip {clip.get('id', '?')}: {exc}")
            continue

    manifest = {
        "vod_id": work_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "clips": manifest_clips,
    }
    write_json(final_dir / "manifest.json", manifest)
    logger.info(f"Finalized {len(manifest_clips)} clips to {final_dir}")
    return final_dir / "manifest.json"
