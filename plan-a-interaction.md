# Plan A — Core Review Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the interaction layer specified in `interaction-design.md` — fast preview encoder, FastAPI review server, two-pane web UI, and basic finalize stage with plain (non-animated) burned captions. Result: a user can run a VOD through, review in browser, get final captioned clips out.

**Architecture:** Pipeline ends with `preview_export` (fast 540×960 MP4s). `web.py` launches a FastAPI + uvicorn server bound to localhost; browser auto-opens. User edits clips in a two-pane UI; edits persist to `review_state.json` via PUT. Clicking Finalize calls `finalize.py` which re-encodes only kept clips at 1080×1920 with simple SRT-style burned captions (animated captions and effects come in Plan B).

**Tech Stack:** Python 3.11/3.12 · FastAPI · uvicorn · pydantic · click · rich · ffmpeg (NVENC) · vanilla HTML/CSS/JS · pytest.

**Scope:** This plan covers `preview_export.py`, `web.py`, `finalize.py`, `captions.py` (plain SRT-style only — animated styles defer to Plan B), `web/` frontend, CLI rewires, test fixtures. Upstream pipeline modules (`download`, `chat`, `transcribe`, peaks, candidates, `rank`) are **out of scope** and need to be built separately (MILESTONES.md M1-M4) or stubbed manually. This plan includes fixtures so the interaction layer can be developed and tested without the upstream.

---

## Reusable Code Principles

The pipeline has overlapping concerns: `preview_export` and `finalize` both invoke ffmpeg with very similar arg lists; multiple places window the transcript by time; every module reads/writes JSON. Plan B will add four motion-effect modules that each generate ASS layers.

**Rule:** anything that would be copy-pasted between two modules belongs in `util/`. Anything used twice is extracted.

Foundational helpers live in `src/clipper/util/`:
- `json_io.py` — `read_json` / `write_json` / `read_jsonl`. Single source for file-touching.
- `ffmpeg.py` — `run_ffmpeg(args)`, an `EncodeProfile` dataclass with `PREVIEW` and `FINAL` constants, and `encode_clip(src, t_start, duration, out, profile, subtitles_path=None, extra_filters=None)`. One canonical encode invocation; preview and finalize differ only by profile and optional filters.
- `transcript.py` — `load_transcript(work_dir)`, `words_in_window(transcript, t_start, t_end)`. Used by `web.py`'s transcript endpoint, by `finalize.py`, and by every Plan B effect.
- `captions.py` exposes `AssBuilder` — a class that accumulates styles + dialogue lines and renders to ASS text. `generate_basic_ass()` is a thin wrapper around it. Plan B effects that emit ASS layers (emoji_burst, hook_card) construct their own `AssBuilder` or accept one to compose into.

If you find yourself writing the same 5-line block twice, stop and extract it before continuing.

---

## File Structure

### Created in this plan
```
src/clipper/
├── __init__.py
├── main.py                    # CLI: run, review, finalize subcommands
├── preview_export.py          # fast 540×960 NVENC previews
├── web.py                     # FastAPI app, endpoints, lifecycle
├── finalize.py                # full-quality re-encode of kept clips
├── captions.py                # SRT and basic ASS generation
├── effects/
│   ├── __init__.py
│   └── base.py                # FinalizeEffect Protocol (no effects yet — Plan B)
├── util/
│   ├── __init__.py
│   ├── timing.py              # seconds <-> HH:MM:SS.mmm helpers
│   ├── logging.py             # rich logger factory
│   ├── slug.py                # filename slugify helper
│   ├── ports.py               # free-port discovery
│   ├── range_response.py      # HTTP Range support for FastAPI
│   ├── json_io.py             # read_json / write_json / read_jsonl
│   ├── ffmpeg.py              # run_ffmpeg + EncodeProfile + encode_clip
│   └── transcript.py          # load_transcript + words_in_window
└── web/
    ├── index.html
    ├── app.css
    └── app.js

tests/
├── conftest.py                # shared fixtures
├── fixtures/
│   ├── make_fixture_video.py  # generates a 60s test video
│   ├── ranked.sample.json
│   ├── transcript.sample.json
│   └── face_track.sample.json
├── test_preview_export.py
├── test_web_endpoints.py
├── test_review_state.py
├── test_finalize.py
├── test_captions.py
├── test_range_response.py
└── test_slug.py

pyproject.toml
.gitignore
README.md (stub)
```

### Modified in this plan
None — this is greenfield within `src/clipper/`.

---

## Conventions for every task

- TDD: write the test first, run it to confirm it fails for the right reason, implement, re-run to confirm pass, commit.
- All file paths absolute on Windows: `E:\dev\vtuber-clipper\...`. Tasks below show paths relative to the project root for brevity.
- All commits use a brief conventional-style message; the actual `git commit` command is shown in each commit step.
- All test commands run from the project root with the venv activated.
- Frontend code: use `textContent` / DOM construction, never `innerHTML` with values from `/api/clips` (titles flow from LLM output and shouldn't be treated as trusted markup).

---

## Phase 0 — Project Skeleton

### Task 1: Initialize git repo and basic structure

**Files:**
- Create: `.gitignore`
- Create: `README.md`

- [ ] **Step 1: Initialize repo**

```powershell
git init
git branch -M main
```

- [ ] **Step 2: Write .gitignore**

```
__pycache__/
*.py[cod]
.venv/
work/
out/
.superpowers/
.pytest_cache/
*.egg-info/
.coverage
```

- [ ] **Step 3: Write README.md stub**

```markdown
# VTuber Clipper
See spec.md, architecture.md, interaction-design.md for design. MILESTONES.md for build order.
```

- [ ] **Step 4: Initial commit**

```bash
git add .gitignore README.md spec.md research.md architecture.md MILESTONES.md changelog.md interaction-design.md plan-a-interaction.md
git commit -m "chore: initial project scaffolding and design docs"
```

---

### Task 2: pyproject.toml with all dependencies

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Write pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "vtuber-clipper"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = [
    "faster-whisper>=1.0.3",
    "chat-downloader>=0.2.8",
    "yt-dlp>=2024.10.0",
    "numpy>=1.26",
    "scipy>=1.13",
    "mediapipe>=0.10.14",
    "opencv-python>=4.10",
    "pydantic>=2.8",
    "rich>=13.7",
    "click>=8.1",
    "httpx>=0.27",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "python-multipart>=0.0.9",
    "nvidia-cudnn-cu12>=9.0,<10.0",
]

[project.optional-dependencies]
anthropic = ["anthropic>=0.39"]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "pytest-mock>=3.12"]

