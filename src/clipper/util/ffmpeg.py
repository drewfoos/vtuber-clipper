import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EncodeProfile:
    width: int
    height: int
    nvenc_preset: str    # "p5", "p7"
    cq: int              # 0-51 (23 ~ good, 28 ~ preview)
    audio_bitrate: str   # "96k", "128k"


PREVIEW = EncodeProfile(540, 960, "p7", 28, "96k")
FINAL = EncodeProfile(1080, 1920, "p5", 23, "128k")


def run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg with standard prefix. Raises CalledProcessError on non-zero exit."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *args]
    subprocess.run(cmd, check=True)


def _is_complex_filter(f: str) -> bool:
    """Return True if the filter string uses named pad syntax ([label]) requiring -filter_complex."""
    return "[" in f or "]" in f


def encode_clip(
    src: Path,
    t_start: float,
    duration: float,
    out: Path,
    profile: EncodeProfile,
    subtitles_path: Path | None = None,
    extra_filters: list[str] | None = None,
) -> None:
    """Encode a clip with crop+scale to profile dimensions, optional burned subtitles + extra filters.

    Uses -vf (simple filtergraph) when all filters are simple.  Switches to
    -filter_complex when any extra_filter uses named pad syntax (e.g. emoji_burst
    overlay chains), rewriting the pipeline so [in]/[out] labels are consistent.
    """
    crop_scale = (
        f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=increase,"
        f"crop={profile.width}:{profile.height}"
    )

    has_complex = extra_filters and any(_is_complex_filter(f) for f in extra_filters)

    if not has_complex:
        # Simple path: everything chained with commas, -vf.
        filters = [crop_scale]
        if extra_filters:
            filters.extend(extra_filters)
        if subtitles_path is not None:
            escaped = str(subtitles_path).replace("\\", "/").replace(":", "\\:")
            filters.append(f"subtitles='{escaped}'")
        vf = ",".join(filters)
        run_ffmpeg([
            "-ss", str(t_start),
            "-i", str(src),
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "h264_nvenc", "-preset", profile.nvenc_preset, "-cq:v", str(profile.cq),
            "-c:a", "aac", "-b:a", profile.audio_bitrate,
            "-movflags", "+faststart",
            str(out),
        ])
    else:
        # Complex path: build a -filter_complex graph.
        # Layout:
        #   [0:v] crop_scale, simple_frags [prescaled];
        #   <complex fragments (overlays) with [prescaled]/[chainN] labels>;
        #   [last] subtitles [vout]   (or just [last] → vout if no subtitles)
        #
        # Strategy: separate extra_filters into two buckets —
        #   complex_frags: contain [/] pad names (overlay chains from emoji_burst)
        #   simple_frags: plain video filters (zoompan, etc.) applied before overlays
        simple_frags = [f for f in (extra_filters or []) if not _is_complex_filter(f)]
        complex_frags = [f for f in (extra_filters or []) if _is_complex_filter(f)]

        # Build the filter_complex string.
        # Step 1: crop+scale + simple filters on the main input → [prescaled]
        pre_chain = crop_scale
        if simple_frags:
            pre_chain += "," + ",".join(simple_frags)
        fc_parts = [f"[0:v]{pre_chain}[prescaled]"]

        # Step 2: thread complex frags (overlays) one by one.
        # Each emoji_burst frag looks like:
        #   movie='path',scale=SIZE:SIZE[emN];[in][emN]overlay=x:y:enable='...'[out]
        # We replace the generic [in] and [out] labels with chain label pairs.
        prev_label = "prescaled"
        for i, frag in enumerate(complex_frags):
            next_label = f"chain{i}"
            # Replace [in] → [prev_label], [out] → [next_label].
            rewritten = frag.replace("[in]", f"[{prev_label}]").replace("[out]", f"[{next_label}]")
            fc_parts.append(rewritten)
            prev_label = next_label

        # Step 3: optional subtitles after the last overlay.
        if subtitles_path is not None:
            escaped = str(subtitles_path).replace("\\", "/").replace(":", "\\:")
            fc_parts.append(f"[{prev_label}]subtitles='{escaped}'[vout]")
            out_label = "vout"
        else:
            out_label = prev_label

        filter_complex = ";".join(fc_parts)
        run_ffmpeg([
            "-ss", str(t_start),
            "-i", str(src),
            "-t", str(duration),
            "-filter_complex", filter_complex,
            "-map", f"[{out_label}]",
            "-map", "0:a",
            "-c:v", "h264_nvenc", "-preset", profile.nvenc_preset, "-cq:v", str(profile.cq),
            "-c:a", "aac", "-b:a", profile.audio_bitrate,
            "-movflags", "+faststart",
            str(out),
        ])
