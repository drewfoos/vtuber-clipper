from pathlib import Path

import pytest

from clipper.config import Config, load_config


def test_load_config_from_repo_default():
    cfg = load_config()
    assert cfg.rank.backend in ("ollama", "anthropic")
    assert cfg.rank.max_clips > 0
    assert cfg.transcribe.model
    assert cfg.audio_peaks.db_above_baseline > 0


def test_load_config_from_custom_path(tmp_path: Path):
    p = tmp_path / "custom.toml"
    p.write_text(
        """
[rank]
backend = "anthropic"
max_clips = 5
ollama_model = "llama3.1:8b"
anthropic_model = "claude-haiku-4-5-20251001"
min_score = 70

[transcribe]
model = "distil-large-v3"
device = "cuda"
compute_type = "float16"

[audio_peaks]
db_above_baseline = 6.0
min_duration_seconds = 1.0
merge_gap_seconds = 2.0

[chat_peaks]
bucket_seconds = 2.0
min_prominence_multiplier = 2.0
min_gap_seconds = 30.0
hype_regex = "\\\\bGG\\\\b"

[candidates]
overlap_tolerance_seconds = 5.0
min_clip_seconds = 25.0
max_clip_seconds = 90.0
include_chat_only = true

[download]
quality = "1080p60"
""",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.rank.backend == "anthropic"
    assert cfg.rank.max_clips == 5
    assert cfg.rank.min_score == 70


def test_missing_config_raises_clear_error(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="config.toml"):
        load_config(tmp_path / "nope.toml")
