from pathlib import Path
from unittest.mock import patch

from clipper.chat import _normalize_message, download_chat


def test_normalize_message_extracts_fields():
    raw = {
        "time_in_seconds": 12.5,
        "author": {"name": "viewer123"},
        "message": "KEKW HOLY",
    }
    assert _normalize_message(raw) == {"t": 12.5, "user": "viewer123", "msg": "KEKW HOLY"}


def test_normalize_message_handles_missing_author():
    raw = {"time_in_seconds": 1.0, "message": "hi"}
    out = _normalize_message(raw)
    assert out["t"] == 1.0
    assert out["user"] == ""
    assert out["msg"] == "hi"


def test_download_chat_writes_jsonl(tmp_path: Path):
    fake_messages = [
        {"time_in_seconds": 1.0, "author": {"name": "a"}, "message": "hi"},
        {"time_in_seconds": 2.5, "author": {"name": "b"}, "message": "KEKW"},
    ]

    class FakeCD:
        def get_chat(self, url):
            return iter(fake_messages)

    with patch("clipper.chat.ChatDownloader", return_value=FakeCD()):
        out = download_chat("https://www.twitch.tv/videos/1", tmp_path)

    assert out.exists()
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    import json
    first = json.loads(lines[0])
    assert first == {"t": 1.0, "user": "a", "msg": "hi"}


def test_download_chat_skips_if_output_exists_and_complete(tmp_path: Path):
    """When both chat.jsonl and chat.jsonl.complete exist, skip the download."""
    out = tmp_path / "chat.jsonl"
    out.write_text("preexisting\n", encoding="utf-8")
    (tmp_path / "chat.jsonl.complete").touch()
    with patch("clipper.chat.ChatDownloader") as cd:
        result = download_chat("https://www.twitch.tv/videos/1", tmp_path)
    assert result == out
    cd.assert_not_called()


def test_download_chat_retries_if_jsonl_without_sentinel(tmp_path: Path):
    """Bare chat.jsonl (no sentinel) is treated as an incomplete prior run; retry."""
    out = tmp_path / "chat.jsonl"
    out.write_text("garbage from failed run\n", encoding="utf-8")
    # No sentinel file -> should retry.

    fake_messages = [{"time_in_seconds": 1.0, "author": {"name": "a"}, "message": "hi"}]

    class FakeCD:
        def get_chat(self, url):
            return iter(fake_messages)

    with patch("clipper.chat.ChatDownloader", return_value=FakeCD()):
        result = download_chat("https://www.twitch.tv/videos/1", tmp_path)

    # The stale content was replaced with the fresh fetch.
    lines = result.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    import json
    assert json.loads(lines[0])["user"] == "a"
    # Sentinel now exists.
    assert (tmp_path / "chat.jsonl.complete").exists()


def test_download_chat_does_not_write_sentinel_on_failure(tmp_path: Path):
    """If chat-downloader raises mid-stream, no sentinel is written so re-run retries."""
    class FlakyCD:
        def get_chat(self, url):
            yield {"time_in_seconds": 1.0, "author": {"name": "a"}, "message": "hi"}
            raise RuntimeError("simulated API failure")

    with patch("clipper.chat.ChatDownloader", return_value=FlakyCD()):
        result = download_chat("https://www.twitch.tv/videos/1", tmp_path)

    assert result.exists()                          # partial file written
    assert not (tmp_path / "chat.jsonl.complete").exists()   # but NOT marked complete
