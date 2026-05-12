"""Merge audio + chat peaks into candidate clip windows."""
from pathlib import Path

from clipper.util.json_io import read_json, write_json
from clipper.util.logging import get_logger

logger = get_logger(__name__)


def _overlaps(a_start: float, a_end: float, b_start: float, b_end: float, tol: float) -> bool:
    return a_start <= b_end + tol and a_end + tol >= b_start


def merge_peaks(
    audio_peaks: list[dict],
    chat_peaks: list[dict],
    *,
    overlap_tolerance: float,
    min_clip: float,
    max_clip: float,
    include_chat_only: bool,
) -> list[dict]:
    """Return ordered candidate windows from audio + chat peak lists.

    Algorithm:
    1. For each chat peak, find the first unmatched audio peak that overlaps it
       (within overlap_tolerance seconds).  If found, create a merged audio+chat
       candidate.  If not found, create a chat_only candidate (when
       include_chat_only=True).
    2. Unmatched audio peaks are appended as audio_only candidates
       unconditionally.  The spec is silent on audio-only peaks, but the test
       suite requires them to be included so that min/max clip clamping is
       exercised on audio-only inputs.
    3. All candidates are sorted by t_start, then adjacent overlapping windows
       are merged into single windows.
    4. Each window is padded/capped to satisfy min_clip / max_clip.
    5. Sequential IDs (c001, c002, …) are assigned.
    """
    cands: list[dict] = []
    audio_used = [False] * len(audio_peaks)

    # Pass 1: iterate chat peaks, match each to an audio peak when possible.
    for chat in chat_peaks:
        matched_audio_idx = None
        for ai, audio in enumerate(audio_peaks):
            if audio_used[ai]:
                continue
            if _overlaps(audio["t_start"], audio["t_end"],
                         chat["t_start"], chat["t_end"], overlap_tolerance):
                matched_audio_idx = ai
                break
        if matched_audio_idx is not None:
            audio = audio_peaks[matched_audio_idx]
            audio_used[matched_audio_idx] = True
            cands.append({
                "t_start": min(audio["t_start"], chat["t_start"]),
                "t_end": max(audio["t_end"], chat["t_end"]),
                "signals": ["audio", "chat"],
                "audio_intensity": audio["intensity"],
                "chat_hype_score": chat["hype_score"],
                "msg_count": chat.get("msg_count", 0),
                "top_emotes": chat.get("top_emotes", []),
            })
        elif include_chat_only:
            cands.append({
                "t_start": chat["t_start"],
                "t_end": chat["t_end"],
                "signals": ["chat_only"],
                "audio_intensity": 0.0,
                "chat_hype_score": chat["hype_score"],
                "msg_count": chat.get("msg_count", 0),
                "top_emotes": chat.get("top_emotes", []),
            })

    # Pass 2: include unmatched audio peaks as audio_only candidates.
    # The spec does not explicitly mention audio-only candidates, but the test
    # suite (test_min_clip_pads_short_windows, test_max_clip_caps_long_windows)
    # supplies audio-only inputs and asserts len(cands) == 1.  To make those
    # tests pass without contradicting any other test, we always include
    # unmatched audio peaks regardless of include_chat_only.
    for ai, audio in enumerate(audio_peaks):
        if not audio_used[ai]:
            cands.append({
                "t_start": audio["t_start"],
                "t_end": audio["t_end"],
                "signals": ["audio_only"],
                "audio_intensity": audio["intensity"],
                "chat_hype_score": 0.0,
                "msg_count": 0,
                "top_emotes": [],
            })

    cands.sort(key=lambda c: c["t_start"])

    # Merge overlapping / adjacent candidates.
    merged: list[dict] = []
    for c in cands:
        if merged and c["t_start"] <= merged[-1]["t_end"] + overlap_tolerance:
            merged[-1]["t_end"] = max(merged[-1]["t_end"], c["t_end"])
            merged[-1]["audio_intensity"] = max(merged[-1]["audio_intensity"], c["audio_intensity"])
            merged[-1]["chat_hype_score"] = max(merged[-1]["chat_hype_score"], c["chat_hype_score"])
            merged[-1]["msg_count"] = max(merged[-1]["msg_count"], c["msg_count"])
            sig = set(merged[-1]["signals"]) | set(c["signals"])
            if {"audio", "chat"}.issubset(sig):
                sig.discard("chat_only")
                sig.discard("audio_only")
            merged[-1]["signals"] = sorted(sig)
            seen: set[str] = set()
            both = list(merged[-1]["top_emotes"]) + list(c["top_emotes"])
            merged[-1]["top_emotes"] = [e for e in both if not (e in seen or seen.add(e))]  # type: ignore[func-returns-value]
        else:
            merged.append(c)

    # Apply min/max clip duration constraints.
    for c in merged:
        duration = c["t_end"] - c["t_start"]
        if duration < min_clip:
            pad = (min_clip - duration) / 2
            c["t_start"] = max(0.0, c["t_start"] - pad)
            c["t_end"] = c["t_start"] + min_clip
        elif duration > max_clip:
            center = (c["t_start"] + c["t_end"]) / 2
            c["t_start"] = center - max_clip / 2
            c["t_end"] = c["t_start"] + max_clip

    for idx, c in enumerate(merged, start=1):
        c["id"] = f"c{idx:03d}"

    return merged


def build_candidates(
    audio_peaks_path: Path,
    chat_peaks_path: Path,
    work_dir: Path,
    *,
    overlap_tolerance: float,
    min_clip: float,
    max_clip: float,
    include_chat_only: bool,
) -> Path:
    out = work_dir / "candidates.json"
    if out.exists():
        logger.info(f"Skipping candidate merge; {out} exists")
        return out
    audio = read_json(audio_peaks_path)
    chat = read_json(chat_peaks_path)
    cands = merge_peaks(
        audio, chat,
        overlap_tolerance=overlap_tolerance,
        min_clip=min_clip,
        max_clip=max_clip,
        include_chat_only=include_chat_only,
    )
    write_json(out, cands)
    logger.info(f"Wrote {len(cands)} candidates to {out}")
    return out
