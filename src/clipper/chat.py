"""Download Twitch VOD chat replay as JSONL via the chat-downloader package."""
import json
from pathlib import Path

from chat_downloader import ChatDownloader

from clipper.util.logging import get_logger

logger = get_logger(__name__)


def _normalize_message(raw: dict) -> dict:
    """Project chat-downloader's verbose dict into our lean schema."""
    return {
        "t": float(raw.get("time_in_seconds", 0.0)),
        "user": (raw.get("author") or {}).get("name", "") or "",
        "msg": raw.get("message", "") or "",
    }


def download_chat(url: str, work_dir: Path) -> Path:
    """Fetch chat replay; write JSONL to work_dir/chat.jsonl.

    Uses a `.complete` sentinel file to distinguish "successfully finished" from
    "started but errored / killed mid-run". A bare chat.jsonl with no sentinel
    is treated as incomplete and retried on the next call. The sentinel is
    written only after the iterator drains cleanly.

    Resilient to chat-downloader failures: catches exceptions, logs a warning,
    leaves the (possibly partial) jsonl on disk WITHOUT the sentinel — so a
    future re-run will retry. Downstream stages (chat_peaks, candidates, rank)
    gracefully handle empty chat — the pipeline still produces clips, just with
    less chat-informed ranking.

    Uses line-buffered writes so the file grows visibly during download instead
    of appearing empty until the buffer flushes.
    """
    out = work_dir / "chat.jsonl"
    sentinel = work_dir / "chat.jsonl.complete"
    if out.exists() and sentinel.exists():
        logger.info(f"Skipping chat download; {out} exists and is marked complete")
        return out
    if out.exists() and not sentinel.exists():
        logger.info(f"Found incomplete {out} from a previous run; retrying")
        out.unlink()

    count = 0
    completed = False
    try:
        cd = ChatDownloader()
        # buffering=1 -> line-buffered; each f.write(...) flushes immediately.
        with out.open("w", encoding="utf-8", buffering=1) as f:
            for raw in cd.get_chat(url):
                line = json.dumps(_normalize_message(raw), ensure_ascii=False)
                f.write(line + "\n")
                count += 1
                if count % 1000 == 0:
                    logger.info(f"  chat: {count} messages so far...")
        completed = True
    except Exception as exc:
        logger.warning(
            f"chat-downloader failed after {count} messages: {exc!r}. "
            f"Continuing with what we have; downstream stages handle empty chat. "
            f"Re-running the pipeline will retry chat."
        )
        if not out.exists():
            out.touch()

    if completed:
        sentinel.touch()
        logger.info(f"Wrote {count} chat messages to {out} (marked complete)")
    else:
        logger.info(f"Wrote {count} chat messages to {out} (NOT marked complete; will retry on re-run)")
    return out
