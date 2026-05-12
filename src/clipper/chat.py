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
    """Fetch chat replay; write JSONL to work_dir/chat.jsonl."""
    out = work_dir / "chat.jsonl"
    if out.exists():
        logger.info(f"Skipping chat download; {out} exists")
        return out
    cd = ChatDownloader()
    count = 0
    with out.open("w", encoding="utf-8") as f:
        for raw in cd.get_chat(url):
            line = json.dumps(_normalize_message(raw), ensure_ascii=False)
            f.write(line + "\n")
            count += 1
    logger.info(f"Wrote {count} chat messages to {out}")
    return out