[project.scripts]
clipper = "clipper.main:cli"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
"clipper" = ["web/*.html", "web/*.css", "web/*.js"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create venv and install**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
```

- [ ] **Step 3: Verify install**

Run: `clipper --help`
Expected: command not found yet (we haven't written the CLI) — install succeeded if pip didn't error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: pyproject.toml with deps including FastAPI + uvicorn"
```

---

### Task 3: Util modules — timing, logging, slug

**Files:**
- Create: `src/clipper/__init__.py`
- Create: `src/clipper/util/__init__.py`
- Create: `src/clipper/util/timing.py`
- Create: `src/clipper/util/logging.py`
- Create: `src/clipper/util/slug.py`
- Create: `tests/test_slug.py`

- [ ] **Step 1: Write failing slug test**

`tests/test_slug.py`:
```python
from clipper.util.slug import slugify

def test_slugify_basic():
    assert slugify("HOLY NO WAY") == "holy-no-way"

def test_slugify_punctuation():
    assert slugify("I can't believe it!") == "i-cant-believe-it"

def test_slugify_trims_to_max_length():
    long = "a" * 100
    assert len(slugify(long, max_len=60)) == 60

def test_slugify_handles_unicode():
    assert slugify("café — résumé") == "cafe-resume"

def test_slugify_index_prefix():
    assert slugify("hello", index=3) == "03_hello"
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_slug.py -v`
Expected: ImportError or AttributeError on `slugify`.

- [ ] **Step 3: Implement slug**

`src/clipper/util/slug.py`:
```python
import re
import unicodedata

def slugify(text: str, max_len: int = 60, index: int | None = None) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lower = ascii_only.lower()
    no_punct = re.sub(r"[^\w\s-]", "", lower)
    hyphenated = re.sub(r"[\s_]+", "-", no_punct).strip("-")
    truncated = hyphenated[:max_len].rstrip("-")
    if index is not None:
        return f"{index:02d}_{truncated}"
    return truncated
```

- [ ] **Step 4: Write timing module (no test — trivial)**

`src/clipper/util/timing.py`:
```python
def seconds_to_hms(seconds: float) -> str:
    """1234.567 -> '00:20:34.567'"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"

def seconds_to_srt(seconds: float) -> str:
    """SRT uses comma decimal: '00:20:34,567'"""
    return seconds_to_hms(seconds).replace(".", ",")

def hms_to_seconds(hms: str) -> float:
    """'00:20:34.567' -> 1234.567"""
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)
```

- [ ] **Step 5: Write logging module**

`src/clipper/util/logging.py`:
```python
import logging
from rich.logging import RichHandler

_configured = False

def get_logger(name: str) -> logging.Logger:
    global _configured
    if not _configured:
        logging.basicConfig(
            level=logging.INFO,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
        )
        _configured = True
    return logging.getLogger(name)
```

- [ ] **Step 6: Create empty __init__.py files**

`src/clipper/__init__.py`: empty
`src/clipper/util/__init__.py`: empty

- [ ] **Step 7: Run slug tests**

Run: `pytest tests/test_slug.py -v`
Expected: all 5 pass.

- [ ] **Step 8: Commit**

```bash
git add src/clipper/__init__.py src/clipper/util/ tests/test_slug.py
git commit -m "feat: util modules (timing, logging, slug) with tests"
```

---

### Task 4: Free-port discovery

**Files:**
- Create: `src/clipper/util/ports.py`
- Create: `tests/test_ports.py`

- [ ] **Step 1: Write failing test**

`tests/test_ports.py`:
```python
import socket
from clipper.util.ports import find_free_port

def test_find_free_port_in_range():
    port = find_free_port(start=8765, end=8800)
    assert 8765 <= port <= 8800

def test_find_free_port_skips_busy():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 8765))
    s.listen(1)
    try:
        port = find_free_port(start=8765, end=8800)
        assert port != 8765
    finally:
        s.close()

def test_find_free_port_raises_when_exhausted():
    import pytest
    with pytest.raises(RuntimeError, match="No free port"):
        find_free_port(start=1, end=0)  # invalid range
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_ports.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

`src/clipper/util/ports.py`:
```python
import socket

def find_free_port(start: int = 8765, end: int = 8800, host: str = "127.0.0.1") -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port in range {start}-{end}")
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/test_ports.py -v`
Expected: 3 pass.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/util/ports.py tests/test_ports.py
git commit -m "feat: free-port discovery helper"
```

---

## Phase 1 — Test Fixtures

### Task 5: Fixture video + fixture JSON files

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/fixtures/make_fixture_video.py`
- Create: `tests/fixtures/ranked.sample.json`
- Create: `tests/fixtures/transcript.sample.json`
- Create: `tests/fixtures/face_track.sample.json`

- [ ] **Step 1: Write fixture video generator**

`tests/fixtures/make_fixture_video.py`:
```python
"""Generate a 60-second 1080x1080 fixture video. Run once; output committed."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "fixture_video.mp4"

def main() -> None:
    if OUT.exists():
        print(f"{OUT} already exists, skipping")
        return
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=60",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=60",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(OUT),
    ]
    subprocess.run(cmd, check=True)
    print(f"Wrote {OUT}")

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Generate the fixture video**

Run: `python tests/fixtures/make_fixture_video.py`
Expected: `tests/fixtures/fixture_video.mp4` exists (~5 MB).

- [ ] **Step 3: Write fixture ranked.json**

`tests/fixtures/ranked.sample.json`:
```json
[
  {
    "id": "c001",
    "t_start_refined": 5.0,
    "t_end_refined": 15.0,
    "score": 87,
    "hook_quality": 9,
    "standalone": true,
    "title": "HOLY NO WAY THAT JUST HAPPENED",
    "reason": "Strong audio + chat reaction with clean sentence boundaries",
    "signals": ["audio", "chat"],
    "audio_intensity": 14.2,
    "chat_hype_score": 87.3,
    "msg_count": 142,
    "top_emotes": ["KEKW", "LULW", "OMEGALUL"]
  },
  {
    "id": "c002",
    "t_start_refined": 20.0,
    "t_end_refined": 35.0,
    "score": 75,
    "hook_quality": 6,
    "standalone": true,
    "title": "I cannot believe what just happened",
    "reason": "Sustained chat reaction",
    "signals": ["chat"],
    "audio_intensity": 4.1,
    "chat_hype_score": 65.0,
    "msg_count": 88,
    "top_emotes": ["LULW", "POG"]
  },
  {
    "id": "c003",
    "t_start_refined": 40.0,
    "t_end_refined": 55.0,
    "score": 68,
    "hook_quality": 5,
    "standalone": true,
    "title": "the chat reaction is wild",
    "reason": "Audio peak with delayed chat",
    "signals": ["audio", "chat"],
    "audio_intensity": 9.5,
    "chat_hype_score": 42.1,
    "msg_count": 60,
    "top_emotes": ["POG", "KEKW"]
  }
]
```

- [ ] **Step 4: Write fixture transcript.json**

`tests/fixtures/transcript.sample.json`:
```json
{
  "segments": [
    {
      "start": 5.0,
      "end": 15.0,
      "text": "holy no way that just happened",
      "words": [
        {"start": 5.0, "end": 5.3, "word": "holy"},
        {"start": 5.4, "end": 5.7, "word": "no"},
        {"start": 5.8, "end": 6.2, "word": "way"},
        {"start": 6.3, "end": 6.6, "word": "that"},
        {"start": 6.7, "end": 7.0, "word": "just"},
        {"start": 7.1, "end": 7.6, "word": "happened"}
      ]
    },
    {
      "start": 20.0,
      "end": 35.0,
      "text": "i cannot believe what just happened on this stream",
      "words": [
        {"start": 20.0, "end": 20.3, "word": "i"},
        {"start": 20.4, "end": 20.9, "word": "cannot"},
        {"start": 21.0, "end": 21.6, "word": "believe"},
        {"start": 21.7, "end": 22.0, "word": "what"},
        {"start": 22.1, "end": 22.4, "word": "just"},
        {"start": 22.5, "end": 23.1, "word": "happened"}
      ]
    },
    {
      "start": 40.0,
      "end": 55.0,
      "text": "the chat reaction is wild",
      "words": [
        {"start": 40.0, "end": 40.3, "word": "the"},
        {"start": 40.4, "end": 40.7, "word": "chat"},
        {"start": 40.8, "end": 41.6, "word": "reaction"},
        {"start": 41.7, "end": 41.9, "word": "is"},
        {"start": 42.0, "end": 42.6, "word": "wild"}
      ]
    }
  ]
}
```

- [ ] **Step 5: Write fixture face_track.json**

`tests/fixtures/face_track.sample.json`:
```json
{
  "c001": {"fps_sampled": 2, "track": [[0.0, 0.6], [0.5, 0.6], [1.0, 0.6], [10.0, 0.6]]},
  "c002": {"fps_sampled": 2, "track": [[0.0, 0.5], [0.5, 0.5], [15.0, 0.5]]},
  "c003": {"fps_sampled": 2, "track": [[0.0, 0.55], [15.0, 0.55]]}
}
```

- [ ] **Step 6: Write conftest.py with shared fixtures**

`tests/conftest.py`:
```python
import json
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.fixture
def fixture_work_dir(tmp_path: Path) -> Path:
    """Synthetic work/<vod_id>/ directory with all upstream files in place."""
    work = tmp_path / "work" / "vod_test"
    work.mkdir(parents=True)
    shutil.copy(FIXTURES / "fixture_video.mp4", work / "video.mp4")
    shutil.copy(FIXTURES / "ranked.sample.json", work / "ranked.json")
    shutil.copy(FIXTURES / "transcript.sample.json", work / "transcript.json")
    shutil.copy(FIXTURES / "face_track.sample.json", work / "face_track.json")
    return work

@pytest.fixture
def fixture_out_dir(tmp_path: Path) -> Path:
    out = tmp_path / "out" / "vod_test"
    out.mkdir(parents=True)
    return out
```

- [ ] **Step 7: Commit (do NOT commit fixture_video.mp4 — it's a binary regenerated on demand)**

Add to `.gitignore`:
```
tests/fixtures/fixture_video.mp4
```

```bash
git add tests/conftest.py tests/fixtures/ .gitignore
git commit -m "test: fixtures for ranked/transcript/face_track + video generator"
```

---

### Task 5.5: Shared helpers — json_io, ffmpeg, transcript

These three modules eliminate duplication that would otherwise show up in Tasks 6, 10, 11, 12, and every Plan B effect. Build them first; downstream tasks use them.

**Files:**
- Create: `src/clipper/util/json_io.py`
- Create: `src/clipper/util/ffmpeg.py`
- Create: `src/clipper/util/transcript.py`
- Create: `tests/test_json_io.py`
- Create: `tests/test_ffmpeg.py`
- Create: `tests/test_transcript.py`

- [ ] **Step 1: Write failing tests for json_io**

`tests/test_json_io.py`:
```python
from pathlib import Path

from clipper.util.json_io import read_json, write_json, read_jsonl


def test_write_read_roundtrip(tmp_path: Path):
    p = tmp_path / "a.json"
    write_json(p, {"x": 1, "y": [2, 3]})
    assert read_json(p) == {"x": 1, "y": [2, 3]}


def test_read_jsonl_iterates_lines(tmp_path: Path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"a": 1}\n{"a": 2}\n\n{"a": 3}\n', encoding="utf-8")
    assert list(read_jsonl(p)) == [{"a": 1}, {"a": 2}, {"a": 3}]
```

- [ ] **Step 2: Implement json_io**

`src/clipper/util/json_io.py`:
```python
import json
from pathlib import Path
from typing import Any, Iterator

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    path.write_text(json.dumps(data, indent=indent), encoding="utf-8")

def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
```

- [ ] **Step 3: Verify json_io tests pass**

Run: `pytest tests/test_json_io.py -v`
Expected: 2 pass.

- [ ] **Step 4: Write failing tests for ffmpeg helpers**

`tests/test_ffmpeg.py`:
```python
import subprocess
from pathlib import Path

import pytest

from clipper.util.ffmpeg import FINAL, PREVIEW, encode_clip, run_ffmpeg


def test_profiles_have_expected_dimensions():
    assert (PREVIEW.width, PREVIEW.height) == (540, 960)
    assert (FINAL.width, FINAL.height) == (1080, 1920)
    assert PREVIEW.nvenc_preset == "p7"
    assert FINAL.nvenc_preset == "p5"


def test_run_ffmpeg_raises_on_bad_args():
    with pytest.raises(subprocess.CalledProcessError):
        run_ffmpeg(["-this-is-not-a-real-flag"])


def test_encode_clip_produces_file_at_profile_size(tmp_path: Path):
    # Generate a 3s source video
    src = tmp_path / "src.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(src),
    ], check=True)

    out = tmp_path / "out.mp4"
    encode_clip(src, t_start=0.0, duration=2.0, out=out, profile=PREVIEW)
    assert out.exists()
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )
    w, h = res.stdout.strip().split(",")
    assert (int(w), int(h)) == (540, 960)
```

- [ ] **Step 5: Implement ffmpeg helpers**

`src/clipper/util/ffmpeg.py`:
```python
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EncodeProfile:
    width: int
    height: int
    nvenc_preset: str    # "p5", "p7"
    cq: int              # 0-51 (23 ~ good, 28 ~ preview)
    audio_bitrate: str   # "96k", "128k"


PREVIEW = EncodeProfile(540, 960, "p7", 28, "96k")
FINAL = EncodeProfile(1080, 1920, "p5", 23, "128k")


def run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg with standard prefix. Raises CalledProcessError on non-zero exit."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *args]
    subprocess.run(cmd, check=True)


def encode_clip(
    src: Path,
    t_start: float,
    duration: float,
    out: Path,
    profile: EncodeProfile,
    subtitles_path: Path | None = None,
    extra_filters: list[str] | None = None,
) -> None:
    """Encode a clip with crop+scale to profile dimensions, optional burned subtitles + extra filters."""
    crop_scale = (
        f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=increase,"
        f"crop={profile.width}:{profile.height}"
    )
    filters = [crop_scale]
    if extra_filters:
        filters.extend(extra_filters)
    if subtitles_path is not None:
        escaped = str(subtitles_path).replace("\\", "/").replace(":", "\\:")
        filters.append(f"subtitles='{escaped}'")
    vf = ",".join(filters)
    run_ffmpeg([
        "-ss", str(t_start),
        "-i", str(src),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "h264_nvenc", "-preset", profile.nvenc_preset, "-cq:v", str(profile.cq),
        "-c:a", "aac", "-b:a", profile.audio_bitrate,
        "-movflags", "+faststart",
        str(out),
    ])
```

- [ ] **Step 6: Verify ffmpeg tests pass**

Run: `pytest tests/test_ffmpeg.py -v`
Expected: 3 pass. (Requires ffmpeg with NVENC; the third test is the heavy one.)

- [ ] **Step 7: Write failing tests for transcript helpers**

`tests/test_transcript.py`:
```python
from pathlib import Path

from clipper.util.transcript import load_transcript, words_in_window


def test_load_transcript_returns_dict(fixture_work_dir: Path):
    t = load_transcript(fixture_work_dir)
    assert "segments" in t


def test_words_in_window_filters_by_time(fixture_work_dir: Path):
    t = load_transcript(fixture_work_dir)
    # c001 is [5.0, 15.0] in the fixture
    words = words_in_window(t, 5.0, 15.0)
    assert words[0]["word"] == "holy"
    for w in words:
        assert 5.0 <= w["start"] < 15.0


def test_words_in_window_excludes_boundary_end():
    t = {"segments": [{"words": [
        {"start": 0.0, "end": 0.5, "word": "a"},
        {"start": 1.0, "end": 1.5, "word": "b"},
        {"start": 2.0, "end": 2.5, "word": "c"},
    ]}]}
    assert [w["word"] for w in words_in_window(t, 0.5, 2.0)] == ["b"]
```

- [ ] **Step 8: Implement transcript helpers**

`src/clipper/util/transcript.py`:
```python
from pathlib import Path

from clipper.util.json_io import read_json


def load_transcript(work_dir: Path) -> dict:
    return read_json(work_dir / "transcript.json")


def words_in_window(transcript: dict, t_start: float, t_end: float) -> list[dict]:
    out = []
    for seg in transcript["segments"]:
        for w in seg.get("words", []):
            if t_start <= w["start"] < t_end:
                out.append(w)
    return out
```

- [ ] **Step 9: Verify transcript tests pass**

Run: `pytest tests/test_transcript.py -v`
Expected: 3 pass.

- [ ] **Step 10: Commit**

```bash
git add src/clipper/util/json_io.py src/clipper/util/ffmpeg.py src/clipper/util/transcript.py \
        tests/test_json_io.py tests/test_ffmpeg.py tests/test_transcript.py
git commit -m "feat: shared util helpers (json_io, ffmpeg, transcript) to prevent duplication"
```

---

## Phase 2 — preview_export

### Task 6: preview_export emits one MP4 per ranked clip

**Files:**
- Create: `src/clipper/preview_export.py`
- Create: `tests/test_preview_export.py`

- [ ] **Step 1: Write failing test**

`tests/test_preview_export.py`:
```python
import json
from pathlib import Path

from clipper.preview_export import preview_export

def test_emits_one_mp4_per_ranked_clip(fixture_work_dir: Path):
    out = preview_export(fixture_work_dir)
    assert out.exists()
    previews = fixture_work_dir / "previews"
    assert (previews / "c001.mp4").exists()
    assert (previews / "c002.mp4").exists()
    assert (previews / "c003.mp4").exists()

def test_preview_is_540x960(fixture_work_dir: Path):
    import subprocess
    preview_export(fixture_work_dir)
    p = fixture_work_dir / "previews" / "c001.mp4"
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, check=True,
    )
    w, h = res.stdout.strip().split(",")
    assert int(w) == 540 and int(h) == 960

def test_idempotent_skip(fixture_work_dir: Path):
    preview_export(fixture_work_dir)
    p = fixture_work_dir / "previews" / "c001.mp4"
    mtime = p.stat().st_mtime
    preview_export(fixture_work_dir)
    assert p.stat().st_mtime == mtime  # unchanged
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_preview_export.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement (uses shared helpers from Task 5.5)**

`src/clipper/preview_export.py`:
```python
from pathlib import Path

from clipper.util.ffmpeg import PREVIEW, encode_clip
from clipper.util.json_io import read_json
from clipper.util.logging import get_logger

logger = get_logger(__name__)


def preview_export(work_dir: Path) -> Path:
    """Generate 540x960 NVENC previews for every clip in ranked.json."""
    previews_dir = work_dir / "previews"
    previews_dir.mkdir(exist_ok=True)
    video = work_dir / "video.mp4"

    for clip in read_json(work_dir / "ranked.json"):
        out_path = previews_dir / f"{clip['id']}.mp4"
        if out_path.exists():
            logger.info(f"skip {clip['id']} (exists)")
            continue
        duration = clip["t_end_refined"] - clip["t_start_refined"]
        encode_clip(video, clip["t_start_refined"], duration, out_path, PREVIEW)
    return previews_dir
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/test_preview_export.py -v`
Expected: 3 pass. (Requires ffmpeg with NVENC on PATH — verify via env-check from research.md §1 first.)

- [ ] **Step 5: Commit**

```bash
git add src/clipper/preview_export.py tests/test_preview_export.py
git commit -m "feat: preview_export emits fast 540x960 NVENC clips"
```

---

## Phase 3 — Web Server Shell

### Task 7: FastAPI app + GET /api/clips

**Files:**
- Create: `src/clipper/web.py`
- Create: `tests/test_web_endpoints.py`

- [ ] **Step 1: Write failing test**

`tests/test_web_endpoints.py`:
```python
from pathlib import Path

from fastapi.testclient import TestClient

from clipper.web import build_app

def test_get_clips_returns_ranked_list(fixture_work_dir: Path):
    app = build_app(fixture_work_dir)
    client = TestClient(app)
    r = client.get("/api/clips")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    assert body[0]["id"] == "c001"
    assert body[0]["title"] == "HOLY NO WAY THAT JUST HAPPENED"
    assert body[0]["kept"] is True   # default-kept
    assert body[0]["caption_mode"] == "burned"
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_web_endpoints.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

`src/clipper/web.py`:
```python
import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

DEFAULT_EFFECTS = {
    "punch_zoom": True,
    "emoji_burst": True,
    "hook_card": True,
    "reaction_zoom": True,
}

class ClipState(BaseModel):
    id: str
    title: str
    t_start: float
    t_end: float
    kept: bool = True
    caption_mode: Literal["burned", "clean", "both"] = "burned"
    effects: dict[str, bool] = DEFAULT_EFFECTS.copy()
    score: int
    hook_quality: int
    reason: str
    top_emotes: list[str]

def _load_initial_clips(work_dir: Path) -> list[ClipState]:
    ranked = json.loads((work_dir / "ranked.json").read_text())
    return [
        ClipState(
            id=c["id"],
            title=c["title"],
            t_start=c["t_start_refined"],
            t_end=c["t_end_refined"],
            score=c["score"],
            hook_quality=c.get("hook_quality", 0),
            reason=c.get("reason", ""),
            top_emotes=c.get("top_emotes", []),
        )
        for c in ranked
    ]

def build_app(work_dir: Path) -> FastAPI:
    app = FastAPI()
    app.state.work_dir = work_dir
    app.state.clips = {c.id: c for c in _load_initial_clips(work_dir)}

    @app.get("/api/clips")
    def list_clips() -> list[ClipState]:
        return list(app.state.clips.values())

    return app
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/test_web_endpoints.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/web.py tests/test_web_endpoints.py
git commit -m "feat: FastAPI app skeleton with GET /api/clips"
```

---

### Task 8: PUT /api/clips/{id} with review_state.json persistence

**Files:**
- Modify: `src/clipper/web.py`
- Create: `tests/test_review_state.py`

- [ ] **Step 1: Write failing tests**

`tests/test_review_state.py`:
```python
import json
from pathlib import Path

from fastapi.testclient import TestClient

from clipper.web import build_app

def test_put_updates_clip_in_memory(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    r = client.put("/api/clips/c001", json={"title": "NEW TITLE", "kept": False})
    assert r.status_code == 200
    assert r.json()["title"] == "NEW TITLE"
    assert r.json()["kept"] is False

def test_put_persists_to_review_state_json(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    client.put("/api/clips/c001", json={"title": "PERSISTED"})
    state = json.loads((fixture_work_dir / "review_state.json").read_text())
    assert state["clips"]["c001"]["title"] == "PERSISTED"

def test_state_loaded_on_startup(fixture_work_dir: Path):
    (fixture_work_dir / "review_state.json").write_text(json.dumps({
        "vod_id": "vod_test",
        "schema_version": "0.1.0",
        "last_modified": "2026-05-11T00:00:00Z",
        "clips": {"c001": {"title": "FROM DISK", "t_start": 5.0, "t_end": 15.0,
                           "kept": False, "caption_mode": "clean", "effects": {}}}
    }))
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/api/clips")
    c001 = next(c for c in r.json() if c["id"] == "c001")
    assert c001["title"] == "FROM DISK"
    assert c001["kept"] is False
    assert c001["caption_mode"] == "clean"

def test_put_rejects_invalid_trim(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    r = client.put("/api/clips/c001", json={"t_start": 14.0, "t_end": 15.0})  # 1s clip
    assert r.status_code == 400
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_review_state.py -v`
Expected: 404 / missing endpoint.

- [ ] **Step 3: Update web.py**

Replace `src/clipper/web.py` with:
```python
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DEFAULT_EFFECTS = {
    "punch_zoom": True,
    "emoji_burst": True,
    "hook_card": True,
    "reaction_zoom": True,
}
STATE_SCHEMA_VERSION = "0.1.0"
MIN_CLIP_SECONDS = 2.0

class ClipState(BaseModel):
    id: str
    title: str
    t_start: float
    t_end: float
    kept: bool = True
    caption_mode: Literal["burned", "clean", "both"] = "burned"
    effects: dict[str, bool] = Field(default_factory=lambda: DEFAULT_EFFECTS.copy())
    score: int
    hook_quality: int
    reason: str
    top_emotes: list[str]

class ClipUpdate(BaseModel):
    title: str | None = None
    t_start: float | None = None
    t_end: float | None = None
    kept: bool | None = None
    caption_mode: Literal["burned", "clean", "both"] | None = None
    effects: dict[str, bool] | None = None

def _initial_clips(work_dir: Path) -> dict[str, ClipState]:
    ranked = json.loads((work_dir / "ranked.json").read_text())
    base = {
        c["id"]: ClipState(
            id=c["id"],
            title=c["title"],
            t_start=c["t_start_refined"],
            t_end=c["t_end_refined"],
            score=c["score"],
            hook_quality=c.get("hook_quality", 0),
            reason=c.get("reason", ""),
            top_emotes=c.get("top_emotes", []),
        )
        for c in ranked
    }
    state_path = work_dir / "review_state.json"
    if state_path.exists():
        saved = json.loads(state_path.read_text())
        for cid, overrides in saved.get("clips", {}).items():
            if cid in base:
                merged = base[cid].model_dump()
                merged.update(overrides)
                base[cid] = ClipState(**merged)
    return base

def _persist(work_dir: Path, clips: dict[str, ClipState]) -> None:
    payload = {
        "vod_id": work_dir.name,
        "schema_version": STATE_SCHEMA_VERSION,
        "last_modified": datetime.now(timezone.utc).isoformat(),
        "clips": {cid: c.model_dump() for cid, c in clips.items()},
    }
    (work_dir / "review_state.json").write_text(json.dumps(payload, indent=2))

def build_app(work_dir: Path) -> FastAPI:
    app = FastAPI()
    app.state.work_dir = work_dir
    app.state.clips = _initial_clips(work_dir)

    @app.get("/api/clips")
    def list_clips() -> list[ClipState]:
        return list(app.state.clips.values())

    @app.put("/api/clips/{clip_id}")
    def update_clip(clip_id: str, patch: ClipUpdate) -> ClipState:
        if clip_id not in app.state.clips:
            raise HTTPException(404, "no such clip")
        current = app.state.clips[clip_id]
        merged = current.model_dump()
        for k, v in patch.model_dump(exclude_none=True).items():
            merged[k] = v
        if merged["t_end"] - merged["t_start"] < MIN_CLIP_SECONDS:
            raise HTTPException(400, f"clip must be at least {MIN_CLIP_SECONDS}s")
        updated = ClipState(**merged)
        app.state.clips[clip_id] = updated
        _persist(work_dir, app.state.clips)
        return updated

    return app
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/test_review_state.py tests/test_web_endpoints.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/web.py tests/test_review_state.py
git commit -m "feat: PUT /api/clips/{id} with review_state.json persistence"
```

---

### Task 9: Range-request support for preview MP4 streaming

**Files:**
- Create: `src/clipper/util/range_response.py`
- Modify: `src/clipper/web.py`
- Create: `tests/test_range_response.py`

- [ ] **Step 1: Write failing tests**

`tests/test_range_response.py`:
```python
from pathlib import Path

from fastapi.testclient import TestClient

from clipper.preview_export import preview_export
from clipper.web import build_app

def test_full_file_returns_200(fixture_work_dir: Path):
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/api/clips/c001/preview.mp4")
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"

def test_range_returns_206_and_partial(fixture_work_dir: Path):
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/api/clips/c001/preview.mp4", headers={"Range": "bytes=0-1023"})
    assert r.status_code == 206
    assert len(r.content) == 1024
    assert r.headers["content-range"].startswith("bytes 0-1023/")

def test_missing_preview_returns_404(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/api/clips/c001/preview.mp4")
    assert r.status_code == 404
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_range_response.py -v`
Expected: 404 on the endpoint (not implemented).

- [ ] **Step 3: Implement range helper**

`src/clipper/util/range_response.py`:
```python
import re
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, Response

RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")

def range_or_full(request: Request, path: Path, media_type: str = "video/mp4") -> Response:
    if not path.exists():
        from fastapi import HTTPException
        raise HTTPException(404, f"missing: {path.name}")
    range_header = request.headers.get("range")
    file_size = path.stat().st_size
    if not range_header:
        return FileResponse(path, media_type=media_type)
    m = RANGE_RE.match(range_header)
    if not m:
        return FileResponse(path, media_type=media_type)
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else file_size - 1
    end = min(end, file_size - 1)
    length = end - start + 1
    with path.open("rb") as f:
        f.seek(start)
        data = f.read(length)
    return Response(
        content=data,
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        },
    )
```

- [ ] **Step 4: Wire endpoint into web.py**

Add to `build_app()` in `src/clipper/web.py` (after the PUT handler):
```python
    from fastapi import Request
    from clipper.util.range_response import range_or_full

    @app.get("/api/clips/{clip_id}/preview.mp4")
    def get_preview(clip_id: str, request: Request):
        if clip_id not in app.state.clips:
            raise HTTPException(404, "no such clip")
        path = work_dir / "previews" / f"{clip_id}.mp4"
        return range_or_full(request, path)
```

- [ ] **Step 5: Verify pass**

Run: `pytest tests/test_range_response.py -v`
Expected: 3 pass.

- [ ] **Step 6: Commit**

```bash
git add src/clipper/util/range_response.py src/clipper/web.py tests/test_range_response.py
git commit -m "feat: HTTP range support for preview MP4 streaming"
```

---

### Task 10: GET /api/clips/{id}/transcript

**Files:**
- Modify: `src/clipper/web.py`
- Modify: `tests/test_web_endpoints.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_web_endpoints.py`:
```python
def test_get_transcript_returns_words_in_clip_window(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/api/clips/c001/transcript")
    assert r.status_code == 200
    words = r.json()
    # c001 is [5.0, 15.0]; first word "holy" starts at 5.0
    assert words[0]["word"] == "holy"
    # All words should fall within [5.0, 15.0]
    for w in words:
        assert 5.0 <= w["start"] < 15.0
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_web_endpoints.py::test_get_transcript_returns_words_in_clip_window -v`

- [ ] **Step 3: Implement (uses transcript helper from Task 5.5)**

Add at the top of `src/clipper/web.py`:
```python
from clipper.util.transcript import load_transcript, words_in_window
```

Add to `build_app()` in `src/clipper/web.py`:
```python
    @app.get("/api/clips/{clip_id}/transcript")
    def get_transcript(clip_id: str) -> list[dict]:
        if clip_id not in app.state.clips:
            raise HTTPException(404, "no such clip")
        clip = app.state.clips[clip_id]
        return words_in_window(load_transcript(work_dir), clip.t_start, clip.t_end)
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/test_web_endpoints.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/web.py tests/test_web_endpoints.py
git commit -m "feat: GET /api/clips/{id}/transcript returns clip-window words"
```

---

## Phase 4 — captions.py (plain SRT, basic ASS for burn)

### Task 11: SRT generation from word list

**Files:**
- Create: `src/clipper/captions.py`
- Create: `tests/test_captions.py`

- [ ] **Step 1: Write failing tests**

`tests/test_captions.py`:
```python
from clipper.captions import generate_srt, generate_basic_ass

WORDS = [
    {"start": 5.0, "end": 5.3, "word": "holy"},
    {"start": 5.4, "end": 5.7, "word": "no"},
    {"start": 5.8, "end": 6.2, "word": "way"},
]

def test_srt_uses_clip_local_time():
    srt = generate_srt(WORDS, clip_start=5.0, max_words_per_cue=3)
    assert "00:00:00,000" in srt
    assert "holy no way" in srt
    assert "5.0" not in srt    # not source-local
    assert "-->" in srt

def test_srt_groups_words_into_cues():
    many = [{"start": i * 0.5, "end": i * 0.5 + 0.4, "word": f"w{i}"} for i in range(10)]
    srt = generate_srt(many, clip_start=0.0, max_words_per_cue=3)
    # 10 words / 3 per cue = 4 cues
    assert srt.count("-->") == 4

def test_basic_ass_has_styles_block():
    ass = generate_basic_ass(WORDS, clip_start=5.0, output_size=(1080, 1920))
    assert "[Script Info]" in ass
    assert "[V4+ Styles]" in ass
    assert "[Events]" in ass
    assert "Dialogue:" in ass

def test_ass_dialogue_uses_clip_local_time():
    ass = generate_basic_ass(WORDS, clip_start=5.0, output_size=(1080, 1920))
    # 0.0 - 0.3 in clip-local = first word "holy"
    assert "0:00:00.00" in ass
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_captions.py -v`

- [ ] **Step 3: Implement (AssBuilder is reused by Plan B effects)**

`src/clipper/captions.py`:
```python
from dataclasses import dataclass, field

from clipper.util.timing import seconds_to_srt

_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
    "Bold, Outline, Shadow, Alignment, MarginV"
)
_EVENT_FORMAT = (
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
)


def _ass_time(seconds: float) -> str:
    """ASS uses H:MM:SS.cs (centiseconds)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h}:{m:02d}:{s:05.2f}"


