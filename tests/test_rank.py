import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clipper.rank import (
    OllamaRanker,
    RankedClip,
    _extract_json,
    rank_candidates,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_json_handles_clean_object():
    out = _extract_json('{"a": 1}')
    assert out == {"a": 1}


def test_extract_json_strips_markdown_fence():
    out = _extract_json('```json\n{"a": 1}\n```')
    assert out == {"a": 1}


def test_extract_json_strips_prose_preamble():
    out = _extract_json('Sure here you go: {"a": 1} hope this helps')
    assert out == {"a": 1}


def test_extract_json_raises_on_garbage():
    with pytest.raises(ValueError):
        _extract_json("not json at all")


def test_ollama_ranker_returns_ranked_clip(fixture_work_dir: Path):
    response = json.loads((FIXTURES / "ollama_response.json").read_text())
    candidate = {
        "id": "c001",
        "t_start": 5.0,
        "t_end": 15.0,
        "signals": ["audio", "chat"],
        "audio_intensity": 14.0,
        "chat_hype_score": 87.0,
        "msg_count": 142,
        "top_emotes": ["KEKW"],
    }
    transcript_words = [{"start": 5.0, "end": 5.3, "word": "holy"}]
    chat_window = [{"t": 5.5, "user": "x", "msg": "KEKW"}]

    ranker = OllamaRanker(model="llama3.1:8b", base_url="http://localhost:11434")
    fake_resp = MagicMock()
    fake_resp.json.return_value = response
    fake_resp.raise_for_status = MagicMock()

    with patch("clipper.rank.httpx.post", return_value=fake_resp) as post:
        rc = ranker.rank_one(candidate, transcript_words, chat_window)
    assert isinstance(rc, RankedClip)
    assert rc.id == "c001"
    assert rc.score == 87
    assert rc.title.startswith("HOLY")
    post.assert_called_once()


def test_rank_candidates_filters_by_min_score(fixture_work_dir: Path, monkeypatch):
    """End-to-end: feed candidates + transcript + chat through a mocked ranker; only score>=min wins."""
    candidates = [
        {"id": "c001", "t_start": 5.0, "t_end": 15.0, "signals": ["audio", "chat"],
         "audio_intensity": 14.0, "chat_hype_score": 87.0, "msg_count": 142, "top_emotes": []},
        {"id": "c002", "t_start": 20.0, "t_end": 35.0, "signals": ["chat"],
         "audio_intensity": 0.0, "chat_hype_score": 30.0, "msg_count": 20, "top_emotes": []},
    ]
    (fixture_work_dir / "candidates.json").write_text(json.dumps(candidates), encoding="utf-8")
    # Also make sure chat.jsonl exists since rank reads from it.
    (fixture_work_dir / "chat.jsonl").write_text("", encoding="utf-8")
    # Remove pre-seeded ranked.json so rank_candidates runs fresh.
    (fixture_work_dir / "ranked.json").unlink()

    class FakeRanker:
        def rank_one(self, cand, words, chat):
            return RankedClip(
                id=cand["id"],
                t_start_refined=cand["t_start"],
                t_end_refined=cand["t_end"],
                score=85 if cand["id"] == "c001" else 40,
                hook_quality=8,
                standalone=True,
                title=cand["id"].upper(),
                reason="mock",
                signals=cand.get("signals", []),
                audio_intensity=cand.get("audio_intensity", 0),
                chat_hype_score=cand.get("chat_hype_score", 0),
                msg_count=cand.get("msg_count", 0),
                top_emotes=cand.get("top_emotes", []),
            )

    out = rank_candidates(fixture_work_dir, FakeRanker(), min_score=60, max_clips=20)
    ranked = json.loads(out.read_text(encoding="utf-8"))
    assert len(ranked) == 1
    assert ranked[0]["id"] == "c001"


def test_anthropic_ranker_returns_ranked_clip(fixture_work_dir: Path):
    from clipper.rank import AnthropicRanker

    candidate = {
        "id": "c001",
        "t_start": 5.0,
        "t_end": 15.0,
        "signals": ["audio", "chat"],
        "audio_intensity": 14.0,
        "chat_hype_score": 87.0,
        "msg_count": 142,
        "top_emotes": ["KEKW"],
    }
    transcript_words = [{"start": 5.0, "end": 5.3, "word": "holy"}]
    chat_window = [{"t": 5.5, "user": "x", "msg": "KEKW"}]

    fake_message = MagicMock()
    fake_message.content = [
        MagicMock(text='{"score": 75, "t_start_refined": 5.0, "t_end_refined": 14.5, "hook_quality": 7, "standalone": true, "title": "TEST TITLE", "reason": "test"}')
    ]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message

    # Create a fake anthropic module and inject it into sys.modules
    fake_anthropic_module = MagicMock()
    fake_anthropic_module.Anthropic = MagicMock(return_value=fake_client)

    sys.modules["anthropic"] = fake_anthropic_module
    try:
        ranker = AnthropicRanker(model="claude-haiku-4-5-20251001", api_key="test")
        rc = ranker.rank_one(candidate, transcript_words, chat_window)
        assert rc.score == 75
        assert rc.title == "TEST TITLE"
    finally:
        if "anthropic" in sys.modules:
            del sys.modules["anthropic"]
