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

    ranked = read_json(ranked_path)
    detector = mp.solutions.face_detection.FaceDetection(
        model_selection=0, min_detection_confidence=min_confidence
    )

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open {video_path}")

    result: dict[str, dict] = {}
    try:
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
                results = detector.process(rgb)
                if results.detections:
                    det = results.detections[0]
                    bbox = det.location_data.relative_bounding_box
                    track.append({
                        "t": round(t_local, 3),
                        "x": float(bbox.xmin + bbox.width / 2),
                        "y": float(bbox.ymin + bbox.height / 2),
                        "bbox_w": float(bbox.width),
                        "bbox_h": float(bbox.height),
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
        detector.close()

    write_json(out, result)
    logger.info(f"Wrote face_track for {len(result)} clips to {out}")
    return out