@dataclass
class AssBuilder:
    """Accumulates ASS styles and dialogue events; renders to a complete .ass document.

    Used by `generate_basic_ass` here and by every Plan B effect that emits ASS layers
    (emoji_burst, hook_card, etc.). Compose them by passing one AssBuilder around.
    """
    width: int
    height: int
    style_lines: list[str] = field(default_factory=list)
    event_lines: list[str] = field(default_factory=list)

    def add_style(
        self,
        name: str = "Default",
        fontname: str = "Arial Black",
        fontsize: int = 72,
        primary: str = "&H00FFFFFF",
        outline: str = "&H00000000",
        bold: int = 1,
        outline_width: int = 4,
        margin_v: int = 300,
        alignment: int = 2,
    ) -> None:
        self.style_lines.append(
            f"Style: {name},{fontname},{fontsize},{primary},{outline},&H00000000,"
            f"{bold},{outline_width},0,{alignment},{margin_v}"
        )

    def add_dialogue(
        self,
        start: float,
        end: float,
        text: str,
        style: str = "Default",
        layer: int = 0,
        margin_l: int = 0,
        margin_r: int = 0,
        margin_v: int = 0,
        effect: str = "",
    ) -> None:
        self.event_lines.append(
            f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},{style},,"
            f"{margin_l},{margin_r},{margin_v},{effect},{text}"
        )

    def render(self) -> str:
        if not self.style_lines:
            self.add_style()
        sections = [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {self.width}",
            f"PlayResY: {self.height}",
            "",
            "[V4+ Styles]",
            _STYLE_FORMAT,
            *self.style_lines,
            "",
            "[Events]",
            _EVENT_FORMAT,
            *self.event_lines,
            "",
        ]
        return "\n".join(sections)


