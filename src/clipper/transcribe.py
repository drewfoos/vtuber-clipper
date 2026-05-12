"""Generate word-level timestamped transcript via faster-whisper."""
import gc
from pathlib import Path

from clipper.util.json_io import write_json
from clipper.util.logging import get_logger

logger = get_logger(__name__)


def transcribe(
    audio_path: Path,
    work_dir: Path,
    *,
    model_size: str = "distil-large-v3",
    device: str = "cuda",
    compute_type: str = "float16",
    language: str = "en",
) -> Path:
    """Word-level timestamped transcript. Explicitly releases VRAM on exit."""
    out = work_dir / "transcript.json"
    if out.exists():
        logger.info(f"Skipping transcription; {out} exists")
        return out

    from faster_whisper import WhisperModel

    logger.info(f"Loading {model_size} on {device}")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    try:
        segments_gen, info = model.transcribe(
            str(audio_path),
            language=language,
            word_timestamps=True,
            vad_filter=True,
            beam_size=5,
        )
        segments_out: list[dict] = []
        for seg in segments_gen:
            words_out = []
            for w in (seg.words or []):
                words_out.append({"start": float(w.start), "end": float(w.end), "word": w.word})
            segments_out.append({
                "start": float(seg.start),
                "end": float(seg.end),
                "text": seg.text,
                "words": words_out,
            })
        write_json(out, {"segments": segments_out})
        logger.info(f"Wrote {len(segments_out)} segments to {out}")
    finally:
        del model
        gc.collect()
    return out
