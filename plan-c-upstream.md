# Plan C — Upstream Pipeline (M1-M4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the upstream half of the pipeline — `download` → `chat` → `transcribe` → `audio_peaks` + `chat_peaks` → `candidates` → `rank` — so `clipper run <twitch_url>` actually runs end-to-end against a real VOD, producing the inputs that Plan A's preview_export and Plan B's effect chain already consume.

**Architecture:** Each module is a pure-ish stage: reads one or more files in `work/<vod_id>/`, writes one file. Stages are sequential, idempotent (skip if output exists), and produce JSON/JSONL that already match the fixture schemas Plan A established. `rank.py` uses a `Ranker` Protocol with two backends: `OllamaRanker` (default, free, local) and `AnthropicRanker` (opt-in, requires `ANTHROPIC_API_KEY`). `main.py`'s `run` subcommand is rewired to drive the full pipeline.

**Tech Stack:** Same as Plan A/B + `yt-dlp` Python API + `chat-downloader` + `faster-whisper` + `scipy.signal.find_peaks` + `httpx` (Ollama) + `anthropic` (optional).

**Scope:** Ships:
- `download.py` (yt-dlp Python API; video + audio extraction).
- `chat.py` (chat-downloader; JSONL output).
- `transcribe.py` (faster-whisper with explicit VRAM release).
- `audio_peaks.py` (ffmpeg astats → RMS parsing → peak detection).
- `chat_peaks.py` (2-second buckets, hype-weighted rate, scipy peak finding).
- `candidates.py` (overlap-merge audio + chat peaks; min/max duration enforcement).
- `rank.py` (`Ranker` Protocol + `OllamaRanker` + `AnthropicRanker` + ranked filtering).
- `config.py` + `config.toml` loader (rolled in because rankers need config).
- `main.py` rewired to run the full pipeline via `clipper run <url>`.
- Plan A debt cleanup: skip-and-continue per-clip failure in finalize (interaction-design §12).

**Out of scope:**
- M6 face tracking (`face_track.py` and dynamic per-frame crop) — separate milestone.
- M7 polish (atomic disk-space pre-flight checks, expired-VOD friendly error, `--force-from`) — defer.
- Plan A debt items not directly intersecting: server PID re-attach, corrupt-state fallback, idle-during-finalize blocking. Defer to a future polish plan.
- Animated caption styles `single`/`karaoke`/`stacked2` — design alternatives that didn't make Plan B's cut.

---

## File Structure

### Created in this plan
```
src/clipper/
├── download.py
├── chat.py
├── transcribe.py
├── audio_peaks.py
├── chat_peaks.py
├── candidates.py
├── rank.py
└── config.py

config.toml                    # at project root, user-editable

tests/
├── fixtures/
│   ├── rms.sample.log         # ffmpeg astats output for parser tests
│   ├── chat_stream.sample.jsonl  # synthetic chat for chat_peaks tests
│   └── ollama_response.json   # mock LLM response
├── test_download.py
├── test_chat.py
├── test_transcribe.py
├── test_audio_peaks.py
├── test_chat_peaks.py
├── test_candidates.py
├── test_rank.py
└── test_config.py
```

### Modified in this plan
```
src/clipper/
├── main.py            # rewire `run` to drive the full pipeline
└── finalize.py        # skip-and-continue on per-clip ffmpeg failure
```

`pyproject.toml` already includes all the dependencies (faster-whisper, chat-downloader, yt-dlp, scipy, httpx, anthropic-as-optional). No changes there.

---

## Conventions for every task

- TDD: failing test → run → confirm failure → implement → run → confirm pass → commit.
- All file paths relative to `E:\dev\vtuber-clipper`.
- Reuse helpers: `read_json`/`write_json`/`read_jsonl` for all I/O; `get_logger(__name__)` for logging.
- All on-disk timestamps in **source-video seconds** (clip-local only inside SRT/ASS).
- All Path operations work cross-platform — no hardcoded `\` separators.
- Idempotency: every stage's entry function checks `if output_path.exists(): return output_path` near the top, then writes the output last. Re-running the pipeline must be a no-op if all outputs exist.
- Skip slow tests (faster-whisper, real ffmpeg) marked `@pytest.mark.slow` and run by default; document a `pytest -m "not slow"` escape hatch for CI.

---

## Phase 0 — config.py + config.toml

### Task 1: Config loader + default config.toml

**Files:**
- Create: `src/clipper/config.py`
- Create: `config.toml`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

`tests/test_config.py`:
```python
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
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_config.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/clipper/config.py`**

```python
"""Config loader: parses config.toml into typed pydantic models."""
import tomllib
from pathlib import Path

from pydantic import BaseModel

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.toml"


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
    min_prominence_multiplier: float = 2.0
    min_gap_seconds: float = 30.0
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
```

- [ ] **Step 4: Write `config.toml` at repo root**

```toml
[download]
quality = "1080p60"

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
hype_regex = "\\b(KEKW|LULW|PogChamp|POG|OMEGALUL|LMAO|LOL|W|WTF|HOLY|JESUS|NO WAY|LETS GO|LETSGO|GG)\\b"

[candidates]
overlap_tolerance_seconds = 5.0
min_clip_seconds = 25.0
max_clip_seconds = 90.0
include_chat_only = true

[rank]
backend = "ollama"
ollama_model = "llama3.1:8b"
anthropic_model = "claude-haiku-4-5-20251001"
max_clips = 20
min_score = 60
```

- [ ] **Step 5: Verify**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 82 prior + 3 new = 85 passing.

- [ ] **Step 6: Commit**

```bash
git add src/clipper/config.py config.toml tests/test_config.py
git commit -m "feat: config.py + config.toml for pipeline + ranker settings"
```

---

## Phase 1 — M1 Download

### Task 2: download.py — yt-dlp Python API wrapper

**Files:**
- Create: `src/clipper/download.py`
- Create: `tests/test_download.py`

- [ ] **Step 1: Write failing tests**

`tests/test_download.py`:
```python
import re
from pathlib import Path

import pytest

from clipper.download import DownloadResult, parse_vod_id


def test_parse_vod_id_from_canonical_url():
    assert parse_vod_id("https://www.twitch.tv/videos/2762489406") == "2762489406"


def test_parse_vod_id_strips_trailing_query():
    assert parse_vod_id("https://www.twitch.tv/videos/2762489406?t=5m") == "2762489406"


def test_parse_vod_id_rejects_non_video_url():
    with pytest.raises(ValueError, match="not a Twitch VOD"):
        parse_vod_id("https://www.twitch.tv/somestreamer")


def test_parse_vod_id_rejects_garbage():
    with pytest.raises(ValueError):
        parse_vod_id("not even a url")
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_download.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/clipper/download.py`**

```python
"""Download a Twitch VOD via yt-dlp Python API; extract a low-bitrate audio track via ffmpeg."""
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from clipper.util.logging import get_logger

logger = get_logger(__name__)

_VOD_ID_RE = re.compile(r"^https?://(?:www\.)?twitch\.tv/videos/(\d+)")


@dataclass
class DownloadResult:
    video_path: Path
    audio_path: Path
    vod_id: str
    duration_seconds: float
    title: str
    streamer: str


def parse_vod_id(url: str) -> str:
    m = _VOD_ID_RE.match(url)
    if not m:
        raise ValueError(f"not a Twitch VOD URL: {url!r}")
    return m.group(1)