def generate_srt(words: list[dict], clip_start: float, max_words_per_cue: int = 3) -> str:
    cues = []
    for i in range(0, len(words), max_words_per_cue):
        group = words[i : i + max_words_per_cue]
        start = group[0]["start"] - clip_start
        end = group[-1]["end"] - clip_start
        text = " ".join(w["word"] for w in group)
        idx = len(cues) + 1
        cues.append(
            f"{idx}\n{seconds_to_srt(start)} --> {seconds_to_srt(end)}\n{text}\n"
        )
    return "\n".join(cues)


def generate_basic_ass(
    words: list[dict],
    clip_start: float,
    output_size: tuple[int, int],
    max_words_per_cue: int = 3,
) -> str:
    builder = AssBuilder(width=output_size[0], height=output_size[1])
    for i in range(0, len(words), max_words_per_cue):
        group = words[i : i + max_words_per_cue]
        start = group[0]["start"] - clip_start
        end = group[-1]["end"] - clip_start
        text = " ".join(g["word"] for g in group)
        builder.add_dialogue(start, end, text)
    return builder.render()
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/test_captions.py -v`
Expected: 4 pass.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/captions.py tests/test_captions.py
git commit -m "feat: SRT and basic ASS caption generation"
```

---

## Phase 5 — finalize.py

