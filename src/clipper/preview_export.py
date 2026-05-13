from pathlib import Path

from clipper.util.ffmpeg import PREVIEW, encode_clip
from clipper.util.json_io import read_json
from clipper.util.logging import get_logger

logger = get_logger(__name__)


def preview_export(work_dir: Path) -> Path:
    """Generate 540x960 NVENC previews for every clip in ranked.json.

    Reads face_track.json if available and biases each preview's crop x-offset
    toward the avatar's average position. Otherwise center-crops (the legacy
    behavior). This keeps the avatar visible in the review-UI preview for
    corner-cam streams, even though the final encode may use a stacked layout.
    """
    previews_dir = work_dir / "previews"
    previews_dir.mkdir(exist_ok=True)
    video = work_dir / "video.mp4"

    face_track_data: dict = {}
    ft_path = work_dir / "face_track.json"
    if ft_path.exists():
        face_track_data = read_json(ft_path)

    for clip in read_json(work_dir / "ranked.json"):
        out_path = previews_dir / f"{clip['id']}.mp4"
        if out_path.exists():
            logger.info(f"skip {clip['id']} (exists)")
            continue
        duration = clip["t_end_refined"] - clip["t_start_refined"]

        # If MediaPipe found the face reliably, bias the crop toward it so the
        # avatar appears in the preview.
        summary = face_track_data.get(clip["id"], {}).get("summary", {})
        crop_x = None
        if summary.get("hit_rate", 0) >= 0.5 and summary.get("avg_x") is not None:
            crop_x = float(summary["avg_x"])

        encode_clip(
            video, clip["t_start_refined"], duration, out_path, PREVIEW,
            crop_x_norm=crop_x,
        )
    return previews_dir
