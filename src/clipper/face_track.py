"""Per-clip face detection via MediaPipe."""
from pathlib import Path

import cv2
import numpy as np

from clipper.util.json_io import read_json, write_json
from clipper.util.logging import get_logger

logger = get_logger(__name__)


def _smooth_x(xs: list[float], *, fps: int, window_seconds: float = 3.0) -> list[float]:
    """3-second moving-average smoothing on a per-sample x series."""
    n = len(xs)
    if n == 0:
        return []
    half_window = max(1, int(fps * window_seconds / 2))
    out: list[float] = []
    for i in range(n):
        lo = max(0, i - half_window)
        hi = min(n, i + half_window + 1)
        out.append(float(np.mean(xs[lo:hi])))
    return out


def _summarize_track(track: list[dict]) -> dict:
    """Compute per-clip averages and hit rate from a track list."""
    hits = [t for t in track if t.get("x") is not None]
    hit_rate = len(hits) / len(track) if track else 0.0
    if not hits:
        return {"avg_x": None, "avg_y": None, "avg_bbox_w": 0.0, "avg_bbox_h": 0.0,
                "hit_rate": 0.0}
    return {
        "avg_x": float(np.mean([t["x"] for t in hits])),
        "avg_y": float(np.mean([t["y"] for t in hits])),
        "avg_bbox_w": float(np.mean([t["bbox_w"] for t in hits])),
        "avg_bbox_h": float(np.mean([t["bbox_h"] for t in hits])),
        "hit_rate": hit_rate,
    }


def track_face(
    video_path: Path,
    work_dir: Path,
    ranked_path: Path,
    *,
    fps: int = 2,
    min_confidence: float = 0.3,
) -> Path:
    """For each ranked clip, sample frames at `fps` and record MediaPipe face detection."""
    out = work_dir / "face_track.json"
    if out.exists():
        logger.info(f"Skipping face track; {out} exists")
        return out

    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    model_path = Path(__file__).resolve().parent / "assets" / "models" / "blaze_face_short_range.tflite"
    if not model_path.exists():
        raise FileNotFoundError(f"BlazeFace model missing: {model_path}")

    ranked = read_json(ranked_path)
    base_options = mp_python.BaseOptions(model_asset_path=str(model_path))
    options = vision.FaceDetectorOptions(
        base_options=base_options,
        min_detection_confidence=min_confidence,
    )

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open {video_path}")
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    result: dict[str, dict] = {}
    try:
        with vision.FaceDetector.create_from_options(options) as detector:
            for clip in ranked:
                cid = clip["id"]
                t_start = float(clip["t_start_refined"])
                t_end = float(clip["t_end_refined"])
                sample_interval = 1.0 / fps
                track: list[dict] = []
                t_local = 0.0
                while t_start + t_local < t_end:
                    cap.set(cv2.CAP_PROP_POS_MSEC, (t_start + t_local) * 1000.0)
                    ok, frame = cap.read()
                    if not ok:
                        break
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    detect_result = detector.detect(mp_image)
                    if detect_result.detections:
                        det = detect_result.detections[0]
                        bbox = det.bounding_box  # PIXEL coords now
                        # Normalize to [0, 1] like the legacy API did.
                        track.append({
                            "t": round(t_local, 3),
                            "x": float((bbox.origin_x + bbox.width / 2) / frame_w),
                            "y": float((bbox.origin_y + bbox.height / 2) / frame_h),
                            "bbox_w": float(bbox.width / frame_w),
                            "bbox_h": float(bbox.height / frame_h),
                        })
                    else:
                        track.append({
                            "t": round(t_local, 3),
                            "x": None, "y": None, "bbox_w": None, "bbox_h": None,
                        })
                    t_local += sample_interval
                result[cid] = {
                    "fps_sampled": fps,
                    "track": track,
                    "summary": _summarize_track(track),
                }
                logger.info(f"face_track {cid}: hit_rate={result[cid]['summary']['hit_rate']:.0%}")
    finally:
        cap.release()

    write_json(out, result)
    logger.info(f"Wrote face_track for {len(result)} clips to {out}")
    return out