### Task 12: finalize re-encodes only kept clips at full quality

**Files:**
- Create: `src/clipper/finalize.py`
- Create: `src/clipper/effects/__init__.py`
- Create: `src/clipper/effects/base.py`
- Create: `tests/test_finalize.py`

- [ ] **Step 1: Write effects/base.py (stub for Plan B)**

`src/clipper/effects/base.py`:
```python
from typing import Protocol

class FinalizeEffect(Protocol):
    name: str
    default_enabled: bool

    def apply(self, ctx: dict) -> None: ...
```

`src/clipper/effects/__init__.py`:
```python
from clipper.effects.base import FinalizeEffect
__all__ = ["FinalizeEffect"]
```

- [ ] **Step 2: Write failing test**

`tests/test_finalize.py`:
```python
import json
import subprocess
from pathlib import Path

from clipper.finalize import finalize
from clipper.preview_export import preview_export
from clipper.web import build_app
from fastapi.testclient import TestClient

def _mark_only_c001_kept(work: Path) -> None:
    client = TestClient(build_app(work))
    client.put("/api/clips/c002", json={"kept": False})
    client.put("/api/clips/c003", json={"kept": False})

def test_only_kept_clips_are_encoded(fixture_work_dir: Path, fixture_out_dir: Path):
    preview_export(fixture_work_dir)
    _mark_only_c001_kept(fixture_work_dir)
    finalize(fixture_work_dir, fixture_out_dir)
    final = fixture_out_dir / "final"
    files = sorted(p.name for p in final.glob("*.mp4"))
    assert len(files) == 1
    assert files[0].startswith("01_")

def test_final_is_1080x1920(fixture_work_dir: Path, fixture_out_dir: Path):
    preview_export(fixture_work_dir)
    _mark_only_c001_kept(fixture_work_dir)
    finalize(fixture_work_dir, fixture_out_dir)
    mp4 = next((fixture_out_dir / "final").glob("*.mp4"))
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(mp4)],
        capture_output=True, text=True, check=True,
    )
    w, h = res.stdout.strip().split(",")
    assert int(w) == 1080 and int(h) == 1920

def test_manifest_written(fixture_work_dir: Path, fixture_out_dir: Path):
    preview_export(fixture_work_dir)
    _mark_only_c001_kept(fixture_work_dir)
    finalize(fixture_work_dir, fixture_out_dir)
    manifest = json.loads((fixture_out_dir / "final" / "manifest.json").read_text())
    assert len(manifest["clips"]) == 1
    assert manifest["clips"][0]["title"] == "HOLY NO WAY THAT JUST HAPPENED"
```

- [ ] **Step 3: Run, expect failure**

Run: `pytest tests/test_finalize.py -v`
Expected: ImportError on `finalize`.

- [ ] **Step 4: Implement finalize (uses shared helpers)**

`src/clipper/finalize.py`:
```python
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from clipper.captions import generate_basic_ass, generate_srt
from clipper.util.ffmpeg import FINAL, encode_clip
from clipper.util.json_io import read_json, write_json
from clipper.util.logging import get_logger
from clipper.util.slug import slugify
from clipper.util.transcript import load_transcript, words_in_window

logger = get_logger(__name__)


def _kept_clips(work_dir: Path) -> list[dict]:
    state = read_json(work_dir / "review_state.json")
    return [
        {"id": cid, **data} for cid, data in state["clips"].items() if data.get("kept", True)
    ]


def finalize(work_dir: Path, out_root: Path) -> Path:
    final_dir = out_root / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    video = work_dir / "video.mp4"
    transcript = load_transcript(work_dir)
    kept = _kept_clips(work_dir)

    manifest_clips = []
    for idx, clip in enumerate(kept, start=1):
        slug = slugify(clip["title"], index=idx)
        base = final_dir / slug
        words = words_in_window(transcript, clip["t_start"], clip["t_end"])
        duration = clip["t_end"] - clip["t_start"]
        mode = clip.get("caption_mode", "burned")

        burned_path = None
        clean_path = None
        srt_path = None

        if mode in ("burned", "both"):
            with tempfile.NamedTemporaryFile(
                "w", suffix=".ass", delete=False, encoding="utf-8"
            ) as f:
                f.write(generate_basic_ass(words, clip["t_start"], (FINAL.width, FINAL.height)))
                ass_path = Path(f.name)
            try:
                burned_path = base.with_suffix(".mp4")
                encode_clip(video, clip["t_start"], duration, burned_path, FINAL,
                            subtitles_path=ass_path)
            finally:
                ass_path.unlink(missing_ok=True)

        if mode in ("clean", "both"):
            if mode == "both":
                clean_path = base.with_name(base.name + "_clean").with_suffix(".mp4")
            else:
                clean_path = base.with_suffix(".mp4")
            encode_clip(video, clip["t_start"], duration, clean_path, FINAL)
            srt_path = base.with_suffix(".srt")
            srt_path.write_text(generate_srt(words, clip["t_start"]))

        manifest_clips.append({
            "filename": burned_path.name if burned_path else clean_path.name,
            "clean_filename": clean_path.name if (mode == "both" and clean_path) else None,
            "srt_filename": srt_path.name if srt_path else None,
            "title": clip["title"],
            "t_start_source": clip["t_start"],
            "t_end_source": clip["t_end"],
            "duration": duration,
            "caption_mode": mode,
            "effects_applied": ["captions"] if mode != "clean" else [],
            "score": clip.get("score", 0),
            "hook_quality": clip.get("hook_quality", 0),
            "reason": clip.get("reason", ""),
            "top_emotes": clip.get("top_emotes", []),
        })

    manifest = {
        "vod_id": work_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "clips": manifest_clips,
    }
    write_json(final_dir / "manifest.json", manifest)
    logger.info(f"Finalized {len(manifest_clips)} clips to {final_dir}")
    return final_dir / "manifest.json"
```

