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

    Resilient to chat-downloader failures: catches exceptions, writes an empty
    chat.jsonl, and continues. Downstream stages (chat_peaks, candidates, rank)
    gracefully handle empty chat — the pipeline still produces clips, just with
    less chat-informed ranking.

    Uses line-buffered writes so the file grows visibly during download instead
    of appearing empty until the buffer flushes.
    """
    out = work_dir / "chat.jsonl"
    if out.exists():
        logger.info(f"Skipping chat download; {out} exists")
        return out
    count = 0
    try:
        cd = ChatDownloader()
        # buffering=1 → line-buffered; each `f.write(...)` flushes immediately.
        with out.open("w", encoding="utf-8", buffering=1) as f:
            for raw in cd.get_chat(url):
                line = json.dumps(_normalize_message(raw), ensure_ascii=False)
                f.write(line + "\n")
                count += 1
                if count % 1000 == 0:
                    logger.info(f"  chat: {count} messages so far...")
    except Exception as exc:
        logger.warning(
            f"chat-downloader failed after {count} messages: {exc!r}. "
            f"Continuing with what we have; downstream stages handle empty chat."
        )
        # Ensure the file exists (possibly empty) so downstream skip-if-exists
        # logic works on rerun without trying chat again.
        if not out.exists():
            out.touch()
    logger.info(f"Wrote {count} chat messages to {out}")
    return out
