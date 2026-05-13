"""Config loader: parses config.toml into typed pydantic models."""
import tomllib
from pathlib import Path

from pydantic import BaseModel

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"


class DownloadConfig(BaseModel):
    quality: str = "1080p60"


class TranscribeConfig(BaseModel):
    model: str = "distil-large-v3"
    device: str = "cuda"
    compute_type: str = "float16"


class AudioPeaksConfig(BaseModel):
    db_above_baseline: float = 6.0
    min_duration_seconds: float = 1.0
    merge_gap_seconds: float = 2.0


class ChatPeaksConfig(BaseModel):
    bucket_seconds: float = 2.0
    rolling_baseline_seconds: float = 300.0  # 5-min local "what's normal lately" window
    surge_multiplier: float = 3.0            # peak must be N x the rolling baseline
    absolute_floor: float = 3.0              # AND must clear this raw weight (dead-air guard)
    min_gap_seconds: float = 60.0
    target_count: int = 40                   # cap peaks at this; keep biggest surges
    hype_regex: str = r"\b(KEKW|LULW|PogChamp|POG|OMEGALUL|LMAO|LOL|W|WTF|HOLY|JESUS|NO WAY|LETS GO|LETSGO|GG)\b"


class CandidatesConfig(BaseModel):
    overlap_tolerance_seconds: float = 5.0
    min_clip_seconds: float = 25.0
    max_clip_seconds: float = 90.0
    include_chat_only: bool = True


class RankConfig(BaseModel):
    backend: str = "ollama"
    ollama_model: str = "llama3.1:8b"
    anthropic_model: str = "claude-haiku-4-5-20251001"
    max_clips: int = 20
    min_score: int = 60


class Config(BaseModel):
    download: DownloadConfig = DownloadConfig()
    transcribe: TranscribeConfig = TranscribeConfig()
    audio_peaks: AudioPeaksConfig = AudioPeaksConfig()
    chat_peaks: ChatPeaksConfig = ChatPeaksConfig()
    candidates: CandidatesConfig = CandidatesConfig()
    rank: RankConfig = RankConfig()


def load_config(path: Path | None = None) -> Config:
    """Load config.toml. Defaults to repo-root config.toml."""
    p = path if path is not None else DEFAULT_CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(f"config.toml not found at {p}")
    with p.open("rb") as f:
        raw = tomllib.load(f)
    return Config(**raw)