- [ ] **Step 5: Verify pass**

Run: `pytest tests/test_finalize.py -v`
Expected: 3 pass.

- [ ] **Step 6: Commit**

```bash
git add src/clipper/finalize.py src/clipper/effects/ tests/test_finalize.py
git commit -m "feat: finalize.py with plain burned captions and manifest"
```

---

### Task 13: caption_mode=clean and mode=both produce the right files

**Files:**
- Modify: `tests/test_finalize.py`

- [ ] **Step 1: Add tests for clean and both modes**

Append to `tests/test_finalize.py`:
```python
def test_clean_mode_produces_no_captions_and_srt(fixture_work_dir, fixture_out_dir):
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    client.put("/api/clips/c001", json={"caption_mode": "clean"})
    client.put("/api/clips/c002", json={"kept": False})
    client.put("/api/clips/c003", json={"kept": False})
    finalize(fixture_work_dir, fixture_out_dir)
    final = fixture_out_dir / "final"
    mp4s = list(final.glob("*.mp4"))
    srts = list(final.glob("*.srt"))
    assert len(mp4s) == 1
    assert len(srts) == 1
    assert mp4s[0].stem == srts[0].stem

def test_both_mode_produces_burned_and_clean_and_srt(fixture_work_dir, fixture_out_dir):
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    client.put("/api/clips/c001", json={"caption_mode": "both"})
    client.put("/api/clips/c002", json={"kept": False})
    client.put("/api/clips/c003", json={"kept": False})
    finalize(fixture_work_dir, fixture_out_dir)
    final = fixture_out_dir / "final"
    files = sorted(p.name for p in final.iterdir())
    assert sum(1 for f in files if f.endswith(".mp4") and "_clean" not in f) == 1
    assert sum(1 for f in files if f.endswith("_clean.mp4")) == 1
    assert sum(1 for f in files if f.endswith(".srt")) == 1
```

- [ ] **Step 2: Run, expect pass (already implemented in Task 12)**

Run: `pytest tests/test_finalize.py -v`
Expected: 5 pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_finalize.py
git commit -m "test: clean and both caption modes produce the right files"
```

---

### Task 14: POST /api/finalize with SSE progress stream

**Files:**
- Modify: `src/clipper/web.py`
- Modify: `tests/test_finalize.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_finalize.py`:
```python
def test_post_finalize_streams_progress(fixture_work_dir, fixture_out_dir):
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir, out_root=fixture_out_dir))
    client.put("/api/clips/c002", json={"kept": False})
    client.put("/api/clips/c003", json={"kept": False})
    with client.stream("POST", "/api/finalize") as r:
        assert r.status_code == 200
        events = [line for line in r.iter_lines() if line.startswith("data:")]
    assert any("complete" in e for e in events)
```

- [ ] **Step 2: Update build_app signature + add endpoint**

In `src/clipper/web.py`, change `def build_app(work_dir: Path) -> FastAPI:` to:
```python
def build_app(work_dir: Path, out_root: Path | None = None) -> FastAPI:
```

After the existing endpoints, add:
```python
    import json as _json
    from fastapi.responses import StreamingResponse
    from clipper.finalize import finalize as _finalize_call

    _out_root = out_root if out_root is not None else (work_dir.parent.parent / "out" / work_dir.name)

    @app.post("/api/finalize")
    def post_finalize():
        def event_stream():
            try:
                kept_count = sum(1 for c in app.state.clips.values() if c.kept)
                yield f"data: {_json.dumps({'status': 'started', 'kept_count': kept_count})}\n\n"
                manifest = _finalize_call(work_dir, _out_root)
                yield f"data: {_json.dumps({'status': 'complete', 'manifest': str(manifest)})}\n\n"
            except Exception as exc:
                yield f"data: {_json.dumps({'status': 'error', 'msg': str(exc)})}\n\n"
        return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **Step 3: Run test**

Run: `pytest tests/test_finalize.py::test_post_finalize_streams_progress -v`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add src/clipper/web.py tests/test_finalize.py
git commit -m "feat: POST /api/finalize with SSE progress stream"
```

---

### Task 15: POST /api/shutdown

**Files:**
- Modify: `src/clipper/web.py`
- Modify: `tests/test_web_endpoints.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_web_endpoints.py`:
```python
def test_shutdown_signals_exit(fixture_work_dir: Path):
    app = build_app(fixture_work_dir)
    client = TestClient(app)
    r = client.post("/api/shutdown")
    assert r.status_code == 200
    assert app.state.should_exit is True
```

- [ ] **Step 2: Implement**

In `src/clipper/web.py`, after `app.state.clips = ...`, add:
```python
    app.state.should_exit = False
```

Add endpoint:
```python
    @app.post("/api/shutdown")
    def shutdown():
        app.state.should_exit = True
        return {"status": "shutting down"}
```

- [ ] **Step 3: Verify pass**

Run: `pytest tests/test_web_endpoints.py -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/clipper/web.py tests/test_web_endpoints.py
git commit -m "feat: POST /api/shutdown sets should_exit flag"
```

---

## Phase 6 — Frontend

### Task 16: index.html + app.css two-pane scaffold

**Files:**
- Create: `src/clipper/web/index.html`
- Create: `src/clipper/web/app.css`
- Modify: `src/clipper/web.py` (mount static)

- [ ] **Step 1: Write index.html**

`src/clipper/web/index.html`:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>VTuber Clipper · Review</title>
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
  <header class="topbar">
    <div id="vod-label">Loading…</div>
    <div id="kept-summary"></div>
  </header>
  <main class="panes">
    <aside id="clip-list" aria-label="Clip list"></aside>
    <section id="detail" aria-label="Clip detail">
      <video id="player" controls></video>
      <div id="captions-overlay"></div>
      <div class="edit-row">
        <label>Title <input id="title-input"></label>
      </div>
      <div class="edit-row trim">
        <label>Start <input id="t-start-input" type="text"></label>
        <label>End <input id="t-end-input" type="text"></label>
      </div>
      <div class="edit-row">
        <label>Captions
          <select id="caption-mode">
            <option value="burned">Burned</option>
            <option value="clean">Clean + SRT</option>
            <option value="both">Both</option>
          </select>
        </label>
      </div>
      <div class="edit-row buttons">
        <button id="keep-btn">✓ Keep</button>
        <button id="drop-btn">✗ Drop</button>
      </div>
      <div id="metadata"></div>
    </section>
  </main>
  <footer class="bottom-bar">
    <button id="finalize-btn">Finalize</button>
    <button id="done-btn">Done</button>
    <div id="finalize-progress"></div>
  </footer>
  <script src="/static/app.js" type="module"></script>
</body>
</html>
```

- [ ] **Step 2: Write app.css**

`src/clipper/web/app.css`:
```css
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; background: #161616; color: #e0e0e0;
       display: flex; flex-direction: column; height: 100vh; }
.topbar { display: flex; justify-content: space-between; padding: 10px 16px;
          background: #2a2a2a; border-bottom: 1px solid #444; }
.panes { display: flex; flex: 1; overflow: hidden; }
#clip-list { width: 320px; overflow-y: auto; background: #1a1a1a; border-right: 1px solid #444; }
.clip-row { padding: 10px 12px; border-bottom: 1px solid #333; cursor: pointer; }
.clip-row.selected { background: #2d4a6b; }
.clip-row.kept { border-left: 3px solid #4caf50; }
.clip-row.dropped { opacity: 0.4; }
.clip-row .title { font-weight: bold; }
.clip-row .meta { font-size: 11px; opacity: 0.7; margin-top: 2px; }
#detail { flex: 1; padding: 16px; overflow-y: auto; position: relative; }
#player { width: 100%; max-width: 360px; display: block; margin: 0 auto 12px; background: #000; }
#captions-overlay { position: absolute; top: 0; left: 50%; transform: translateX(-50%);
                    pointer-events: none; font-family: 'Arial Black', sans-serif;
                    font-size: 22px; color: white; text-shadow: 0 0 4px #000, -2px 0 0 #000,
                    2px 0 0 #000, 0 -2px 0 #000, 0 2px 0 #000; white-space: nowrap; }
.edit-row { margin: 8px 0; display: flex; gap: 12px; align-items: center; }
.edit-row label { display: flex; gap: 6px; align-items: center; flex: 1; }
input, select { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; padding: 4px 8px; }
.edit-row.buttons button { padding: 6px 16px; font-weight: bold; }
#keep-btn { background: #2d6b4a; color: white; border: none; cursor: pointer; }
#drop-btn { background: #6b2d2d; color: white; border: none; cursor: pointer; }
.bottom-bar { display: flex; gap: 12px; padding: 12px 16px; background: #2a2a2a;
              border-top: 1px solid #444; align-items: center; }
#finalize-btn { background: #2d4a6b; color: white; padding: 8px 20px; border: none;
                cursor: pointer; font-weight: bold; }
#done-btn { background: #444; color: white; padding: 8px 16px; border: none; cursor: pointer; }
#metadata { margin-top: 16px; font-size: 12px; opacity: 0.8; }
```

- [ ] **Step 3: Mount static files in web.py**

In `src/clipper/web.py`, before `return app`:
```python
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    web_dir = Path(__file__).parent / "web"
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/")
    def index():
        return FileResponse(web_dir / "index.html")
```

- [ ] **Step 4: Smoke-test the static mount**

Add to `tests/test_web_endpoints.py`:
```python
def test_root_serves_index_html(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>VTuber Clipper · Review</title>" in r.text

def test_static_css_served(fixture_work_dir: Path):
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/static/app.css")
    assert r.status_code == 200
    assert "clip-row" in r.text
```

Run: `pytest tests/test_web_endpoints.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/web/ src/clipper/web.py tests/test_web_endpoints.py
git commit -m "feat: index.html + app.css two-pane scaffold, static mount"
```

