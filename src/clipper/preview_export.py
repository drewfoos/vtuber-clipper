from pathlib import Path

from clipper.util.ffmpeg import PREVIEW, encode_clip
from clipper.util.json_io import read_json
from clipper.util.logging import get_logger

logger = get_logger(__name__)


def preview_export(work_dir: Path) -> Path:
    """Generate 540x960 NVENC previews for every clip in ranked.json."""
    previews_dir = work_dir / "previews"
    previews_dir.mkdir(exist_ok=True)
    video = work_dir / "video.mp4"

    for clip in read_json(work_dir / "ranked.json"):
        out_path = previews_dir / f"{clip['id']}.mp4"
        if out_path.exists():
            logger.info(f"skip {clip['id']} (exists)")
            continue
        duration = clip["t_end_refined"] - clip["t_start_refined"]
        encode_clip(video, clip["t_start_refined"], duration, out_path, PREVIEW)
    return previews_dir