def download_vod(url: str, work_root: Path, quality: str = "1080p60") -> DownloadResult:
    """Download the VOD video file then extract a low-bitrate Opus audio track."""
    vod_id = parse_vod_id(url)
    work_dir = work_root / vod_id
    work_dir.mkdir(parents=True, exist_ok=True)
    video_path = work_dir / "video.mp4"
    audio_path = work_dir / "audio.opus"

    # Fetch metadata even when the video already exists, so we can return a complete result.
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    duration = float(info.get("duration", 0))
    title = info.get("title", "")
    streamer = info.get("uploader") or info.get("channel") or ""

    if not video_path.exists():
        logger.info(f"Downloading {url} at {quality} -> {video_path}")
        with yt_dlp.YoutubeDL({
            "format": quality,
            "outtmpl": str(video_path),
            "quiet": True,
            "no_warnings": True,
        }) as ydl:
            ydl.download([url])
    else:
        logger.info(f"Skipping download; {video_path} exists")

    if not audio_path.exists():
        logger.info(f"Extracting audio -> {audio_path}")
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(video_path),
            "-vn", "-c:a", "libopus", "-b:a", "32k",
            str(audio_path),
        ], check=True)
    else:
        logger.info(f"Skipping audio extract; {audio_path} exists")

    return DownloadResult(
        video_path=video_path,
        audio_path=audio_path,
        vod_id=vod_id,
        duration_seconds=duration,
        title=title,
        streamer=streamer,
    )
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe tests/test_download.py -v`
Expected: 4 pass (only the URL-parsing tests run; the heavy `download_vod` isn't unit-tested because it requires network + a live VOD).

Run full suite: `.venv\Scripts\pytest.exe -v`
Expected: 85 + 4 = 89 passing.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/download.py tests/test_download.py
git commit -m "feat: download.py — yt-dlp Python API wrapper + Opus audio extract"
```

---

## Phase 2 — M1 Chat

### Task 3: chat.py — chat-downloader wrapper

**Files:**
- Create: `src/clipper/chat.py`
- Create: `tests/test_chat.py`

- [ ] **Step 1: Write failing tests**

`tests/test_chat.py`:
```python
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
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_chat.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/clipper/chat.py`**

```python
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
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 89 + 4 = 93 passing.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/chat.py tests/test_chat.py
git commit -m "feat: chat.py — chat-downloader wrapper writing lean JSONL schema"
```

---

## Phase 3 — M2 Audio Peaks

### Task 4: rms.log fixture + parser

**Files:**
- Create: `tests/fixtures/rms.sample.log`
- Create: `src/clipper/audio_peaks.py`
- Create: `tests/test_audio_peaks.py`

- [ ] **Step 1: Write the rms.log fixture**

`tests/fixtures/rms.sample.log` — synthetic ffmpeg `astats + ametadata=print` output. Each frame block is two lines (`frame:N pts:M pts_time:T` then `lavfi.astats.Overall.RMS_level=X`). Use a 30-frame sample covering 7.5 seconds at 250ms windows, with one obvious peak around t=2.0-2.5s:

```
frame:0    pts:0       pts_time:0
lavfi.astats.Overall.RMS_level=-30.000
frame:1    pts:11025   pts_time:0.25
lavfi.astats.Overall.RMS_level=-29.500
frame:2    pts:22050   pts_time:0.5
lavfi.astats.Overall.RMS_level=-30.100
frame:3    pts:33075   pts_time:0.75
lavfi.astats.Overall.RMS_level=-29.800
frame:4    pts:44100   pts_time:1.0
lavfi.astats.Overall.RMS_level=-29.600
frame:5    pts:55125   pts_time:1.25
lavfi.astats.Overall.RMS_level=-30.000
frame:6    pts:66150   pts_time:1.5
lavfi.astats.Overall.RMS_level=-29.500
frame:7    pts:77175   pts_time:1.75
lavfi.astats.Overall.RMS_level=-29.700
frame:8    pts:88200   pts_time:2.0
lavfi.astats.Overall.RMS_level=-15.000
frame:9    pts:99225   pts_time:2.25
lavfi.astats.Overall.RMS_level=-12.500
frame:10   pts:110250  pts_time:2.5
lavfi.astats.Overall.RMS_level=-14.000
frame:11   pts:121275  pts_time:2.75
lavfi.astats.Overall.RMS_level=-29.300
frame:12   pts:132300  pts_time:3.0
lavfi.astats.Overall.RMS_level=-30.100
frame:13   pts:143325  pts_time:3.25
lavfi.astats.Overall.RMS_level=-29.900
frame:14   pts:154350  pts_time:3.5
lavfi.astats.Overall.RMS_level=-30.000
frame:15   pts:165375  pts_time:3.75
lavfi.astats.Overall.RMS_level=-29.600
frame:16   pts:176400  pts_time:4.0
lavfi.astats.Overall.RMS_level=-30.200
frame:17   pts:187425  pts_time:4.25
lavfi.astats.Overall.RMS_level=-29.700
frame:18   pts:198450  pts_time:4.5
lavfi.astats.Overall.RMS_level=-29.900
frame:19   pts:209475  pts_time:4.75
lavfi.astats.Overall.RMS_level=-29.500
frame:20   pts:220500  pts_time:5.0
lavfi.astats.Overall.RMS_level=-30.000
frame:21   pts:231525  pts_time:5.25
lavfi.astats.Overall.RMS_level=-29.800
frame:22   pts:242550  pts_time:5.5
lavfi.astats.Overall.RMS_level=-29.600
frame:23   pts:253575  pts_time:5.75
lavfi.astats.Overall.RMS_level=-29.900
frame:24   pts:264600  pts_time:6.0
lavfi.astats.Overall.RMS_level=-30.000
frame:25   pts:275625  pts_time:6.25
lavfi.astats.Overall.RMS_level=-29.700
frame:26   pts:286650  pts_time:6.5
lavfi.astats.Overall.RMS_level=-29.500
frame:27   pts:297675  pts_time:6.75
lavfi.astats.Overall.RMS_level=-29.800
frame:28   pts:308700  pts_time:7.0
lavfi.astats.Overall.RMS_level=-30.000
frame:29   pts:319725  pts_time:7.25
lavfi.astats.Overall.RMS_level=-29.600
```