---

### Task 17: app.js — load clips, render list, click loads detail

**Files:**
- Create: `src/clipper/web/app.js`

**XSS note:** Clip titles come from the LLM ranker, which is not strictly trusted input. Use `textContent` and DOM construction (`createElement`, `appendChild`, `replaceChildren`) — never `innerHTML` — when rendering any field that comes from `/api/clips`.

- [ ] **Step 1: Write app.js**

`src/clipper/web/app.js`:
```javascript
const state = {
  clips: [],
  selectedId: null,
  transcript: [],
  saveTimer: null,
};

async function loadClips() {
  const r = await fetch("/api/clips");
  state.clips = await r.json();
  renderTopbar();
  renderList();
  if (state.clips.length) selectClip(state.clips[0].id);
}

function renderTopbar() {
  const kept = state.clips.filter(c => c.kept).length;
  document.getElementById("vod-label").textContent = `${state.clips.length} clips`;
  document.getElementById("kept-summary").textContent = `${kept} kept`;
}

function renderList() {
  const list = document.getElementById("clip-list");
  list.replaceChildren();
  state.clips.forEach((c, i) => {
    const row = document.createElement("div");
    row.className = "clip-row"
      + (c.id === state.selectedId ? " selected" : "")
      + (c.kept ? " kept" : " dropped");
    row.dataset.clipId = c.id;

    const titleDiv = document.createElement("div");
    titleDiv.className = "title";
    titleDiv.textContent = `${String(i + 1).padStart(2, "0")} · ${c.title}`;

    const metaDiv = document.createElement("div");
    metaDiv.className = "meta";
    metaDiv.textContent = `★${c.score} · ${(c.t_end - c.t_start).toFixed(1)}s`;

    row.appendChild(titleDiv);
    row.appendChild(metaDiv);
    row.addEventListener("click", () => selectClip(c.id));
    list.appendChild(row);
  });
}

async function selectClip(id) {
  state.selectedId = id;
  renderList();
  const clip = state.clips.find(c => c.id === id);
  document.getElementById("title-input").value = clip.title;
  document.getElementById("t-start-input").value = clip.t_start.toFixed(3);
  document.getElementById("t-end-input").value = clip.t_end.toFixed(3);
  document.getElementById("caption-mode").value = clip.caption_mode;

  const meta = document.getElementById("metadata");
  meta.replaceChildren();
  const ln1 = document.createElement("div");
  ln1.textContent = `Score: ${clip.score} · Hook: ${clip.hook_quality}`;
  const ln2 = document.createElement("div");
  ln2.textContent = `Reason: ${clip.reason}`;
  const ln3 = document.createElement("div");
  ln3.textContent = `Emotes: ${(clip.top_emotes || []).join(" ")}`;
  meta.appendChild(ln1);
  meta.appendChild(ln2);
  meta.appendChild(ln3);

  const player = document.getElementById("player");
  player.src = `/api/clips/${id}/preview.mp4`;
  const tr = await fetch(`/api/clips/${id}/transcript`).then(r => r.json());
  state.transcript = tr.map(w => ({
    word: w.word,
    start: w.start - clip.t_start,
    end: w.end - clip.t_start,
  }));
}

async function patchClip(patch) {
  const r = await fetch(`/api/clips/${state.selectedId}`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(patch),
  });
  if (!r.ok) return;
  const updated = await r.json();
  const idx = state.clips.findIndex(c => c.id === updated.id);
  state.clips[idx] = updated;
  renderList();
  renderTopbar();
}

function debouncedPatch(patch) {
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => patchClip(patch), 400);
}

document.getElementById("title-input").addEventListener("input", e => {
  debouncedPatch({title: e.target.value});
});
document.getElementById("caption-mode").addEventListener("change", e => {
  patchClip({caption_mode: e.target.value});
});
document.getElementById("keep-btn").addEventListener("click", () => patchClip({kept: true}));
document.getElementById("drop-btn").addEventListener("click", () => patchClip({kept: false}));
document.getElementById("t-start-input").addEventListener("change", e => {
  patchClip({t_start: parseFloat(e.target.value)});
});
document.getElementById("t-end-input").addEventListener("change", e => {
  patchClip({t_end: parseFloat(e.target.value)});
});

const player = document.getElementById("player");
const overlay = document.getElementById("captions-overlay");
player.addEventListener("timeupdate", () => {
  const t = player.currentTime;
  const active = state.transcript.find(w => w.start <= t && t < w.end);
  overlay.textContent = active ? active.word : "";
  overlay.style.top = "70%";
});

document.getElementById("finalize-btn").addEventListener("click", async () => {
  const r = await fetch("/api/finalize", {method: "POST"});
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  const progressDiv = document.getElementById("finalize-progress");
  while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value);
    for (const line of chunk.split("\n")) {
      if (line.startsWith("data:")) {
        const evt = JSON.parse(line.slice(5).trim());
        progressDiv.textContent = JSON.stringify(evt);
      }
    }
  }
});

document.getElementById("done-btn").addEventListener("click", async () => {
  await fetch("/api/shutdown", {method: "POST"});
  document.body.replaceChildren();
  const h = document.createElement("h1");
  h.style.padding = "32px";
  h.textContent = "Done. You can close this tab.";
  document.body.appendChild(h);
});

document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  const currentIdx = state.clips.findIndex(c => c.id === state.selectedId);
  if (e.key === "j" || e.key === "ArrowDown") {
    if (currentIdx < state.clips.length - 1) selectClip(state.clips[currentIdx + 1].id);
    e.preventDefault();
  } else if (e.key === "k" || e.key === "ArrowUp") {
    if (currentIdx > 0) selectClip(state.clips[currentIdx - 1].id);
    e.preventDefault();
  } else if (e.key === "y") {
    patchClip({kept: true});
  } else if (e.key === "n") {
    patchClip({kept: false});
  } else if (e.key === " ") {
    player.paused ? player.play() : player.pause();
    e.preventDefault();
  }
});

loadClips();
```

- [ ] **Step 2: Manual smoke**

Start the server against a prepared work dir (run `preview_export` first), open the browser, click around. Expected: page loads, list shows 3 clips, click selects, title edits persist, keep/drop updates.

- [ ] **Step 3: Commit**

```bash
git add src/clipper/web/app.js
git commit -m "feat: frontend app.js with safe textContent rendering, SSE finalize, keyboard"
```

---

## Phase 7 — CLI Integration

### Task 18: clipper CLI with run / review / finalize subcommands

**Files:**
- Create: `src/clipper/main.py`
- Create: `tests/test_main.py`

- [ ] **Step 1: Write failing test (CLI smoke)**

`tests/test_main.py`:
```python
from click.testing import CliRunner
from clipper.main import cli

def test_cli_help_works():
    res = CliRunner().invoke(cli, ["--help"])
    assert res.exit_code == 0
    assert "review" in res.output
    assert "finalize" in res.output

def test_finalize_subcommand_runs_headlessly(fixture_work_dir, fixture_out_dir):
    from clipper.web import build_app
    from fastapi.testclient import TestClient
    from clipper.preview_export import preview_export
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    client.put("/api/clips/c002", json={"kept": False})
    client.put("/api/clips/c003", json={"kept": False})

    res = CliRunner().invoke(cli, [
        "finalize",
        "--work-dir", str(fixture_work_dir),
        "--out-dir", str(fixture_out_dir),
    ])
    assert res.exit_code == 0, res.output
    assert (fixture_out_dir / "final" / "manifest.json").exists()
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_main.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement main.py**

`src/clipper/main.py`:
```python
import json
import webbrowser
from pathlib import Path

import click
import uvicorn

from clipper.finalize import finalize as finalize_call
from clipper.preview_export import preview_export
from clipper.util.logging import get_logger
from clipper.util.ports import find_free_port
from clipper.web import build_app

logger = get_logger(__name__)


@click.group()
def cli() -> None:
    """VTuber Clipper — pipeline + review UI."""


def _serve(work_dir: Path, out_root: Path, port: int) -> None:
    app = build_app(work_dir, out_root=out_root)
    server_info = {
        "port": port,
        "url": f"http://localhost:{port}",
        "vod_id": work_dir.name,
        "pid": __import__("os").getpid(),
    }
    (work_dir / "server.json").write_text(json.dumps(server_info))
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


@cli.command()
@click.argument("url")
@click.option("--work-root", default="work", type=click.Path(path_type=Path))
@click.option("--out-root", default="out", type=click.Path(path_type=Path))
@click.option("--no-review", is_flag=True, help="Skip launching review UI; run upstream + preview only.")
def run(url: str, work_root: Path, out_root: Path, no_review: bool) -> None:
    """Run the full pipeline for a Twitch VOD URL. Upstream stages NOT implemented in Plan A."""
    raise click.ClickException(
        "Upstream pipeline (download/transcribe/rank) is out of scope for Plan A. "
        "Use `clipper review <vod_id>` against a manually-prepared work dir, "
        "or build M1-M4 first."
    )


@cli.command()
@click.argument("vod_id")
@click.option("--work-root", default="work", type=click.Path(path_type=Path))
@click.option("--out-root", default="out", type=click.Path(path_type=Path))
def review(vod_id: str, work_root: Path, out_root: Path) -> None:
    """Open the review UI for an already-processed VOD."""
    work_dir = work_root / vod_id
    if not (work_dir / "ranked.json").exists():
        raise click.ClickException(f"No ranked.json in {work_dir}")
    preview_export(work_dir)
    port = find_free_port()
    url = f"http://localhost:{port}"
    logger.info(f"Opening {url}")
    webbrowser.open(url)
    _serve(work_dir, out_root / vod_id, port)


