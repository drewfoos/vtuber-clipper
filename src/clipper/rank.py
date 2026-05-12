"""Rank candidate clips via an LLM (Ollama default, Anthropic optional)."""
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import httpx

from clipper.util.json_io import read_json, read_jsonl, write_json
from clipper.util.logging import get_logger
from clipper.util.transcript import load_transcript, words_in_window

logger = get_logger(__name__)

PROMPT_TEMPLATE = """You are a viral short-form video editor. You're picking clips from a VTuber stream
to repost as TikTok/Shorts.

Below is a candidate moment. Decide:
1. Is this actually clip-worthy on its own, without the surrounding context? (standalone)
2. How strong is the first 3 seconds as a hook? (hook_quality 0-10)
3. Refine the start and end timestamps to land on clean sentence boundaries
   using the word-level transcript provided. Don't start mid-word or mid-thought.
4. Score overall clip quality 0-100.
5. Write a TikTok title (max 60 chars, no hashtags, no emojis, attention-grabbing).

Return JSON only, no preamble.

CANDIDATE:
{candidate_json}

TRANSCRIPT (word-level timestamps):
{transcript_window}

CHAT (last 30 messages in window):
{chat_window}

Output schema:
{{
  "score": int,
  "t_start_refined": float,
  "t_end_refined": float,
  "hook_quality": int,
  "standalone": bool,
  "title": str,
  "reason": str
}}
"""


@dataclass
class RankedClip:
    id: str
    t_start_refined: float
    t_end_refined: float
    score: int
    hook_quality: int
    standalone: bool
    title: str
    reason: str
    signals: list[str]
    audio_intensity: float
    chat_hype_score: float
    msg_count: int
    top_emotes: list[str]


class Ranker(Protocol):
    def rank_one(
        self,
        candidate: dict,
        transcript_words: list[dict],
        chat_window: list[dict],
    ) -> RankedClip: ...


def _extract_json(text: str) -> dict:
    """Extract a JSON object from LLM output. Tolerant of markdown fences and prose."""
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```\s*$", stripped, flags=re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    start = stripped.find("{")
    if start < 0:
        raise ValueError(f"no JSON object found in: {text[:200]!r}")
    depth = 0
    end = -1
    for i in range(start, len(stripped)):
        if stripped[i] == "{":
            depth += 1
        elif stripped[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        raise ValueError(f"unterminated JSON object in: {text[:200]!r}")
    return json.loads(stripped[start:end])


def _build_prompt(candidate: dict, transcript_words: list[dict], chat_window: list[dict]) -> str:
    chat_slice = chat_window[-30:]
    return PROMPT_TEMPLATE.format(
        candidate_json=json.dumps({k: v for k, v in candidate.items() if k != "id"}, indent=2),
        transcript_window=json.dumps(transcript_words, indent=2),
        chat_window=json.dumps([{"t": m["t"], "msg": m["msg"]} for m in chat_slice], indent=2),
    )


@dataclass
class OllamaRanker:
    model: str = "llama3.1:8b"
    base_url: str = "http://localhost:11434"
    timeout_s: float = 120.0

    def rank_one(self, candidate, transcript_words, chat_window) -> RankedClip:
        prompt = _build_prompt(candidate, transcript_words, chat_window)
        resp = httpx.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
                "keep_alive": "10m",
            },
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        body = resp.json()
        content = body.get("message", {}).get("content", "")
        parsed = _extract_json(content)
        return RankedClip(
            id=candidate["id"],
            t_start_refined=float(parsed.get("t_start_refined", candidate["t_start"])),
            t_end_refined=float(parsed.get("t_end_refined", candidate["t_end"])),
            score=int(parsed.get("score", 0)),
            hook_quality=int(parsed.get("hook_quality", 0)),
            standalone=bool(parsed.get("standalone", False)),
            title=str(parsed.get("title", ""))[:60],
            reason=str(parsed.get("reason", "")),
            signals=candidate.get("signals", []),
            audio_intensity=float(candidate.get("audio_intensity", 0.0)),
            chat_hype_score=float(candidate.get("chat_hype_score", 0.0)),
            msg_count=int(candidate.get("msg_count", 0)),
            top_emotes=list(candidate.get("top_emotes", [])),
        )


def _chat_in_window(chat_jsonl: Path, t_start: float, t_end: float) -> list[dict]:
    if not chat_jsonl.exists():
        return []
    return [m for m in read_jsonl(chat_jsonl) if t_start <= float(m.get("t", 0.0)) <= t_end]


def rank_candidates(
    work_dir: Path,
    ranker: "Ranker",
    *,
    min_score: int = 60,
    max_clips: int = 20,
    context_pad: float = 5.0,
) -> Path:
    """Rank every candidate via the LLM; filter score>=min and standalone; sort; write ranked.json."""
    out = work_dir / "ranked.json"
    if out.exists():
        logger.info(f"Skipping ranking; {out} exists")
        return out

    candidates = read_json(work_dir / "candidates.json")
    transcript = load_transcript(work_dir)
    chat_path = work_dir / "chat.jsonl"

    ranked: list[dict] = []
    for cand in candidates:
        words = words_in_window(transcript, cand["t_start"] - context_pad, cand["t_end"] + context_pad)
        chat_window = _chat_in_window(chat_path, cand["t_start"] - context_pad, cand["t_end"] + context_pad)
        try:
            rc = ranker.rank_one(cand, words, chat_window)
        except (ValueError, httpx.HTTPError) as exc:
            logger.warning(f"Ranker failed on {cand.get('id')}: {exc}")
            continue
        if rc.score < min_score:
            continue
        if not rc.standalone:
            continue
        ranked.append(asdict(rc))

    ranked.sort(key=lambda r: r["score"], reverse=True)
    ranked = ranked[:max_clips]
    write_json(out, ranked)
    logger.info(f"Wrote {len(ranked)} ranked clips to {out}")
    return out
