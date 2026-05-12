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


def test_download_chat_skips_if_output_exists(tmp_path: Path):
    out = tmp_path / "chat.jsonl"
    out.write_text("preexisting\n", encoding="utf-8")
    with patch("clipper.chat.ChatDownloader") as cd:
        result = download_chat("https://www.twitch.tv/videos/1", tmp_path)
    assert result == out
    cd.assert_not_called()