@cli.command()
@click.option("--work-dir", required=True, type=click.Path(path_type=Path, exists=True))
@click.option("--out-dir", required=True, type=click.Path(path_type=Path))
def finalize(work_dir: Path, out_dir: Path) -> None:
    """Headless finalize using the latest review_state.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = finalize_call(work_dir, out_dir)
    click.echo(f"Wrote {manifest}")


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/test_main.py -v`
Expected: 2 pass.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/main.py tests/test_main.py
git commit -m "feat: clipper CLI with run/review/finalize subcommands"
```

---

## Phase 8 — Polish

### Task 19: Idle-timeout shutdown for the server

**Files:**
- Modify: `src/clipper/web.py`
- Modify: `src/clipper/main.py`
- Modify: `tests/test_web_endpoints.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_web_endpoints.py`:
```python
import time

def test_idle_tracker_updates_on_request(fixture_work_dir: Path):
    app = build_app(fixture_work_dir)
    before = app.state.last_request_at
    time.sleep(0.01)
    TestClient(app).get("/api/clips")
    assert app.state.last_request_at > before
```

- [ ] **Step 2: Implement activity tracker in web.py**

In `src/clipper/web.py`, after `app.state.should_exit = False`, add:
```python
    import time as _time
    app.state.last_request_at = _time.monotonic()

    @app.middleware("http")
    async def track_activity(request, call_next):
        app.state.last_request_at = _time.monotonic()
        return await call_next(request)
```

- [ ] **Step 3: Wire idle-watcher in main.py**

Replace `_serve()` in `src/clipper/main.py`:
```python
def _serve(work_dir: Path, out_root: Path, port: int, idle_timeout_s: int = 1800) -> None:
    import asyncio, time
    app = build_app(work_dir, out_root=out_root)
    server_info = {
        "port": port,
        "url": f"http://localhost:{port}",
        "vod_id": work_dir.name,
        "pid": __import__("os").getpid(),
    }
    (work_dir / "server.json").write_text(json.dumps(server_info))

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    async def watcher():
        while not server.started:
            await asyncio.sleep(0.1)
        while True:
            await asyncio.sleep(5)
            if app.state.should_exit:
                server.should_exit = True
                return
            idle = time.monotonic() - app.state.last_request_at
            if idle > idle_timeout_s:
                logger.info(f"Idle {idle:.0f}s — shutting down")
                server.should_exit = True
                return

    async def main_loop():
        await asyncio.gather(server.serve(), watcher())

    asyncio.run(main_loop())
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/test_web_endpoints.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/web.py src/clipper/main.py tests/test_web_endpoints.py
git commit -m "feat: 30min idle-timeout server shutdown + activity middleware"
```

---

### Task 20: Update docs per interaction-design §13

**Files:**
- Modify: `spec.md`
- Modify: `architecture.md`
- Modify: `MILESTONES.md`
- Modify: `changelog.md`

- [ ] **Step 1: Update spec.md**

Replace the `### 6.9 export.py` section with two new module specs:
- `### 6.9 preview_export.py` — fast 540×960 previews, no captions; cross-references this plan.
- `### 6.10 finalize.py` — full-quality re-encode of kept clips per `review_state.json`; cross-references this plan.

Add new sections after `finalize.py`:
- `### 6.11 captions.py` — SRT generator + basic ASS generator (window3 animated style is Plan B).
- `### 6.12 web.py` — FastAPI server, endpoints listed in interaction-design §3.
- `### 6.13 effects/` — Protocol only; concrete effects ship in Plan B.

Renumber existing `main.py` and config sections.

In §7 config, append:
```toml
[finalize]
caption_style = "basic"        # Plan B adds: window3 | single | karaoke | stacked2
caption_mode = "burned"        # burned | clean | both
server_port_start = 8765
server_port_end = 8800
idle_timeout_seconds = 1800
```

In §8 acceptance criteria, add:
> 9. `clipper review <vod_id>` launches the browser-based two-pane review UI; edits (title, trim, kept, caption_mode) persist to `review_state.json` and survive server restart.
> 10. Clicking Finalize re-encodes only kept clips to `out/<vod_id>/final/` with a manifest.

- [ ] **Step 2: Update architecture.md**

In §2 system diagram, replace the final-render arrow with:
```
preview_export → web (FastAPI + browser) → finalize → out/<vod>/final/
```

In §3 module table, replace the `export.py` row with `preview_export.py` and add rows for `finalize.py`, `captions.py`, `web.py`, `effects/`.

Add new §11 "Web layer":
- Localhost-only FastAPI + uvicorn
- Endpoints: full list from interaction-design §3
- Range requests for video streaming
- SSE for finalize progress
- review_state.json round-trip
- Idle-timeout server shutdown

In §6 idempotency model, add: `finalize` is driven by `review_state.json` rather than config-hash since user intent is the input.

- [ ] **Step 3: Update MILESTONES.md**

Rescope M5: "Preview export (fast 540×960, no captions, static crop)". Drop the "first watchable clips" framing — those land in M5.5.

Insert new M5.5 before M6:

```markdown
## M5.5 — Review UI + Finalize (Plan A scope)

**Goal:** User runs `clipper review <vod_id>`, reviews clips in a browser, clicks Finalize, gets full-quality captioned MP4s.

**Deliverables**
- `web.py` (FastAPI + uvicorn server)
- `index.html`, `app.css`, `app.js` (two-pane review UI)
- `review_state.json` round-trip via PUT
- `captions.py` with basic (non-animated) ASS + SRT generation
- `finalize.py` with burned/clean/both caption modes
- CLI: `clipper review`, `clipper finalize`
- SSE progress stream for finalize
- Idle-timeout (30 min) server shutdown

**Validation**
- Manually prepare `work/<vod>/` with synthetic ranked.json + transcript.json + video.mp4
- `clipper review <vod_id>` opens the browser
- Edit titles, drop two clips, click Finalize
- `out/<vod>/final/` contains the right MP4s and manifest

**Effort:** 1-2 sessions.

**Note:** Animated captions and motion-graphics effects are deferred to a separate plan (Plan B).
```

Update M6 (face tracking) to clarify: dynamic per-frame crop applies to `finalize.py`, not `preview_export.py`.

- [ ] **Step 4: Update changelog.md**

Under `## [Unreleased]`, add to **Planning**:
- `plan-a-interaction.md` — implementation plan for the core review pipeline + finalize

Add to **Decisions**:
- **2026-05-11** — Plan A (core review pipeline + plain captions) and Plan B (animated captions + 4 motion effects) split. Plan A ships first as an independently-useful v0.5.

- [ ] **Step 5: Commit doc updates**

```bash
git add spec.md architecture.md MILESTONES.md changelog.md
git commit -m "docs: update spec/architecture/milestones/changelog for Plan A scope"
```

---

### Task 21: README how-to-run

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write README content**

Replace `README.md`:
```markdown
# VTuber Clipper

Local tool that ingests a Twitch VTuber VOD and produces 10-20 9:16 short-form clips
with burned-in captions. Pipeline runs end-to-end on a single PC; no paid APIs.

## Status: Plan A in progress

- Spec: `spec.md`
- Architecture: `architecture.md`
- Research notes & env setup: `research.md`
- Milestones: `MILESTONES.md`
- Interaction design: `interaction-design.md`
- Implementation plan (current): `plan-a-interaction.md`

## Quick start (Plan A only)

Prereqs: see `research.md` §1.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
pytest
```

Plan A covers the review-and-finalize layer. The upstream pipeline (download/
transcribe/rank) isn't built yet — use `tests/fixtures/` to develop and test the
review UI in isolation, or wait for Plan B / M1-M4.

```powershell
# Open the review UI for a manually-prepared work directory:
clipper review <vod_id>

# Headless finalize using the latest review_state.json:
clipper finalize --work-dir work/<vod_id> --out-dir out/<vod_id>
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with Plan A status and quick-start"
```

---

## Self-Review Summary

After completing all 22 tasks (21 numbered + Task 5.5):
- All `interaction-design.md` §16 acceptance criteria 1-8 and 10 are covered (effects-related #9 deferred to Plan B).
- Every code step shows actual code; no placeholders.
- Type names consistent: `ClipState`, `ClipUpdate`, `FinalizeEffect`, `AssBuilder`, `EncodeProfile` used identically across files.
- Test coverage: ~30 test cases across 10 test files covering happy paths, idempotency, range requests, three caption modes, state persistence, CLI surface, and the shared util helpers.
- Frontend uses `textContent` + DOM construction; no `innerHTML` with user-flowed content.
- **Zero duplicated ffmpeg invocations** — `preview_export.py` and `finalize.py` both call `encode_clip(..., PREVIEW)` and `encode_clip(..., FINAL)` respectively, with optional `subtitles_path` and `extra_filters`. Plan B effects extend through `extra_filters` rather than re-building the command from scratch.
- **Zero duplicated transcript windowing** — `web.py` and `finalize.py` both use `words_in_window()`.
- **Zero duplicated JSON I/O** — `read_json` / `write_json` from `util/json_io.py` everywhere.

## What's left for Plan B

The foundation makes Plan B significantly smaller:
- `captions.py` window3 / single / karaoke / stacked2 animated styles — each is a new function using the existing `AssBuilder` class (just different `add_dialogue` patterns with `\t` and `\k` tags)
- `effects/punch_zoom.py`, `effects/emoji_burst.py`, `effects/hook_card.py`, `effects/reaction_zoom.py` — each plugs into `finalize.py` via the `extra_filters` arg on `encode_clip()` or by composing into a shared `AssBuilder`
- Effect-application loop in `finalize.py` — iterates effects, lets each mutate a filter list and AssBuilder, single `encode_clip` call at the end
- UI checkboxes + per-clip effect overrides
- Twemoji font bundling
- ASS `\t` animation testing on the target ffmpeg build