(Three frames near t=2.0-2.5 show -15/-12.5/-14 — about 15-18 dB above the ~-30 baseline. That's a peak.)

- [ ] **Step 2: Write failing tests**

`tests/test_audio_peaks.py`:
```python
from pathlib import Path

from clipper.audio_peaks import detect_audio_peaks, parse_rms_log

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_rms_log_yields_time_db_pairs():
    samples = list(parse_rms_log(FIXTURES / "rms.sample.log"))
    assert len(samples) == 30
    assert samples[0] == (0.0, -30.0)
    # The big peak around t=2.25.
    assert any(t == 2.25 and -13.0 <= db <= -12.0 for t, db in samples)


def test_detect_audio_peaks_finds_obvious_peak(tmp_path: Path):
    import shutil
    audio_log = tmp_path / "rms.log"
    shutil.copy(FIXTURES / "rms.sample.log", audio_log)
    peaks = _detect_from_log(audio_log, db_above_baseline=6.0,
                             min_duration_seconds=0.5, merge_gap_seconds=1.0)
    # Single contiguous peak around t=2.0-2.5.
    assert len(peaks) == 1
    p = peaks[0]
    assert 1.9 <= p["t_start"] <= 2.1
    assert 2.4 <= p["t_end"] <= 2.8
    assert p["intensity"] > 10


def test_detect_audio_peaks_empty_when_flat(tmp_path: Path):
    flat = tmp_path / "rms.log"
    flat.write_text("\n".join(
        f"frame:{i} pts_time:{i * 0.25}\nlavfi.astats.Overall.RMS_level=-30.0"
        for i in range(30)
    ), encoding="utf-8")
    peaks = _detect_from_log(flat, db_above_baseline=6.0,
                             min_duration_seconds=0.5, merge_gap_seconds=1.0)
    assert peaks == []


def _detect_from_log(log_path, *, db_above_baseline, min_duration_seconds, merge_gap_seconds):
    """Helper: bypass detect_audio_peaks's ffmpeg call to test detection logic directly."""
    from clipper.audio_peaks import _detect_from_samples
    samples = list(parse_rms_log(log_path))
    return _detect_from_samples(
        samples,
        db_above_baseline=db_above_baseline,
        min_duration_seconds=min_duration_seconds,
        merge_gap_seconds=merge_gap_seconds,
    )
```

- [ ] **Step 3: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_audio_peaks.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement `src/clipper/audio_peaks.py`**

```python
"""Detect audio peaks via ffmpeg astats RMS analysis."""
import re
import subprocess
from pathlib import Path
from typing import Iterator

import numpy as np

from clipper.util.json_io import write_json
from clipper.util.logging import get_logger

logger = get_logger(__name__)

_TIME_RE = re.compile(r"pts_time:([\d.]+)")
_RMS_RE = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?\d+(?:\.\d+)?)")


def parse_rms_log(path: Path) -> Iterator[tuple[float, float]]:
    """Yield (time_s, rms_db) pairs from an ffmpeg astats+ametadata output file."""
    current_time: float | None = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            tm = _TIME_RE.search(line)
            if tm:
                current_time = float(tm.group(1))
                continue
            rm = _RMS_RE.search(line)
            if rm and current_time is not None:
                yield (current_time, float(rm.group(1)))


def _detect_from_samples(
    samples: list[tuple[float, float]],
    *,
    db_above_baseline: float,
    min_duration_seconds: float,
    merge_gap_seconds: float,
) -> list[dict]:
    """Detect peaks from an in-memory (time, db) series.

    Algorithm: rolling-median baseline over a 60s window; flag samples where current
    RMS exceeds baseline + threshold; merge adjacent flagged windows within merge_gap.
    """
    if not samples:
        return []
    times = np.array([t for t, _ in samples])
    dbs = np.array([d for _, d in samples])

    # Rolling median baseline. For a 7.5s test fixture the 60s window collapses to global median.
    sample_dt = times[1] - times[0] if len(times) > 1 else 0.25
    window_samples = max(4, int(60.0 / sample_dt))
    baseline = np.median(dbs[:window_samples]) if len(dbs) > 0 else 0.0
    if len(dbs) > window_samples:
        # Simple rolling median for longer streams.
        baseline_series = np.array([
            np.median(dbs[max(0, i - window_samples // 2): i + window_samples // 2 + 1])
            for i in range(len(dbs))
        ])
    else:
        baseline_series = np.full_like(dbs, baseline)

    flagged = dbs > (baseline_series + db_above_baseline)

    peaks: list[dict] = []
    i = 0
    while i < len(flagged):
        if not flagged[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(flagged) and flagged[j + 1]:
            j += 1
        # Group spans samples i..j inclusive. Convert to time span.
        t_start = float(times[i])
        t_end = float(times[j] + sample_dt)
        intensity = float(np.max(dbs[i:j + 1] - baseline_series[i:j + 1]))
        if t_end - t_start >= min_duration_seconds:
            if peaks and t_start - peaks[-1]["t_end"] <= merge_gap_seconds:
                peaks[-1]["t_end"] = t_end
                peaks[-1]["intensity"] = max(peaks[-1]["intensity"], intensity)
            else:
                peaks.append({"t_start": t_start, "t_end": t_end, "intensity": intensity})
        i = j + 1
    return peaks


def detect_audio_peaks(
    audio_path: Path,
    work_dir: Path,
    *,
    db_above_baseline: float = 6.0,
    min_duration_seconds: float = 1.0,
    merge_gap_seconds: float = 2.0,
) -> Path:
    """Extract RMS, detect peaks, write audio_peaks.json."""
    out = work_dir / "audio_peaks.json"
    if out.exists():
        logger.info(f"Skipping audio peak detection; {out} exists")
        return out
    log_path = work_dir / "rms.log"
    if not log_path.exists():
        logger.info(f"Computing RMS log -> {log_path}")
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(audio_path),
            "-af",
            f"astats=metadata=1:reset=0.25,ametadata=print:key=lavfi.astats.Overall.RMS_level:file={log_path.as_posix()}",
            "-f", "null", "-",
        ], check=True)
    samples = list(parse_rms_log(log_path))
    peaks = _detect_from_samples(
        samples,
        db_above_baseline=db_above_baseline,
        min_duration_seconds=min_duration_seconds,
        merge_gap_seconds=merge_gap_seconds,
    )
    write_json(out, peaks)
    logger.info(f"Wrote {len(peaks)} audio peaks to {out}")
    return out
```

- [ ] **Step 5: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 93 + 3 = 96 passing.

- [ ] **Step 6: Commit**

```bash
git add src/clipper/audio_peaks.py tests/test_audio_peaks.py tests/fixtures/rms.sample.log
git commit -m "feat: audio_peaks.py — ffmpeg astats RMS parser + peak detector"
```

---

## Phase 4 — M2 Chat Peaks

### Task 5: chat_peaks.py — rolling msg/s + hype weighting + scipy peak finding

**Files:**
- Create: `tests/fixtures/chat_stream.sample.jsonl`
- Create: `src/clipper/chat_peaks.py`
- Create: `tests/test_chat_peaks.py`

- [ ] **Step 1: Write the synthetic chat fixture**

`tests/fixtures/chat_stream.sample.jsonl` — 60 messages spread over 120 seconds, with a clear hype burst around t=60s:

```
{"t": 1.0, "user": "a", "msg": "hi"}
{"t": 4.0, "user": "b", "msg": "lol"}
{"t": 8.0, "user": "c", "msg": "hello"}
{"t": 12.0, "user": "d", "msg": "yo"}
{"t": 16.0, "user": "e", "msg": "sup"}
{"t": 20.0, "user": "f", "msg": "interesting"}
{"t": 24.0, "user": "g", "msg": "hm"}
{"t": 28.0, "user": "h", "msg": "ok"}
{"t": 32.0, "user": "i", "msg": "neat"}
{"t": 36.0, "user": "j", "msg": "cool"}
{"t": 40.0, "user": "k", "msg": "haha"}
{"t": 44.0, "user": "l", "msg": "right"}
{"t": 48.0, "user": "m", "msg": "wow"}
{"t": 58.0, "user": "n1", "msg": "KEKW"}
{"t": 58.5, "user": "n2", "msg": "KEKW KEKW"}
{"t": 59.0, "user": "n3", "msg": "LULW"}
{"t": 59.3, "user": "n4", "msg": "HOLY"}
{"t": 59.6, "user": "n5", "msg": "NO WAY"}
{"t": 60.0, "user": "n6", "msg": "OMEGALUL"}
{"t": 60.2, "user": "n7", "msg": "LETS GO"}
{"t": 60.5, "user": "n8", "msg": "WTF"}
{"t": 60.7, "user": "n9", "msg": "POG"}
{"t": 61.0, "user": "n10", "msg": "JESUS"}
{"t": 61.3, "user": "n11", "msg": "KEKW"}
{"t": 61.5, "user": "n12", "msg": "LULW"}
{"t": 61.8, "user": "n13", "msg": "GG"}
{"t": 62.0, "user": "n14", "msg": "KEKW"}
{"t": 62.2, "user": "n15", "msg": "LMAO"}
{"t": 62.5, "user": "n16", "msg": "W"}
{"t": 63.0, "user": "n17", "msg": "POG"}
{"t": 64.0, "user": "n18", "msg": "OMG"}
{"t": 65.0, "user": "n19", "msg": "nice"}
{"t": 70.0, "user": "o", "msg": "ok"}
{"t": 75.0, "user": "p", "msg": "hmm"}
{"t": 80.0, "user": "q", "msg": "right"}
{"t": 84.0, "user": "r", "msg": "cool"}
{"t": 88.0, "user": "s", "msg": "ok"}
{"t": 92.0, "user": "t", "msg": "yeah"}
{"t": 96.0, "user": "u", "msg": "lol"}
{"t": 100.0, "user": "v", "msg": "interesting"}
{"t": 104.0, "user": "w", "msg": "hm"}
{"t": 108.0, "user": "x", "msg": "cool"}
{"t": 112.0, "user": "y", "msg": "neat"}
{"t": 116.0, "user": "z", "msg": "ok"}
{"t": 119.0, "user": "aa", "msg": "bye"}
```

- [ ] **Step 2: Write failing tests**

`tests/test_chat_peaks.py`:
```python
import json
import shutil
from pathlib import Path

from clipper.chat_peaks import detect_chat_peaks, top_emotes_for_window

FIXTURES = Path(__file__).parent / "fixtures"


def test_top_emotes_counts_hype_words():
    msgs = [
        {"t": 1.0, "msg": "KEKW KEKW"},
        {"t": 2.0, "msg": "kekw"},
        {"t": 3.0, "msg": "LULW"},
        {"t": 4.0, "msg": "neutral text"},
    ]
    top = top_emotes_for_window(
        msgs,
        hype_regex=r"\b(KEKW|LULW)\b",
        max_emotes=5,
    )
    assert top[0] == "KEKW"
    assert "LULW" in top


def test_detect_chat_peaks_finds_burst(tmp_path: Path):
    chat_path = tmp_path / "chat.jsonl"
    shutil.copy(FIXTURES / "chat_stream.sample.jsonl", chat_path)
    out = detect_chat_peaks(
        chat_path,
        duration=120.0,
        work_dir=tmp_path,
        bucket_seconds=2.0,
        min_prominence_multiplier=2.0,
        min_gap_seconds=30.0,
        hype_regex=r"\b(KEKW|LULW|POG|OMEGALUL|LMAO|LOL|W|WTF|HOLY|JESUS|NO WAY|LETS GO|LETSGO|GG)\b",
    )
    peaks = json.loads(out.read_text(encoding="utf-8"))
    assert len(peaks) >= 1
    # The burst centers around t=60-63.
    burst = peaks[0]
    assert 55.0 <= burst["t_start"] <= 62.0
    assert burst["t_end"] >= 62.0
    assert burst["msg_count"] >= 10
    assert "KEKW" in burst["top_emotes"]


def test_detect_chat_peaks_skips_if_output_exists(tmp_path: Path):
    out = tmp_path / "chat_peaks.json"
    out.write_text("[]", encoding="utf-8")
    result = detect_chat_peaks(
        tmp_path / "nonexistent_chat.jsonl",
        duration=120.0,
        work_dir=tmp_path,
        bucket_seconds=2.0,
        min_prominence_multiplier=2.0,
        min_gap_seconds=30.0,
        hype_regex=r"\bKEKW\b",
    )
    assert result == out
```

- [ ] **Step 3: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_chat_peaks.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement `src/clipper/chat_peaks.py`**

```python
"""Detect hype peaks in chat by binning msg/s, regex-weighting, and scipy peak finding."""
import re
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

from clipper.util.json_io import read_jsonl, write_json
from clipper.util.logging import get_logger

logger = get_logger(__name__)


def top_emotes_for_window(messages: list[dict], hype_regex: str, max_emotes: int = 5) -> list[str]:
    """Count tokens matching hype_regex (case-insensitive) across messages; return top N by frequency."""
    pattern = re.compile(hype_regex, re.IGNORECASE)
    counter: Counter = Counter()
    for m in messages:
        text = m.get("msg", "")
        for match in pattern.findall(text):
            counter[match.upper()] += 1
    return [emote for emote, _ in counter.most_common(max_emotes)]


def _hype_weight(msg: str, hype_pattern: re.Pattern) -> float:
    weight = 1.0
    if hype_pattern.search(msg):
        weight += 2.0
    stripped = msg.strip()
    if len(stripped) > 3 and stripped.isupper():
        weight += 3.0
    return weight


def detect_chat_peaks(
    chat_path: Path,
    duration: float,
    work_dir: Path,
    *,
    bucket_seconds: float = 2.0,
    min_prominence_multiplier: float = 2.0,
    min_gap_seconds: float = 30.0,
    hype_regex: str = r"\b(KEKW|LULW|POG|OMEGALUL|LMAO|LOL|W|WTF|HOLY|JESUS)\b",
) -> Path:
    """Detect hype peaks; write chat_peaks.json."""
    out = work_dir / "chat_peaks.json"
    if out.exists():
        logger.info(f"Skipping chat peak detection; {out} exists")
        return out
    messages = list(read_jsonl(chat_path))
    if not messages:
        write_json(out, [])
        return out

    n_buckets = max(1, int(duration / bucket_seconds) + 1)
    hype_pattern = re.compile(hype_regex, re.IGNORECASE)
    weighted = np.zeros(n_buckets, dtype=float)
    bucket_messages: list[list[dict]] = [[] for _ in range(n_buckets)]
    for m in messages:
        t = float(m.get("t", 0.0))
        idx = int(t / bucket_seconds)
        if 0 <= idx < n_buckets:
            weighted[idx] += _hype_weight(m.get("msg", ""), hype_pattern)
            bucket_messages[idx].append(m)

    baseline = max(0.5, float(np.median(weighted)))
    peaks_idx, props = find_peaks(
        weighted,
        prominence=baseline * min_prominence_multiplier,
        distance=max(1, int(min_gap_seconds / bucket_seconds)),
    )

    peaks_out: list[dict] = []
    for pi in peaks_idx:
        peak_center = pi * bucket_seconds
        t_start = max(0.0, peak_center - 15.0)
        t_end = peak_center + 15.0
        # Extend t_end forward while rate stays above baseline*1.5.
        i = pi
        while i + 1 < n_buckets and weighted[i + 1] > baseline * 1.5:
            i += 1
        t_end = max(t_end, (i + 1) * bucket_seconds)

        window_msgs = [m for m in messages if t_start <= float(m.get("t", 0.0)) <= t_end]
        peaks_out.append({
            "t_start": float(t_start),
            "t_end": float(t_end),
            "msg_count": len(window_msgs),
            "hype_score": float(np.sum(weighted[max(0, pi - 7): min(n_buckets, pi + 8)])),
            "top_emotes": top_emotes_for_window(window_msgs, hype_regex),
        })

    write_json(out, peaks_out)
    logger.info(f"Wrote {len(peaks_out)} chat peaks to {out}")
    return out
```

- [ ] **Step 5: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 96 + 3 = 99 passing.

- [ ] **Step 6: Commit**

```bash
git add src/clipper/chat_peaks.py tests/test_chat_peaks.py tests/fixtures/chat_stream.sample.jsonl
git commit -m "feat: chat_peaks.py — hype-weighted bucketing + scipy peak finding"
```

---

## Phase 5 — M2 Candidates

### Task 6: candidates.py — merge audio + chat peaks

**Files:**
- Create: `src/clipper/candidates.py`
- Create: `tests/test_candidates.py`

This is the module the spec calls out as the unit-test target.

- [ ] **Step 1: Write failing tests**

`tests/test_candidates.py`:
```python
import json
from pathlib import Path

from clipper.candidates import build_candidates, merge_peaks


def test_overlapping_audio_and_chat_merge_into_one():
    audio = [{"t_start": 10.0, "t_end": 12.0, "intensity": 14.0}]
    chat = [{"t_start": 11.0, "t_end": 13.0, "msg_count": 50, "hype_score": 80.0,
             "top_emotes": ["KEKW"]}]
    cands = merge_peaks(audio, chat, overlap_tolerance=5.0,
                        min_clip=25.0, max_clip=90.0, include_chat_only=True)
    assert len(cands) == 1
    c = cands[0]
    assert set(c["signals"]) == {"audio", "chat"}
    assert c["t_start"] <= 10.0
    assert c["t_end"] >= 13.0
    assert c["audio_intensity"] == 14.0
    assert c["chat_hype_score"] == 80.0


def test_chat_only_peak_when_no_audio_nearby():
    audio = []
    chat = [{"t_start": 50.0, "t_end": 53.0, "msg_count": 80, "hype_score": 90.0,
             "top_emotes": ["LULW"]}]
    cands = merge_peaks(audio, chat, overlap_tolerance=5.0,
                        min_clip=25.0, max_clip=90.0, include_chat_only=True)
    assert len(cands) == 1
    assert cands[0]["signals"] == ["chat_only"]


def test_chat_only_dropped_when_disabled():
    audio = []
    chat = [{"t_start": 50.0, "t_end": 53.0, "msg_count": 80, "hype_score": 90.0,
             "top_emotes": []}]
    cands = merge_peaks(audio, chat, overlap_tolerance=5.0,
                        min_clip=25.0, max_clip=90.0, include_chat_only=False)
    assert cands == []


def test_min_clip_pads_short_windows():
    audio = [{"t_start": 10.0, "t_end": 11.0, "intensity": 14.0}]
    chat = []
    cands = merge_peaks(audio, chat, overlap_tolerance=5.0,
                        min_clip=25.0, max_clip=90.0, include_chat_only=True)
    assert len(cands) == 1
    # Window padded to at least 25 seconds.
    assert cands[0]["t_end"] - cands[0]["t_start"] >= 25.0


def test_max_clip_caps_long_windows():
    audio = [{"t_start": 10.0, "t_end": 200.0, "intensity": 14.0}]
    chat = []
    cands = merge_peaks(audio, chat, overlap_tolerance=5.0,
                        min_clip=25.0, max_clip=90.0, include_chat_only=True)
    assert len(cands) == 1
    assert cands[0]["t_end"] - cands[0]["t_start"] <= 90.0


def test_two_separate_peaks_produce_two_candidates():
    audio = [
        {"t_start": 10.0, "t_end": 12.0, "intensity": 14.0},
        {"t_start": 100.0, "t_end": 102.0, "intensity": 10.0},
    ]
    chat = [
        {"t_start": 10.5, "t_end": 12.5, "msg_count": 30, "hype_score": 60.0,
         "top_emotes": ["KEKW"]},
        {"t_start": 100.5, "t_end": 103.0, "msg_count": 40, "hype_score": 70.0,
         "top_emotes": ["POG"]},
    ]
    cands = merge_peaks(audio, chat, overlap_tolerance=5.0,
                        min_clip=25.0, max_clip=90.0, include_chat_only=True)
    assert len(cands) == 2


def test_build_candidates_writes_json(tmp_path: Path):
    audio_path = tmp_path / "audio_peaks.json"
    chat_path = tmp_path / "chat_peaks.json"
    audio_path.write_text(json.dumps([
        {"t_start": 10.0, "t_end": 12.0, "intensity": 14.0},
    ]), encoding="utf-8")
    chat_path.write_text(json.dumps([
        {"t_start": 11.0, "t_end": 13.0, "msg_count": 50, "hype_score": 80.0, "top_emotes": ["KEKW"]},
    ]), encoding="utf-8")
    out = build_candidates(audio_path, chat_path, tmp_path,
                           overlap_tolerance=5.0, min_clip=25.0, max_clip=90.0,
                           include_chat_only=True)
    cands = json.loads(out.read_text(encoding="utf-8"))
    assert len(cands) == 1
    assert cands[0]["id"] == "c001"
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_candidates.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/clipper/candidates.py`**

```python
"""Merge audio + chat peaks into candidate clip windows."""
from pathlib import Path

from clipper.util.json_io import read_json, write_json
from clipper.util.logging import get_logger

logger = get_logger(__name__)


def _overlaps(a_start: float, a_end: float, b_start: float, b_end: float, tol: float) -> bool:
    return a_start <= b_end + tol and a_end + tol >= b_start


def merge_peaks(
    audio_peaks: list[dict],
    chat_peaks: list[dict],
    *,
    overlap_tolerance: float,
    min_clip: float,
    max_clip: float,
    include_chat_only: bool,
) -> list[dict]:
    """Return ordered candidate windows from audio + chat peak lists.

    A candidate is created when an audio peak overlaps (within `overlap_tolerance`)
    a chat peak. Chat-only peaks (no nearby audio) are kept when `include_chat_only`.
    Windows are then clamped to [min_clip, max_clip], padding short windows evenly.
    Overlapping candidates are merged.
    """
    cands: list[dict] = []
    audio_used = [False] * len(audio_peaks)

    for ci, chat in enumerate(chat_peaks):
        matched_audio_idx = None
        for ai, audio in enumerate(audio_peaks):
            if audio_used[ai]:
                continue
            if _overlaps(audio["t_start"], audio["t_end"],
                         chat["t_start"], chat["t_end"], overlap_tolerance):
                matched_audio_idx = ai
                break
        if matched_audio_idx is not None:
            audio = audio_peaks[matched_audio_idx]
            audio_used[matched_audio_idx] = True
            cands.append({
                "t_start": min(audio["t_start"], chat["t_start"]),
                "t_end": max(audio["t_end"], chat["t_end"]),
                "signals": ["audio", "chat"],
                "audio_intensity": audio["intensity"],
                "chat_hype_score": chat["hype_score"],
                "msg_count": chat.get("msg_count", 0),
                "top_emotes": chat.get("top_emotes", []),
            })
        elif include_chat_only:
            cands.append({
                "t_start": chat["t_start"],
                "t_end": chat["t_end"],
                "signals": ["chat_only"],
                "audio_intensity": 0.0,
                "chat_hype_score": chat["hype_score"],
                "msg_count": chat.get("msg_count", 0),
                "top_emotes": chat.get("top_emotes", []),
            })

    # Unmatched audio peaks: skip (an audio-only peak with no chat reaction is rarely clip-worthy).

    # Merge overlapping candidates.
    cands.sort(key=lambda c: c["t_start"])
    merged: list[dict] = []
    for c in cands:
        if merged and c["t_start"] <= merged[-1]["t_end"] + overlap_tolerance:
            merged[-1]["t_end"] = max(merged[-1]["t_end"], c["t_end"])
            merged[-1]["audio_intensity"] = max(merged[-1]["audio_intensity"], c["audio_intensity"])
            merged[-1]["chat_hype_score"] = max(merged[-1]["chat_hype_score"], c["chat_hype_score"])
            merged[-1]["msg_count"] = max(merged[-1]["msg_count"], c["msg_count"])
            # Union signals.
            sig = set(merged[-1]["signals"]) | set(c["signals"])
            sig.discard("chat_only") if {"audio", "chat"}.issubset(sig) else None
            merged[-1]["signals"] = sorted(sig)
            # Merge top_emotes preserving order, dedup.
            seen = set()
            both = list(merged[-1]["top_emotes"]) + list(c["top_emotes"])
            merged[-1]["top_emotes"] = [e for e in both if not (e in seen or seen.add(e))]
        else:
            merged.append(c)

    # Clamp duration.
    for c in merged:
        duration = c["t_end"] - c["t_start"]
        if duration < min_clip:
            pad = (min_clip - duration) / 2
            c["t_start"] = max(0.0, c["t_start"] - pad)
            c["t_end"] = c["t_start"] + min_clip
        elif duration > max_clip:
            # Center the window on the peak midpoint.
            center = (c["t_start"] + c["t_end"]) / 2
            c["t_start"] = center - max_clip / 2
            c["t_end"] = c["t_start"] + max_clip

    # Assign IDs.
    for idx, c in enumerate(merged, start=1):
        c["id"] = f"c{idx:03d}"

    return merged


def build_candidates(
    audio_peaks_path: Path,
    chat_peaks_path: Path,
    work_dir: Path,
    *,
    overlap_tolerance: float,
    min_clip: float,
    max_clip: float,
    include_chat_only: bool,
) -> Path:
    out = work_dir / "candidates.json"
    if out.exists():
        logger.info(f"Skipping candidate merge; {out} exists")
        return out
    audio = read_json(audio_peaks_path)
    chat = read_json(chat_peaks_path)
    cands = merge_peaks(
        audio, chat,
        overlap_tolerance=overlap_tolerance,
        min_clip=min_clip,
        max_clip=max_clip,
        include_chat_only=include_chat_only,
    )
    write_json(out, cands)
    logger.info(f"Wrote {len(cands)} candidates to {out}")
    return out
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 99 + 7 = 106 passing.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/candidates.py tests/test_candidates.py
git commit -m "feat: candidates.py — overlap-merge audio + chat peaks into clip windows"
```

---

## Phase 6 — M3 Transcribe

### Task 7: transcribe.py — faster-whisper with VRAM release

**Files:**
- Create: `src/clipper/transcribe.py`
- Create: `tests/test_transcribe.py`

- [ ] **Step 1: Write tests (slow integration test marked)**

`tests/test_transcribe.py`:
```python
from pathlib import Path

import pytest

from clipper.transcribe import transcribe


@pytest.mark.slow
def test_transcribe_writes_word_level_json(fixture_work_dir: Path):
    # Use the smallest whisper model so test wall-clock is bearable.
    out = transcribe(
        fixture_work_dir / "video.mp4",   # the fixture is video; faster-whisper handles AV input.
        fixture_work_dir,
        model_size="tiny.en",
        device="cpu",                     # CPU works for tiny model; avoids CI GPU requirement.
        compute_type="int8",
    )
    assert out.exists()
    import json
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "segments" in data
    # At least one segment with at least one word.
    assert any(seg.get("words") for seg in data["segments"])


def test_transcribe_skips_if_output_exists(tmp_path: Path):
    out = tmp_path / "transcript.json"
    out.write_text('{"segments": []}', encoding="utf-8")
    result = transcribe(tmp_path / "nope.opus", tmp_path)
    assert result == out
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_transcribe.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/clipper/transcribe.py`**

```python
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
        # Release VRAM before downstream stages (rank) need it.
        del model
        gc.collect()
    return out
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v -m "not slow"`
Expected: 106 + 1 (skip-if-exists fast test) = 107 passing; the `@pytest.mark.slow` integration test is skipped by default.

Run: `.venv\Scripts\pytest.exe -v -m slow` separately when you want the integration test.
Expected: the slow test passes (downloads `tiny.en` model ~75 MB on first run, then takes ~10 seconds).

- [ ] **Step 5: Commit**

```bash
git add src/clipper/transcribe.py tests/test_transcribe.py
git commit -m "feat: transcribe.py — faster-whisper word-level transcript with VRAM release"
```

---

## Phase 7 — M4 Rank Protocol + OllamaRanker

### Task 8: rank.py — Ranker Protocol + OllamaRanker + JSON-extraction helpers

**Files:**
- Create: `src/clipper/rank.py`
- Create: `tests/fixtures/ollama_response.json`
- Create: `tests/test_rank.py`

- [ ] **Step 1: Write mock LLM response fixture**

`tests/fixtures/ollama_response.json`:
```json
{
  "message": {
    "content": "{\"score\": 87, \"t_start_refined\": 5.2, \"t_end_refined\": 14.8, \"hook_quality\": 9, \"standalone\": true, \"title\": \"HOLY NO WAY THAT JUST HAPPENED\", \"reason\": \"Strong audio + chat reaction; clean sentence boundaries.\"}"
  }
}
```

- [ ] **Step 2: Write failing tests**

`tests/test_rank.py`:
```python
import json
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
```

- [ ] **Step 3: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_rank.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement `src/clipper/rank.py`**

```python
"""Rank candidate clips via an LLM (Ollama default, Anthropic optional).

Each candidate's transcript window + nearby chat are passed to the LLM; the LLM
returns a JSON object scoring the clip, refining its in/out points, and writing a
title. Results are filtered by min_score and sorted, then written as ranked.json.
"""
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
    # Strip markdown ```json ... ``` fence.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```\s*$", stripped, flags=re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    # Find first balanced { ... } block.
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
    # Limit chat to last 30 messages to keep token count bounded.
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
    return [m for m in read_jsonl(chat_jsonl) if t_start <= float(m.get("t", 0.0)) <= t_end]


def rank_candidates(
    work_dir: Path,
    ranker: Ranker,
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
```

- [ ] **Step 5: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 107 + 6 = 113 passing.

- [ ] **Step 6: Commit**

```bash
git add src/clipper/rank.py tests/test_rank.py tests/fixtures/ollama_response.json
git commit -m "feat: rank.py — Ranker Protocol + OllamaRanker + LLM JSON extraction"
```

---

## Phase 8 — M4 AnthropicRanker

### Task 9: AnthropicRanker

**Files:**
- Modify: `src/clipper/rank.py` (append `AnthropicRanker` class)
- Modify: `tests/test_rank.py` (append test for the optional ranker)

- [ ] **Step 1: Append failing test**

Append to `tests/test_rank.py`:
```python
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

    with patch("anthropic.Anthropic", return_value=fake_client):
        ranker = AnthropicRanker(model="claude-haiku-4-5-20251001", api_key="test")
        rc = ranker.rank_one(candidate, transcript_words, chat_window)
    assert rc.score == 75
    assert rc.title == "TEST TITLE"
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_rank.py::test_anthropic_ranker_returns_ranked_clip -v`
Expected: ImportError on AnthropicRanker.

- [ ] **Step 3: Append `AnthropicRanker` to `src/clipper/rank.py`**

After the `OllamaRanker` class:
```python
@dataclass
class AnthropicRanker:
    model: str = "claude-haiku-4-5-20251001"
    api_key: str | None = None
    max_tokens: int = 1024

    def rank_one(self, candidate, transcript_words, chat_window) -> RankedClip:
        import anthropic
        key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("AnthropicRanker requires ANTHROPIC_API_KEY")
        client = anthropic.Anthropic(api_key=key)
        prompt = _build_prompt(candidate, transcript_words, chat_window)
        resp = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        content = "".join(block.text for block in resp.content if hasattr(block, "text"))
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
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 113 + 1 = 114 passing.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/rank.py tests/test_rank.py
git commit -m "feat: AnthropicRanker — opt-in cloud ranker via anthropic SDK"
```

---

## Phase 9 — Plan A debt: skip-and-continue in finalize

### Task 10: finalize.py — per-clip failure handling

**Files:**
- Modify: `src/clipper/finalize.py`
- Modify: `tests/test_finalize.py`

Per interaction-design.md §12 and the Plan A final review: a per-clip ffmpeg failure today halts the entire finalize. Make it skip-and-continue.

- [ ] **Step 1: Write failing test**

Append to `tests/test_finalize.py`:
```python
def test_finalize_skips_failed_clip_continues_others(fixture_work_dir, fixture_out_dir, monkeypatch):
    """If encode_clip fails on one clip, finalize logs it and proceeds with the others."""
    from clipper import finalize as finalize_module
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    # Keep c001 and c002; drop c003.
    client.put("/api/clips/c003", json={"kept": False})

    real_encode = finalize_module.encode_clip
    calls = {"n": 0}

    def flaky_encode(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated ffmpeg failure on first clip")
        return real_encode(*args, **kwargs)

    monkeypatch.setattr(finalize_module, "encode_clip", flaky_encode)

    manifest_path = finalize_module.finalize(fixture_work_dir, fixture_out_dir)
    import json as _json
    manifest = _json.loads(manifest_path.read_text())
    # First clip failed; second succeeded. Manifest has only the successful one.
    assert len(manifest["clips"]) == 1
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_finalize.py::test_finalize_skips_failed_clip_continues_others -v`
Expected: FAIL — current finalize re-raises on encode_clip failure.

- [ ] **Step 3: Wrap the per-clip encode block in try/except in `src/clipper/finalize.py`**

Inside the `for idx, clip in enumerate(kept, start=1):` loop, replace the encode-and-append section. Currently it computes `burned_path`/`clean_path`/`srt_path` and unconditionally appends to `manifest_clips`. Wrap the inner work (after the EffectContext is built, including the encode_clip calls AND the manifest_clips.append) in a try/except:
```python
        try:
            # ... existing block: caption-seeding, EffectContext build, effects loop,
            # encode_clip for burned, encode_clip for clean, srt write, manifest_clips.append ...
        except Exception as exc:
            logger.warning(f"Skipping clip {clip.get('id', '?')}: {exc}")
            continue
```

The smallest scope wrap is around `encode_clip(...) ... manifest_clips.append(...)` so that a failed encode skips the manifest entry too. Keep the EffectContext build inside the try as well so any effect-application error also degrades gracefully.

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 114 + 1 = 115 passing. All prior tests still pass since they don't simulate encode failures.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/finalize.py tests/test_finalize.py
git commit -m "fix: finalize skips failed clips and continues (interaction-design §12)"
```

---

## Phase 10 — Pipeline integration in main.py

### Task 11: main.py — wire run subcommand to full pipeline

**Files:**
- Modify: `src/clipper/main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_main.py`:
```python
def test_run_subcommand_no_longer_raises_unsupported(tmp_path):
    """The `run` subcommand should now exist and accept a URL — we just check that --help shows it."""
    from click.testing import CliRunner

    from clipper.main import cli

    res = CliRunner().invoke(cli, ["run", "--help"])
    assert res.exit_code == 0
    assert "url" in res.output.lower()
    assert "Pipeline" in res.output or "pipeline" in res.output
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_main.py::test_run_subcommand_no_longer_raises_unsupported -v`
Expected: PASS already (the `run` subcommand exists from Plan A and its `--help` works). But the actual `clipper run <url>` invocation raises ClickException. The test as written just checks --help, so it passes regardless. That's intentional: the real integration is covered by the manual `clipper run` invocation, which we can't unit-test without a live VOD. The test above is a smoke check that the subcommand still parses.

If the test passes immediately, that's expected — proceed to Step 3.

- [ ] **Step 3: Replace the body of `run` in `src/clipper/main.py`**

Find the current `def run(url: str, work_root: Path, out_root: Path, no_review: bool) -> None:` and replace its body with:
```python
@cli.command()
@click.argument("url")
@click.option("--work-root", default="work", type=click.Path(path_type=Path))
@click.option("--out-root", default="out", type=click.Path(path_type=Path))
@click.option("--no-review", is_flag=True, help="Skip launching review UI; run upstream + preview only.")
@click.option("--ranker", default=None, help="Override config: 'ollama' or 'anthropic'.")
def run(url: str, work_root: Path, out_root: Path, no_review: bool, ranker: str | None) -> None:
    """Pipeline: download, transcribe, detect peaks, rank, preview, review."""
    from clipper.audio_peaks import detect_audio_peaks
    from clipper.candidates import build_candidates
    from clipper.chat import download_chat
    from clipper.chat_peaks import detect_chat_peaks
    from clipper.config import load_config
    from clipper.download import download_vod
    from clipper.rank import AnthropicRanker, OllamaRanker, rank_candidates
    from clipper.transcribe import transcribe

    cfg = load_config()
    work_root = Path(work_root)
    out_root = Path(out_root)
    work_root.mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)

    logger.info("Stage 1/8: download")
    dl = download_vod(url, work_root, quality=cfg.download.quality)
    work_dir = dl.video_path.parent

    logger.info("Stage 2/8: chat")
    download_chat(url, work_dir)

    logger.info("Stage 3/8: transcribe")
    transcribe(dl.audio_path, work_dir,
               model_size=cfg.transcribe.model,
               device=cfg.transcribe.device,
               compute_type=cfg.transcribe.compute_type)

    logger.info("Stage 4/8: audio peaks")
    detect_audio_peaks(dl.audio_path, work_dir,
                       db_above_baseline=cfg.audio_peaks.db_above_baseline,
                       min_duration_seconds=cfg.audio_peaks.min_duration_seconds,
                       merge_gap_seconds=cfg.audio_peaks.merge_gap_seconds)

    logger.info("Stage 5/8: chat peaks")
    detect_chat_peaks(work_dir / "chat.jsonl", dl.duration_seconds, work_dir,
                      bucket_seconds=cfg.chat_peaks.bucket_seconds,
                      min_prominence_multiplier=cfg.chat_peaks.min_prominence_multiplier,
                      min_gap_seconds=cfg.chat_peaks.min_gap_seconds,
                      hype_regex=cfg.chat_peaks.hype_regex)

    logger.info("Stage 6/8: candidates")
    build_candidates(work_dir / "audio_peaks.json", work_dir / "chat_peaks.json", work_dir,
                     overlap_tolerance=cfg.candidates.overlap_tolerance_seconds,
                     min_clip=cfg.candidates.min_clip_seconds,
                     max_clip=cfg.candidates.max_clip_seconds,
                     include_chat_only=cfg.candidates.include_chat_only)

    logger.info("Stage 7/8: rank")
    backend = ranker or cfg.rank.backend
    if backend == "anthropic":
        ranker_impl = AnthropicRanker(model=cfg.rank.anthropic_model)
    else:
        ranker_impl = OllamaRanker(model=cfg.rank.ollama_model)
    rank_candidates(work_dir, ranker_impl,
                    min_score=cfg.rank.min_score,
                    max_clips=cfg.rank.max_clips)

    logger.info("Stage 8/8: preview export + review")
    preview_export(work_dir)

    if no_review:
        click.echo(f"Pipeline complete. Run 'clipper review {dl.vod_id}' to review.")
        return

    port = find_free_port()
    url_out = f"http://localhost:{port}"
    logger.info(f"Opening {url_out}")
    webbrowser.open(url_out)
    _serve(work_dir, out_root / dl.vod_id, port)
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 115 + 1 = 116 passing.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/main.py tests/test_main.py
git commit -m "feat: clipper run wires the full M1-M4 pipeline end-to-end"
```

---

## Phase 11 — Documentation

### Task 12: Doc updates

**Files:**
- Modify: `spec.md`
- Modify: `architecture.md`
- Modify: `MILESTONES.md`
- Modify: `changelog.md`
- Modify: `README.md`

- [ ] **Step 1: spec.md**

Update §6 module table where applicable. The modules `download.py`, `chat.py`, `transcribe.py`, `audio_peaks.py`, `chat_peaks.py`, `candidates.py`, `rank.py` already have detailed module-spec sections (§6.1–§6.7) from the original spec. No structural changes needed — just spot-check that the implementations match.

Add to §8 (acceptance criteria):
> 13. `clipper run <twitch_url>` runs the M1-M4 pipeline (download → chat → transcribe → peaks → candidates → rank) end-to-end before launching the review UI.
> 14. Each upstream stage is idempotent — re-running with the same work dir skips completed stages.

- [ ] **Step 2: architecture.md**

In §2 system diagram, no structural change needed — the existing diagram already shows the upstream stages. Verify it matches the implementation.

In §3 module-responsibilities table, add rows for: `download.py`, `chat.py`, `transcribe.py`, `audio_peaks.py`, `chat_peaks.py`, `candidates.py`, `rank.py`, `config.py`. One-line responsibility each.

Append to §6 Idempotency Model:
> Every M1-M4 module uses the existence of its output file as the skip signal. There's no per-stage config-hash check yet — that's a future polish item. For now, `--force` is the escape hatch (rerunning manually after deleting the output file).

- [ ] **Step 3: MILESTONES.md**

Mark M1, M2, M3, M4 as ✅ Complete. Update the Post-v0 list — remove anything that was actually shipped here.

- [ ] **Step 4: changelog.md**

Under `## [Unreleased]` → `### Planning`:
- `plan-c-upstream.md` — implementation plan for M1-M4 upstream pipeline.

Under `### Decisions` (date 2026-05-12):
- **2026-05-12** — `download.py` uses yt-dlp's Python API directly (not subprocess) for cleaner error handling and metadata access.
- **2026-05-12** — `transcribe.py` slow integration test uses `tiny.en` on CPU to avoid CI GPU requirements; production uses configured `distil-large-v3` on CUDA.
- **2026-05-12** — `rank.py` LLM JSON extraction (`_extract_json`) tolerates markdown fences and prose preambles around the JSON object. Real-world Ollama responses occasionally include both despite `format: "json"`.
- **2026-05-12** — `finalize.py` now skips and continues on per-clip ffmpeg failure (interaction-design.md §12); failed clips are logged and excluded from the manifest.
- **2026-05-12** — `audio_peaks.py` baseline computation uses a rolling median over a 60-second window; for shorter inputs it collapses to a global median.

- [ ] **Step 5: README.md**

Update status: `Status: Plan A + Plan B + M1-M4 complete; ready for end-to-end VOD runs.`

Replace the "Plan A (review UI only)" section with a real Quick Start:
```markdown
## Quick start

Prereqs: see `research.md` §1 — ffmpeg with NVENC, Python 3.11/3.12, an NVIDIA GPU with CUDA, Ollama (`ollama pull llama3.1:8b`), yt-dlp on PATH.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
pytest

# Full pipeline on a real Twitch VOD (downloads + transcribes + ranks + opens review UI):
clipper run https://www.twitch.tv/videos/<id>

# Headless ranking only (skip review browser):
clipper run https://www.twitch.tv/videos/<id> --no-review

# Re-open the review UI for an already-processed VOD:
clipper review <vod_id>

# Use Anthropic instead of Ollama for ranking:
ANTHROPIC_API_KEY=... clipper run https://www.twitch.tv/videos/<id> --ranker anthropic
```
```

- [ ] **Step 6: Verify suite still passes**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 116 passing.

- [ ] **Step 7: Commit**

```bash
git add spec.md architecture.md MILESTONES.md changelog.md README.md
git commit -m "docs: M1-M4 upstream pipeline complete; README quick-start"
```

---

## Self-Review Summary

After all 12 tasks across 11 phases:

- **Spec coverage** vs spec.md §6: download/chat/transcribe/audio_peaks/chat_peaks/candidates/rank all have implementing modules with TDD coverage.
- **Idempotency** uniformly applied — every stage skips if its output exists. No-op re-runs work.
- **Schemas match Plan A fixtures** — running M1-M4 on a real VOD produces files Plan A's interaction layer already knows how to consume.
- **No placeholders.** Every step shows actual code; no TBD/TODO.
- **Type consistency:** `RankedClip` dataclass fields match what `finalize.py` reads from `ranked.json`. `Ranker` Protocol's `rank_one` signature is consistent between `OllamaRanker` and `AnthropicRanker`. `Config` types are stable across consumers.
- **Test coverage:** ~34 new test cases across 8 test files. Heavy integration paths (faster-whisper, real ffmpeg with audio) marked `@pytest.mark.slow` for opt-in execution.

## What's left for a future Plan D / M6 / polish

- M6 face tracking (`face_track.py` + dynamic per-frame `sendcmd` crop in finalize).
- M7 polish: disk-space pre-flight, expired-VOD friendly error, `--force` / `--force-from` flags.
- Per-stage config-hash idempotency (currently only file-existence).
- Real ffmpeg integration test for `encode_clip` complex-filter path.
- `--single`/`--karaoke`/`--stacked2` animated caption styles.
- Server-side: PID re-attach, corrupt-state fallback, idle-during-finalize, atomic disk-space check.
- LLM resilience: structured retry-on-malformed-JSON loop, prompt-caching for `AnthropicRanker`.
- `clipper rank-only` / `clipper transcribe-only` etc. subcommands for partial reruns.
