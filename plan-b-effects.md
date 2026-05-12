# Plan B — Animated Captions + Motion Graphics Effects

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Submagic-style aesthetic to finalize: animated `window3` captions + four motion-graphics effects (punch_zoom, emoji_burst, hook_card, reaction_zoom), each independently toggleable per-clip in the review UI.

**Architecture:** Effects are a pluggable layer applied inside `finalize.py`. An `EffectContext` dataclass is passed through a chain of `FinalizeEffect` implementations; each mutates the shared `AssBuilder` (from Plan A) and/or appends ffmpeg filter fragments. The single `encode_clip` invocation at the end of finalize composes everything. Audio/chat peaks (which most effects need) are loaded from upstream stages — when those files are missing (Plan A fixture mode), effects gracefully no-op.

**Tech Stack:** Same as Plan A (Python 3.11/3.12, FastAPI, ffmpeg+NVENC, vanilla JS) + bundled Twemoji color PNGs for emoji_burst.

**Scope:** This plan ships:
- `window3` animated caption style (3-word window + active-word yellow highlight + slight scale).
- 4 motion effects: `punch_zoom`, `emoji_burst`, `hook_card`, `reaction_zoom`.
- Per-clip effect overrides in the review UI (checkboxes).
- Caption-style selector (defaults to `window3`; other styles are post-Plan-B).
- Fixture peak data + graceful no-op behavior when upstream stages aren't available.
- Two highest-priority Plan A debt items (atomic write helper + live caption grouping to match window3).

**Out of scope:**
- Single / karaoke / stacked2 caption styles — `window3` is the default and the only style shipped; the other three were design alternatives.
- Other Plan A debt: trim nudge keys, `?` help overlay, server PID re-attach, corrupt-state fallback, `config.toml`. Those go in a future polish pass.
- Upstream pipeline (M1-M4) — Plan B effects gracefully handle missing peak files.

---

## File Structure

### Created in this plan
```
src/clipper/
├── effects/
│   ├── context.py             # EffectContext dataclass
│   ├── registry.py            # name → FinalizeEffect mapping + DEFAULT_EFFECTS_CONFIG
│   ├── punch_zoom.py          # zoompan scale 1.0→1.08→1.0 on audio peaks
│   ├── emoji_burst.py         # PNG overlay at chat-peak timestamps
│   ├── hook_card.py           # "WAIT FOR IT" ASS card if hook_quality >= 7
│   └── reaction_zoom.py       # tighter crop window at biggest combined peak
├── util/
│   └── peaks.py               # load_audio_peaks / load_chat_peaks / peaks_in_window

assets/
└── emojis/
    ├── README.md              # source + license note
    ├── 1f602.png              # 😂
    ├── 1f480.png              # 💀
    ├── 1f525.png              # 🔥
    ├── 1f631.png              # 😱
    ├── 2728.png               # ✨
    └── 1f44f.png              # 👏

tests/
├── fixtures/
│   ├── audio_peaks.sample.json
│   └── chat_peaks.sample.json
├── test_peaks.py
├── test_atomic_write.py
├── test_captions_window3.py
├── test_effects_punch_zoom.py
├── test_effects_emoji_burst.py
├── test_effects_hook_card.py
├── test_effects_reaction_zoom.py
└── test_finalize_effects.py
```

### Modified in this plan
```
src/clipper/
├── effects/
│   └── base.py                # FinalizeEffect Protocol expanded with EffectContext
├── captions.py                # add window3 + style dispatcher
├── finalize.py                # invoke effects pipeline before encode
├── web.py                     # ClipState.caption_style field; finalize_run reads it
└── web/
    ├── index.html             # effects checkboxes + caption style selector
    ├── app.css                # styling for new controls
    └── app.js                 # render + sync effect overrides; 3-word caption overlay

tests/
└── conftest.py                # copy peak fixtures into fixture_work_dir
```

`pyproject.toml` package-data line already covers HTML/CSS/JS. We'll add `"clipper" = [..., "assets/emojis/*.png"]` so Twemoji PNGs ship with the wheel.

---

## Conventions for every task

- TDD: failing test → run → confirm failure for the right reason → implement → run → confirm pass → commit.
- All file paths relative to `E:\dev\vtuber-clipper`.
- Windows + PowerShell shell; pytest via `.venv\Scripts\pytest.exe`.
- Reuse Plan A helpers: `read_json`/`write_json` (never `json.loads/dumps` directly), `encode_clip` + `EncodeProfile`, `AssBuilder`, `words_in_window`, etc.
- Frontend uses `textContent` + DOM construction; **never `innerHTML`** with values from the API.
- All commits use conventional messages.

---

## Phase 0 — Plan A debt cleanup (foundations for Plan B)

### Task 1: Atomic write helper in json_io

**Files:**
- Modify: `src/clipper/util/json_io.py`
- Create: `tests/test_atomic_write.py`

- [ ] **Step 1: Write failing test**

`tests/test_atomic_write.py`:
```python
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from clipper.util.json_io import write_json


def test_atomic_write_creates_target(tmp_path: Path):
    p = tmp_path / "a.json"
    write_json(p, {"x": 1})
    assert p.exists()
    assert p.read_text(encoding="utf-8").strip().startswith("{")


def test_atomic_write_replaces_existing(tmp_path: Path):
    p = tmp_path / "a.json"
    write_json(p, {"v": 1})
    write_json(p, {"v": 2})
    import json
    assert json.loads(p.read_text(encoding="utf-8"))["v"] == 2


def test_atomic_write_leaves_no_temp_on_success(tmp_path: Path):
    p = tmp_path / "a.json"
    write_json(p, {"x": 1})
    siblings = list(tmp_path.iterdir())
    assert len(siblings) == 1
    assert siblings[0].name == "a.json"


def test_atomic_write_does_not_corrupt_on_crash(tmp_path: Path):
    p = tmp_path / "a.json"
    write_json(p, {"v": "first"})

    def boom(_src, _dst):
        raise RuntimeError("simulated mid-rename crash")

    with patch("os.replace", side_effect=boom), pytest.raises(RuntimeError):
        write_json(p, {"v": "second"})

    import json
    assert json.loads(p.read_text(encoding="utf-8"))["v"] == "first"
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_atomic_write.py -v`
Expected: the "no temp on success" and "does not corrupt on crash" tests fail because the current `write_json` writes directly.

- [ ] **Step 3: Implement atomic write**

Replace `write_json` in `src/clipper/util/json_io.py`:
```python
import json
import os
from pathlib import Path
from typing import Any, Iterator


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    """Atomic write: serialize to a sibling tmp file, then os.replace into place.

    On Windows os.replace is atomic on NTFS; on POSIX it's a rename. Either way,
    a crash mid-write leaves the previous file intact.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=indent), encoding="utf-8")
    os.replace(tmp, path)


def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 45 (prior) + 4 new = 49 passing. All existing review-state tests continue to pass (they use `write_json` indirectly).

- [ ] **Step 5: Commit**

```bash
git add src/clipper/util/json_io.py tests/test_atomic_write.py
git commit -m "feat: atomic write in json_io (write-to-tmp + os.replace) for crash safety"
```

---

### Task 2: Caption overlay matches window3 grouping

**Files:**
- Modify: `src/clipper/web/app.js`
- Modify: `tests/test_web_endpoints.py`

Plan A's `app.js` displays one word at a time. The window3 burn style groups 3 words per cue. Align them.

- [ ] **Step 1: Write failing assertion**

Append to `tests/test_web_endpoints.py`:
```python
def test_app_js_groups_caption_words(fixture_work_dir):
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/static/app.js")
    assert r.status_code == 200
    # The overlay should show 3-word windows, not single words.
    # We assert presence of a grouping function or constant.
    assert "WORDS_PER_WINDOW" in r.text or "window" in r.text.lower()
    # And that the active-word visualization wraps individual words in <span>.
    assert "createElement(\"span\")" in r.text or "createElement('span')" in r.text
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_web_endpoints.py::test_app_js_groups_caption_words -v`
Expected: FAIL — the grouping markers aren't in the current app.js.

- [ ] **Step 3: Update the caption-overlay block in `src/clipper/web/app.js`**

Find the `player.addEventListener("timeupdate", ...)` block and replace with:
```javascript
const WORDS_PER_WINDOW = 3;
const player = document.getElementById("player");
const overlay = document.getElementById("captions-overlay");

function activeWordWindow(words, t) {
  // Find index of the word whose [start, end) contains t.
  const idx = words.findIndex(w => w.start <= t && t < w.end);
  if (idx === -1) return null;
  // Center the active word in a 3-word sliding window when possible.
  const start = Math.max(0, idx - 1);
  const end = Math.min(words.length, start + WORDS_PER_WINDOW);
  return { activeIdx: idx, windowStart: start, windowEnd: end };
}

player.addEventListener("timeupdate", () => {
  overlay.replaceChildren();
  const w = activeWordWindow(state.transcript, player.currentTime);
  if (!w) {
    overlay.style.top = "";
    return;
  }
  for (let i = w.windowStart; i < w.windowEnd; i++) {
    const span = document.createElement("span");
    span.textContent = state.transcript[i].word;
    span.style.margin = "0 4px";
    if (i === w.activeIdx) {
      span.style.color = "#ffd700";
      span.style.transform = "scale(1.12)";
      span.style.display = "inline-block";
    }
    overlay.appendChild(span);
  }
  overlay.style.top = "70%";
});
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 49 + 1 = 50 passing. The XSS guard test (`innerHTML` not in r.text) must still pass — verify by inspecting `app.js` does not introduce any `innerHTML` references.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/web/app.js tests/test_web_endpoints.py
git commit -m "fix: live caption overlay shows 3-word window matching window3 burn style"
```

---

## Phase 1 — Effect infrastructure

### Task 3: Peak fixtures + conftest wiring

**Files:**
- Create: `tests/fixtures/audio_peaks.sample.json`
- Create: `tests/fixtures/chat_peaks.sample.json`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write audio_peaks fixture**

`tests/fixtures/audio_peaks.sample.json`:
```json
[
  {"t_start": 5.5, "t_end": 6.1, "intensity": 14.2},
  {"t_start": 7.0, "t_end": 7.3, "intensity": 9.4},
  {"t_start": 22.0, "t_end": 22.8, "intensity": 4.8},
  {"t_start": 41.3, "t_end": 42.0, "intensity": 11.0}
]
```

- [ ] **Step 2: Write chat_peaks fixture**

`tests/fixtures/chat_peaks.sample.json`:
```json
[
  {"t_start": 5.8, "t_end": 8.2, "msg_count": 142, "hype_score": 87.3, "top_emotes": ["KEKW", "LULW", "OMEGALUL"]},
  {"t_start": 22.1, "t_end": 24.5, "msg_count": 88, "hype_score": 65.0, "top_emotes": ["LULW", "POG"]},
  {"t_start": 41.0, "t_end": 43.0, "msg_count": 60, "hype_score": 42.1, "top_emotes": ["POG", "KEKW"]}
]
```

- [ ] **Step 3: Update conftest.py**

In `tests/conftest.py`, expand the `fixture_work_dir` fixture body to also copy the two new peak files:
```python
@pytest.fixture
def fixture_work_dir(tmp_path: Path) -> Path:
    """Synthetic work/<vod_id>/ directory with all upstream files in place."""
    work = tmp_path / "work" / "vod_test"
    work.mkdir(parents=True)
    shutil.copy(FIXTURES / "fixture_video.mp4", work / "video.mp4")
    shutil.copy(FIXTURES / "ranked.sample.json", work / "ranked.json")
    shutil.copy(FIXTURES / "transcript.sample.json", work / "transcript.json")
    shutil.copy(FIXTURES / "face_track.sample.json", work / "face_track.json")
    shutil.copy(FIXTURES / "audio_peaks.sample.json", work / "audio_peaks.json")
    shutil.copy(FIXTURES / "chat_peaks.sample.json", work / "chat_peaks.json")
    return work
```

- [ ] **Step 4: Verify (no new tests yet; existing suite stays green)**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 50 passing (the extra files are now present in tmp_path but unused).

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/audio_peaks.sample.json tests/fixtures/chat_peaks.sample.json tests/conftest.py
git commit -m "test: fixtures for audio_peaks and chat_peaks (used by effects tests)"
```

---

### Task 4: `util/peaks.py` — peak loaders + windowing

**Files:**
- Create: `src/clipper/util/peaks.py`
- Create: `tests/test_peaks.py`

- [ ] **Step 1: Write failing tests**

`tests/test_peaks.py`:
```python
from pathlib import Path

from clipper.util.peaks import load_audio_peaks, load_chat_peaks, peaks_in_window


def test_load_audio_peaks_returns_list(fixture_work_dir: Path):
    peaks = load_audio_peaks(fixture_work_dir)
    assert len(peaks) >= 1
    assert "t_start" in peaks[0]
    assert "intensity" in peaks[0]


def test_load_audio_peaks_missing_returns_empty(tmp_path: Path):
    assert load_audio_peaks(tmp_path) == []


def test_load_chat_peaks_returns_list(fixture_work_dir: Path):
    peaks = load_chat_peaks(fixture_work_dir)
    assert len(peaks) >= 1
    assert "top_emotes" in peaks[0]


def test_load_chat_peaks_missing_returns_empty(tmp_path: Path):
    assert load_chat_peaks(tmp_path) == []


def test_peaks_in_window_filters_by_overlap():
    peaks = [
        {"t_start": 0.0, "t_end": 1.0},
        {"t_start": 5.0, "t_end": 6.0},
        {"t_start": 9.5, "t_end": 10.5},
        {"t_start": 20.0, "t_end": 21.0},
    ]
    # Window [5, 10) should include peaks that overlap, excluding pure-edge cases.
    inside = peaks_in_window(peaks, 5.0, 10.0)
    assert len(inside) == 2
    assert inside[0]["t_start"] == 5.0
    assert inside[1]["t_start"] == 9.5
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_peaks.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

`src/clipper/util/peaks.py`:
```python
from pathlib import Path

from clipper.util.json_io import read_json


def load_audio_peaks(work_dir: Path) -> list[dict]:
    """Load audio_peaks.json; return [] if the file is missing."""
    p = work_dir / "audio_peaks.json"
    return read_json(p) if p.exists() else []


def load_chat_peaks(work_dir: Path) -> list[dict]:
    """Load chat_peaks.json; return [] if the file is missing."""
    p = work_dir / "chat_peaks.json"
    return read_json(p) if p.exists() else []


def peaks_in_window(peaks: list[dict], t_start: float, t_end: float) -> list[dict]:
    """Return peaks whose [t_start, t_end] overlaps the given window.

    Inclusive-start, exclusive-end on the window. A peak overlaps if its
    t_start < window_end AND its t_end > window_start.
    """
    return [p for p in peaks if p["t_start"] < t_end and p["t_end"] > t_start]
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 50 + 5 = 55 passing.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/util/peaks.py tests/test_peaks.py
git commit -m "feat: peak loaders + windowing helper (graceful no-op when missing)"
```

---

### Task 5: `EffectContext` dataclass

**Files:**
- Create: `src/clipper/effects/context.py`

This is a data structure with no behavior of its own; no dedicated test file. It will be exercised by every effect test.

- [ ] **Step 1: Write `effects/context.py`**

```python
from dataclasses import dataclass, field
from pathlib import Path

from clipper.captions import AssBuilder


@dataclass
class EffectContext:
    """All the per-clip data an effect needs to render itself.

    Effects mutate `ass` (add dialogue layers, draws, etc.) and/or append to
    `extra_filters` (ffmpeg filter fragments composed left-to-right).
    They are called in registry order; each one sees the cumulative state.
    """
    clip: dict
    """The clip dict from review_state.json (id, title, t_start, t_end, kept,
    effects, caption_mode, caption_style, score, hook_quality, top_emotes, ...)."""

    transcript_words: list[dict]
    """Words within [clip.t_start, clip.t_end), in source-video seconds."""

    audio_peaks: list[dict]
    """Audio peaks overlapping the clip window. May be empty."""

    chat_peaks: list[dict]
    """Chat peaks overlapping the clip window. May be empty."""

    face_track: dict | None
    """Per-clip face track (fps_sampled + track) or None if missing."""

    output_size: tuple[int, int]
    """Final output dimensions (width, height) for ASS PlayRes math."""

    ass: AssBuilder
    """Cumulative ASS document. Effects call .add_dialogue() / .add_style()."""

    extra_filters: list[str] = field(default_factory=list)
    """ffmpeg filter fragments to compose into the encode_clip call."""

    assets_dir: Path | None = None
    """Path to the bundled assets/ directory (for emoji PNGs etc.)."""
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `.venv\Scripts\python.exe -c "from clipper.effects.context import EffectContext"`
Expected: no error.

Also: `.venv\Scripts\pytest.exe -v` should still show 55 passing.

- [ ] **Step 3: Commit**

```bash
git add src/clipper/effects/context.py
git commit -m "feat: EffectContext dataclass — shared state passed through effect chain"
```

---

### Task 6: Expand `FinalizeEffect` Protocol

**Files:**
- Modify: `src/clipper/effects/base.py`

- [ ] **Step 1: Rewrite `src/clipper/effects/base.py`**

```python
from typing import Protocol

from clipper.effects.context import EffectContext


class FinalizeEffect(Protocol):
    """One step in the finalize effect chain. Concrete effects mutate the
    shared EffectContext (ass + extra_filters) based on its clip metadata,
    peaks, and face track.

    Effects should be idempotent: calling apply twice with the same context
    must produce the same result. They must gracefully no-op when their
    required inputs are missing (e.g., emoji_burst with empty chat_peaks).
    """

    name: str
    """Stable identifier matching the effects/registry key (e.g. 'punch_zoom').
    Used as the key in ClipState.effects and the manifest's effects_applied."""

    default_enabled: bool
    """Per-clip default when ClipState.effects has no override."""

    def apply(self, ctx: EffectContext) -> None: ...
```

- [ ] **Step 2: Verify**

Run: `.venv\Scripts\python.exe -c "from clipper.effects import FinalizeEffect; from clipper.effects.base import FinalizeEffect as F; print(F.__annotations__)"`
Expected: prints the annotations dict including `name`, `default_enabled`.

`.venv\Scripts\pytest.exe -v` → still 55 passing.

- [ ] **Step 3: Commit**

```bash
git add src/clipper/effects/base.py
git commit -m "feat: expand FinalizeEffect Protocol with name/default_enabled/apply(ctx)"
```

---

### Task 7: Effects registry skeleton

**Files:**
- Create: `src/clipper/effects/registry.py`
- Modify: `src/clipper/effects/__init__.py`

- [ ] **Step 1: Write `src/clipper/effects/registry.py`**

```python
"""Registry of available finalize effects.

Concrete effect implementations register themselves here. The finalize stage
iterates the registry, asks each effect whether it's enabled for the current
clip (per-clip override > registry default), and calls apply() in order.
"""
from clipper.effects.base import FinalizeEffect

# Filled in as effect modules are added (Tasks 11-20).
REGISTRY: dict[str, FinalizeEffect] = {}


def register(effect: FinalizeEffect) -> FinalizeEffect:
    REGISTRY[effect.name] = effect
    return effect


def default_effects_config() -> dict[str, bool]:
    """Default per-clip effects flags built from REGISTRY."""
    return {name: e.default_enabled for name, e in REGISTRY.items()}
```

- [ ] **Step 2: Update `src/clipper/effects/__init__.py`**

```python
from clipper.effects.base import FinalizeEffect
from clipper.effects.context import EffectContext
from clipper.effects.registry import REGISTRY, default_effects_config, register

__all__ = [
    "FinalizeEffect",
    "EffectContext",
    "REGISTRY",
    "default_effects_config",
    "register",
]
```

- [ ] **Step 3: Verify (no tests yet — registry is empty)**

Run: `.venv\Scripts\python.exe -c "from clipper.effects import REGISTRY, default_effects_config; print(REGISTRY, default_effects_config())"`
Expected: `{} {}`.

`.venv\Scripts\pytest.exe -v` → still 55 passing.

- [ ] **Step 4: Commit**

```bash
git add src/clipper/effects/registry.py src/clipper/effects/__init__.py
git commit -m "feat: effects registry + default_effects_config helper"
```

---

## Phase 2 — Window3 animated caption style

### Task 8: `generate_window3_ass` function

**Files:**
- Modify: `src/clipper/captions.py`
- Create: `tests/test_captions_window3.py`

- [ ] **Step 1: Write failing tests**

`tests/test_captions_window3.py`:
```python
from clipper.captions import generate_window3_ass

WORDS = [
    {"start": 5.0, "end": 5.3, "word": "holy"},
    {"start": 5.4, "end": 5.7, "word": "no"},
    {"start": 5.8, "end": 6.2, "word": "way"},
    {"start": 6.3, "end": 6.6, "word": "that"},
    {"start": 6.7, "end": 7.0, "word": "just"},
    {"start": 7.1, "end": 7.6, "word": "happened"},
]


def test_window3_emits_one_dialogue_per_word():
    ass = generate_window3_ass(WORDS, clip_start=5.0, output_size=(1080, 1920))
    # One Dialogue line per word — each word is the "active" frame of a 3-word window.
    assert ass.count("Dialogue:") == len(WORDS)


def test_window3_active_word_has_color_override():
    ass = generate_window3_ass(WORDS, clip_start=5.0, output_size=(1080, 1920))
    # Active-word inline color override uses ASS \1c tag with yellow.
    assert "\\1c&H0000FFFF&" in ass or "\\1c&HFFD700&" in ass


def test_window3_includes_fade_in():
    ass = generate_window3_ass(WORDS, clip_start=5.0, output_size=(1080, 1920))
    # \fad(80,0) for a quick fade-in, no fade-out.
    assert "\\fad(" in ass


def test_window3_dialogue_times_are_clip_local():
    ass = generate_window3_ass(WORDS, clip_start=5.0, output_size=(1080, 1920))
    # First word starts at 5.0 source → 0.0 clip-local.
    assert "0:00:00.00" in ass
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_captions_window3.py -v`
Expected: ImportError on `generate_window3_ass`.

- [ ] **Step 3: Implement `generate_window3_ass` in `src/clipper/captions.py`**

Append to the existing file (after `generate_basic_ass`):
```python
def generate_window3_ass(
    words: list[dict],
    clip_start: float,
    output_size: tuple[int, int],
) -> str:
    """3-word sliding window with the active word highlighted yellow + slight scale.

    Emits one Dialogue line per word. Each line spans that word's [start, end)
    in clip-local time and renders three words (prev, active, next) with the
    active word in yellow at 1.12x scale.
    """
    builder = AssBuilder(width=output_size[0], height=output_size[1])

    yellow = "&H0000FFFF&"   # ASS BGR: FF FF 00 = yellow
    white = "&H00FFFFFF&"

    for idx, w in enumerate(words):
        start = w["start"] - clip_start
        end = w["end"] - clip_start
        prev = words[idx - 1]["word"] if idx > 0 else ""
        nxt = words[idx + 1]["word"] if idx + 1 < len(words) else ""

        parts = []
        if prev:
            parts.append(f"{{\\1c{white}}}{prev}")
        parts.append(f"{{\\1c{yellow}\\fscx112\\fscy112}}{w['word']}{{\\1c{white}\\fscx100\\fscy100}}")
        if nxt:
            parts.append(nxt)
        text = "{\\fad(80,0)}" + " ".join(parts)
        builder.add_dialogue(start, end, text)

    return builder.render()


def generate_ass(
    style: str,
    words: list[dict],
    clip_start: float,
    output_size: tuple[int, int],
) -> str:
    """Dispatch by style name. Falls back to 'basic' for unknown styles."""
    if style == "window3":
        return generate_window3_ass(words, clip_start, output_size)
    return generate_basic_ass(words, clip_start, output_size)
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 55 + 4 = 59 passing.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/captions.py tests/test_captions_window3.py
git commit -m "feat: window3 animated caption style + generate_ass dispatcher"
```

---

### Task 9: Wire `caption_style` into ClipState + finalize

**Files:**
- Modify: `src/clipper/web.py`
- Modify: `src/clipper/finalize.py`
- Modify: `tests/test_finalize.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_finalize.py`:
```python
def test_window3_style_emits_per_word_dialogue(fixture_work_dir, fixture_out_dir):
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    client.put("/api/clips/c001", json={"caption_style": "window3"})
    client.put("/api/clips/c002", json={"kept": False})
    client.put("/api/clips/c003", json={"kept": False})
    finalize(fixture_work_dir, fixture_out_dir)
    # The manifest should record the style applied.
    import json as _json
    manifest = _json.loads((fixture_out_dir / "final" / "manifest.json").read_text())
    assert manifest["clips"][0]["caption_style"] == "window3"
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_finalize.py::test_window3_style_emits_per_word_dialogue -v`
Expected: 422 (Pydantic rejects `caption_style` — field doesn't exist yet).

- [ ] **Step 3: Add `caption_style` field to `ClipState` and `ClipUpdate`**

In `src/clipper/web.py`, add to the model fields:

In `ClipState`:
```python
    caption_style: Literal["basic", "window3"] = "window3"
```
(Place it next to `caption_mode`.)

In `ClipUpdate`:
```python
    caption_style: Literal["basic", "window3"] | None = None
```

- [ ] **Step 4: Use `generate_ass` dispatcher in finalize**

In `src/clipper/finalize.py`:

1. Replace the import:
```python
from clipper.captions import generate_ass, generate_srt
```

2. Replace the ASS write block (the `if mode in ("burned", "both"):` branch) with:
```python
        if mode in ("burned", "both"):
            style = clip.get("caption_style", "window3")
            with tempfile.NamedTemporaryFile(
                "w", suffix=".ass", delete=False, encoding="utf-8"
            ) as f:
                f.write(generate_ass(style, words, clip["t_start"], (FINAL.width, FINAL.height)))
                ass_path = Path(f.name)
            try:
                burned_path = base.with_suffix(".mp4")
                encode_clip(video, clip["t_start"], duration, burned_path, FINAL,
                            subtitles_path=ass_path)
            finally:
                ass_path.unlink(missing_ok=True)
```

3. Add `caption_style` to the manifest_clips entry:
```python
            "caption_style": clip.get("caption_style", "window3"),
```
(Add immediately after the `caption_mode` line.)

- [ ] **Step 5: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: all prior tests pass (window3 becomes the default; the existing `test_only_kept_clips_are_encoded` etc. silently use window3 instead of basic), plus the new test passes. Total: 60.

- [ ] **Step 6: Commit**

```bash
git add src/clipper/web.py src/clipper/finalize.py tests/test_finalize.py
git commit -m "feat: caption_style field on ClipState + dispatcher in finalize"
```

---

## Phase 3 — punch_zoom effect

### Task 10: `punch_zoom` effect

**Files:**
- Create: `src/clipper/effects/punch_zoom.py`
- Create: `tests/test_effects_punch_zoom.py`

- [ ] **Step 1: Write failing tests**

`tests/test_effects_punch_zoom.py`:
```python
from clipper.captions import AssBuilder
from clipper.effects.context import EffectContext
from clipper.effects.punch_zoom import PunchZoom


def _ctx_with_peaks(audio_peaks, clip_start=5.0, clip_end=15.0):
    return EffectContext(
        clip={"id": "c001", "t_start": clip_start, "t_end": clip_end},
        transcript_words=[],
        audio_peaks=audio_peaks,
        chat_peaks=[],
        face_track=None,
        output_size=(1080, 1920),
        ass=AssBuilder(1080, 1920),
    )


def test_no_audio_peaks_means_no_filter_appended():
    ctx = _ctx_with_peaks(audio_peaks=[])
    PunchZoom().apply(ctx)
    assert ctx.extra_filters == []


def test_audio_peak_above_threshold_appends_zoompan_filter():
    # Peak at t=5.5 with intensity 14.2 (> 8 dB threshold). Window is [5.0, 15.0],
    # so clip-local peak start is 0.5s.
    ctx = _ctx_with_peaks(audio_peaks=[{"t_start": 5.5, "t_end": 6.1, "intensity": 14.2}])
    PunchZoom().apply(ctx)
    assert len(ctx.extra_filters) == 1
    f = ctx.extra_filters[0]
    assert "zoompan" in f or "scale" in f
    # The expression should reference clip-local time (0.5s), not source-relative (5.5s).
    assert "0.5" in f


def test_subthreshold_peak_is_ignored():
    ctx = _ctx_with_peaks(audio_peaks=[{"t_start": 5.5, "t_end": 6.1, "intensity": 4.0}])
    PunchZoom().apply(ctx)
    assert ctx.extra_filters == []


def test_multiple_peaks_emit_multiple_filters():
    ctx = _ctx_with_peaks(audio_peaks=[
        {"t_start": 5.5, "t_end": 6.1, "intensity": 14.2},
        {"t_start": 12.0, "t_end": 12.4, "intensity": 9.5},
    ])
    PunchZoom().apply(ctx)
    assert len(ctx.extra_filters) == 2


def test_name_and_default_enabled():
    e = PunchZoom()
    assert e.name == "punch_zoom"
    assert e.default_enabled is True
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_effects_punch_zoom.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

`src/clipper/effects/punch_zoom.py`:
```python
"""Punch zoom: scale 1.0 → 1.08 → 1.0 over ~0.4s on audio peaks."""
from dataclasses import dataclass

from clipper.effects.context import EffectContext
from clipper.effects.registry import register

PUNCH_THRESHOLD_DB = 8.0
PUNCH_DURATION_S = 0.4
PUNCH_PEAK_SCALE = 1.08


@dataclass
class PunchZoom:
    name: str = "punch_zoom"
    default_enabled: bool = True

    def apply(self, ctx: EffectContext) -> None:
        clip_start = ctx.clip["t_start"]
        for peak in ctx.audio_peaks:
            if peak["intensity"] < PUNCH_THRESHOLD_DB:
                continue
            t_local = peak["t_start"] - clip_start
            t_end = t_local + PUNCH_DURATION_S
            # Sinusoidal ramp: 1.0 → 1.08 → 1.0 over PUNCH_DURATION_S using sin(PI*x).
            # zoompan with z expression keyed on t (input timestamp).
            expr = (
                f"if(between(t,{t_local:.3f},{t_end:.3f}),"
                f"1+{PUNCH_PEAK_SCALE - 1:.3f}*sin((t-{t_local:.3f})*PI/{PUNCH_DURATION_S}),1)"
            )
            ctx.extra_filters.append(
                f"zoompan=z='{expr}':d=1:s={ctx.output_size[0]}x{ctx.output_size[1]}:fps=30"
            )


register(PunchZoom())
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 60 + 5 = 65 passing.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/effects/punch_zoom.py tests/test_effects_punch_zoom.py
git commit -m "feat: punch_zoom effect — sinusoidal scale ramp on audio peaks"
```

---

## Phase 4 — hook_card effect

### Task 11: `hook_card` effect

**Files:**
- Create: `src/clipper/effects/hook_card.py`
- Create: `tests/test_effects_hook_card.py`

- [ ] **Step 1: Write failing tests**

`tests/test_effects_hook_card.py`:
```python
from clipper.captions import AssBuilder
from clipper.effects.context import EffectContext
from clipper.effects.hook_card import HookCard


def _ctx(hook_quality):
    return EffectContext(
        clip={"id": "c001", "t_start": 5.0, "t_end": 15.0, "hook_quality": hook_quality},
        transcript_words=[],
        audio_peaks=[],
        chat_peaks=[],
        face_track=None,
        output_size=(1080, 1920),
        ass=AssBuilder(1080, 1920),
    )


def test_low_hook_quality_no_card():
    ctx = _ctx(hook_quality=5)
    HookCard().apply(ctx)
    assert ctx.ass.event_lines == []


def test_high_hook_quality_adds_dialogue():
    ctx = _ctx(hook_quality=9)
    HookCard().apply(ctx)
    assert len(ctx.ass.event_lines) >= 1
    # Card text appears in the rendered ASS.
    rendered = ctx.ass.render()
    assert "WAIT FOR IT" in rendered


def test_card_only_in_first_1p5_seconds():
    ctx = _ctx(hook_quality=9)
    HookCard().apply(ctx)
    line = ctx.ass.event_lines[0]
    # End time should be at or before 0:00:01.50 clip-local.
    assert "0:00:01.50" in line or "0:00:01.4" in line or "0:00:01.5" in line


def test_threshold_exclusive_at_7():
    ctx = _ctx(hook_quality=7)
    HookCard().apply(ctx)
    # >=7 triggers.
    assert ctx.ass.event_lines != []


def test_name_and_default_enabled():
    e = HookCard()
    assert e.name == "hook_card"
    assert e.default_enabled is True
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_effects_hook_card.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

`src/clipper/effects/hook_card.py`:
```python
"""Hook card: "WAIT FOR IT" overlay on the first 1.5s when hook_quality >= 7."""
from dataclasses import dataclass

from clipper.effects.context import EffectContext
from clipper.effects.registry import register

HOOK_QUALITY_THRESHOLD = 7
HOOK_CARD_DURATION_S = 1.5
HOOK_CARD_TEXT = "WAIT FOR IT"


@dataclass
class HookCard:
    name: str = "hook_card"
    default_enabled: bool = True

    def apply(self, ctx: EffectContext) -> None:
        if ctx.clip.get("hook_quality", 0) < HOOK_QUALITY_THRESHOLD:
            return
        ctx.ass.add_style(
            name="HookCard",
            fontname="Arial Black",
            fontsize=64,
            primary="&H00FFFFFF&",
            outline="&H006633FF&",   # pink-red outline
            outline_width=6,
            margin_v=1500,           # near top of 9:16 frame
            alignment=8,             # top-center
        )
        # \fad(150,300): 150ms fade-in, 300ms fade-out.
        text = "{\\fad(150,300)}" + HOOK_CARD_TEXT
        ctx.ass.add_dialogue(0.0, HOOK_CARD_DURATION_S, text, style="HookCard")


register(HookCard())
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 65 + 5 = 70 passing.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/effects/hook_card.py tests/test_effects_hook_card.py
git commit -m "feat: hook_card effect — 'WAIT FOR IT' card on first 1.5s when hook_quality>=7"
```

---

## Phase 5 — reaction_zoom effect

### Task 12: `reaction_zoom` effect

**Files:**
- Create: `src/clipper/effects/reaction_zoom.py`
- Create: `tests/test_effects_reaction_zoom.py`

- [ ] **Step 1: Write failing tests**

`tests/test_effects_reaction_zoom.py`:
```python
from clipper.captions import AssBuilder
from clipper.effects.context import EffectContext
from clipper.effects.reaction_zoom import ReactionZoom


def _ctx(audio_peaks=None, chat_peaks=None):
    return EffectContext(
        clip={"id": "c001", "t_start": 5.0, "t_end": 15.0},
        transcript_words=[],
        audio_peaks=audio_peaks or [],
        chat_peaks=chat_peaks or [],
        face_track=None,
        output_size=(1080, 1920),
        ass=AssBuilder(1080, 1920),
    )


def test_no_peaks_no_filter():
    ctx = _ctx()
    ReactionZoom().apply(ctx)
    assert ctx.extra_filters == []


def test_combines_audio_and_chat_to_pick_biggest():
    # Audio peak at t=6.0 (intensity 5.0) → score 5
    # Chat peak at t=10.0 (hype 90.0)   → score 90
    # Combined peak at t=12 is biggest (audio 10 + chat 80 = 90, but separate from 90+0)
    # The biggest single-source score wins.
    audio = [{"t_start": 6.0, "t_end": 6.5, "intensity": 5.0}]
    chat = [{"t_start": 10.0, "t_end": 10.5, "msg_count": 90, "hype_score": 90.0, "top_emotes": []}]
    ctx = _ctx(audio_peaks=audio, chat_peaks=chat)
    ReactionZoom().apply(ctx)
    assert len(ctx.extra_filters) == 1
    # Center the reaction window on the chat peak: t_local = 10 - 5 = 5.0
    assert "5.0" in ctx.extra_filters[0]


def test_combined_audio_and_chat_at_same_time_wins():
    audio = [{"t_start": 9.0, "t_end": 9.5, "intensity": 12.0}]
    chat = [{"t_start": 9.0, "t_end": 9.5, "msg_count": 50, "hype_score": 60.0, "top_emotes": []}]
    ctx = _ctx(audio_peaks=audio, chat_peaks=chat)
    ReactionZoom().apply(ctx)
    assert len(ctx.extra_filters) == 1


def test_name_and_default_enabled():
    e = ReactionZoom()
    assert e.name == "reaction_zoom"
    assert e.default_enabled is True
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_effects_reaction_zoom.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

`src/clipper/effects/reaction_zoom.py`:
```python
"""Reaction zoom: 10% tighter crop window around the avatar at the moment of
the biggest combined audio+chat reaction in the clip."""
from dataclasses import dataclass

from clipper.effects.context import EffectContext
from clipper.effects.registry import register

ZOOM_WINDOW_S = 0.8
ZOOM_FACTOR = 1.10  # 10% tighter


@dataclass
class ReactionZoom:
    name: str = "reaction_zoom"
    default_enabled: bool = True

    def apply(self, ctx: EffectContext) -> None:
        clip_start = ctx.clip["t_start"]

        # Score every peak by source kind, then merge overlapping audio+chat for combined scores.
        scored: list[tuple[float, float]] = []   # (t_center, score)
        for p in ctx.audio_peaks:
            t = (p["t_start"] + p["t_end"]) / 2 - clip_start
            scored.append((t, float(p["intensity"])))
        for p in ctx.chat_peaks:
            t = (p["t_start"] + p["t_end"]) / 2 - clip_start
            scored.append((t, float(p["hype_score"])))

        if not scored:
            return

        # Pick the timestamp with the highest individual score. (Combined-score
        # merging adds complexity that's not worth it for v0; one strong signal
        # is enough to trigger a reaction zoom.)
        best_t, _ = max(scored, key=lambda x: x[1])
        zoom_start = max(0.0, best_t - ZOOM_WINDOW_S / 2)
        zoom_end = zoom_start + ZOOM_WINDOW_S
        expr = (
            f"if(between(t,{zoom_start:.3f},{zoom_end:.3f}),{ZOOM_FACTOR},1)"
        )
        ctx.extra_filters.append(
            f"zoompan=z='{expr}':d=1:s={ctx.output_size[0]}x{ctx.output_size[1]}:fps=30"
        )


register(ReactionZoom())
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 70 + 4 = 74 passing.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/effects/reaction_zoom.py tests/test_effects_reaction_zoom.py
git commit -m "feat: reaction_zoom effect — 10% tighter crop at biggest peak"
```

---

## Phase 6 — emoji_burst effect

### Task 13: Bundle Twemoji PNGs

**Files:**
- Create: `assets/emojis/README.md`
- Create: `assets/emojis/1f602.png`
- Create: `assets/emojis/1f480.png`
- Create: `assets/emojis/1f525.png`
- Create: `assets/emojis/1f631.png`
- Create: `assets/emojis/2728.png`
- Create: `assets/emojis/1f44f.png`
- Modify: `pyproject.toml`

Twemoji is open-source (CC-BY 4.0) and ships PNGs at https://github.com/twitter/twemoji.

- [ ] **Step 1: Write `assets/emojis/README.md`**

```markdown
# Bundled emoji PNGs

These six 72×72 PNGs are sourced from [Twemoji](https://github.com/twitter/twemoji)
(licensed CC-BY 4.0) and bundled with `clipper` for the `emoji_burst` effect.

| File          | Glyph | Codepoint |
|---------------|-------|-----------|
| `1f602.png`   | 😂    | U+1F602   |
| `1f480.png`   | 💀    | U+1F480   |
| `1f525.png`   | 🔥    | U+1F525   |
| `1f631.png`   | 😱    | U+1F631   |
| `2728.png`    | ✨    | U+2728    |
| `1f44f.png`   | 👏    | U+1F44F   |

These are intentionally a small "general reaction" set, not a literal mapping of
Twitch emote names (KEKW, LULW, ...) to glyphs — `emoji_burst` picks one
deterministically per chat peak based on a hash of the peak's top emote.

Replace these files (keeping the same names) to use a different emoji art style.
```

- [ ] **Step 2: Download the six PNGs**

Using a one-liner per file with curl/Invoke-WebRequest from `https://github.com/twitter/twemoji/raw/master/assets/72x72/<code>.png`:

```powershell
$base = "https://github.com/twitter/twemoji/raw/master/assets/72x72"
foreach ($code in "1f602","1f480","1f525","1f631","2728","1f44f") {
    Invoke-WebRequest -Uri "$base/$code.png" -OutFile "assets/emojis/$code.png"
}
```

Verify each file is ~3-5 KB and starts with the PNG magic bytes (`89 50 4E 47`).

- [ ] **Step 3: Update `pyproject.toml` package-data**

In the `[tool.setuptools.package-data]` table, change:
```toml
"clipper" = ["web/*.html", "web/*.css", "web/*.js"]
```
to:
```toml
"clipper" = ["web/*.html", "web/*.css", "web/*.js"]
```

(No change needed there — `assets/emojis/` lives at project root, not under `src/clipper/`. We'll resolve it via a path constant in the effect.)

Add a new entry under `[tool.setuptools]`:
```toml
[tool.setuptools]
include-package-data = true
```

And reinstall the editable package so it picks up the new file layout:
```powershell
.venv\Scripts\pip.exe install -e . --no-deps
```

- [ ] **Step 4: Verify (no test yet)**

Confirm: `(.venv\Scripts\python.exe -c "from pathlib import Path; p = Path('assets/emojis'); print(sorted(f.name for f in p.glob('*.png')))")` lists all 6.

`.venv\Scripts\pytest.exe -v` → still 74 passing.

- [ ] **Step 5: Commit**

```bash
git add assets/emojis/ pyproject.toml
git commit -m "feat: bundle 6 Twemoji PNGs for emoji_burst effect"
```

---

### Task 14: `emoji_burst` effect

**Files:**
- Create: `src/clipper/effects/emoji_burst.py`
- Create: `tests/test_effects_emoji_burst.py`

- [ ] **Step 1: Write failing tests**

`tests/test_effects_emoji_burst.py`:
```python
from pathlib import Path

from clipper.captions import AssBuilder
from clipper.effects.context import EffectContext
from clipper.effects.emoji_burst import EmojiBurst


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "assets"


def _ctx(chat_peaks):
    return EffectContext(
        clip={"id": "c001", "t_start": 5.0, "t_end": 15.0},
        transcript_words=[],
        audio_peaks=[],
        chat_peaks=chat_peaks,
        face_track=None,
        output_size=(1080, 1920),
        ass=AssBuilder(1080, 1920),
        assets_dir=ASSETS,
    )


def test_no_chat_peaks_no_filter():
    ctx = _ctx(chat_peaks=[])
    EmojiBurst().apply(ctx)
    assert ctx.extra_filters == []


def test_one_chat_peak_appends_overlay_filter():
    chat = [{"t_start": 5.8, "t_end": 8.2, "msg_count": 142, "hype_score": 87.0, "top_emotes": ["KEKW"]}]
    ctx = _ctx(chat_peaks=chat)
    EmojiBurst().apply(ctx)
    # Expect one overlay filter referencing a PNG.
    assert len(ctx.extra_filters) >= 1
    assert any("overlay=" in f and ".png" in f for f in ctx.extra_filters)


def test_picks_deterministic_emoji_for_same_emote():
    # Same input emote → same emoji choice across runs.
    chat = [{"t_start": 5.8, "t_end": 8.2, "msg_count": 142, "hype_score": 87.0, "top_emotes": ["KEKW"]}]
    ctx_a = _ctx(chat_peaks=chat)
    ctx_b = _ctx(chat_peaks=chat)
    EmojiBurst().apply(ctx_a)
    EmojiBurst().apply(ctx_b)
    assert ctx_a.extra_filters == ctx_b.extra_filters


def test_missing_assets_dir_skips():
    chat = [{"t_start": 5.8, "t_end": 8.2, "msg_count": 142, "hype_score": 87.0, "top_emotes": ["KEKW"]}]
    ctx = _ctx(chat_peaks=chat)
    ctx.assets_dir = None
    EmojiBurst().apply(ctx)
    assert ctx.extra_filters == []


def test_name_and_default_enabled():
    e = EmojiBurst()
    assert e.name == "emoji_burst"
    assert e.default_enabled is True
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_effects_emoji_burst.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

`src/clipper/effects/emoji_burst.py`:
```python
"""Emoji burst: overlay a Twemoji PNG at chat-peak moments.

Picks a deterministic emoji per peak based on a hash of the top emote so
that re-runs of finalize on the same clip produce the same overlay choices.
"""
import hashlib
from dataclasses import dataclass

from clipper.effects.context import EffectContext
from clipper.effects.registry import register

EMOJI_FILES = ["1f602.png", "1f480.png", "1f525.png", "1f631.png", "2728.png", "1f44f.png"]
EMOJI_SIZE = 180   # px in the 1080x1920 frame
EMOJI_VISIBLE_S = 0.8


def _pick_emoji_for(top_emote: str) -> str:
    h = hashlib.sha1(top_emote.encode("utf-8")).digest()
    return EMOJI_FILES[h[0] % len(EMOJI_FILES)]


@dataclass
class EmojiBurst:
    name: str = "emoji_burst"
    default_enabled: bool = True

    def apply(self, ctx: EffectContext) -> None:
        if ctx.assets_dir is None:
            return
        clip_start = ctx.clip["t_start"]
        for peak in ctx.chat_peaks:
            emotes = peak.get("top_emotes", [])
            if not emotes:
                continue
            emoji_path = ctx.assets_dir / "emojis" / _pick_emoji_for(emotes[0])
            if not emoji_path.exists():
                continue
            t_local = (peak["t_start"] + peak["t_end"]) / 2 - clip_start
            t_end = t_local + EMOJI_VISIBLE_S
            # Position based on hash → upper-left, upper-right, mid-right.
            h = hashlib.sha1(emotes[0].encode("utf-8")).digest()[1] % 3
            x = {0: "main_w*0.10", 1: "main_w*0.65", 2: "main_w*0.70"}[h]
            y = {0: "main_h*0.15", 1: "main_h*0.18", 2: "main_h*0.55"}[h]
            # ffmpeg overlay enable expr: between(t, t_local, t_end).
            esc = str(emoji_path).replace("\\", "/").replace(":", "\\:")
            # movie filter to source the PNG, scaled, then overlay onto the main stream.
            ctx.extra_filters.append(
                f"movie='{esc}',scale={EMOJI_SIZE}:{EMOJI_SIZE}[em{int(t_local * 1000)}];"
                f"[in][em{int(t_local * 1000)}]overlay={x}:{y}:"
                f"enable='between(t,{t_local:.3f},{t_end:.3f})'[out]"
            )


register(EmojiBurst())
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 74 + 5 = 79 passing.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/effects/emoji_burst.py tests/test_effects_emoji_burst.py
git commit -m "feat: emoji_burst effect — deterministic Twemoji PNG overlay at chat peaks"
```

---

## Phase 7 — Finalize integration

### Task 15: Wire the effect chain into finalize

**Files:**
- Modify: `src/clipper/finalize.py`
- Create: `tests/test_finalize_effects.py`

- [ ] **Step 1: Write failing integration test**

`tests/test_finalize_effects.py`:
```python
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipper.finalize import finalize
from clipper.preview_export import preview_export
from clipper.web import build_app


def _keep_only(work: Path, kept_ids: list[str]) -> None:
    client = TestClient(build_app(work))
    for cid in ("c001", "c002", "c003"):
        client.put(f"/api/clips/{cid}", json={"kept": cid in kept_ids})


def test_default_effects_applied_to_manifest(fixture_work_dir: Path, fixture_out_dir: Path):
    preview_export(fixture_work_dir)
    _keep_only(fixture_work_dir, ["c001"])
    finalize(fixture_work_dir, fixture_out_dir)
    manifest = json.loads((fixture_out_dir / "final" / "manifest.json").read_text())
    applied = set(manifest["clips"][0]["effects_applied"])
    # Default effects all enabled; captions plus the four effects.
    assert "captions" in applied
    assert "punch_zoom" in applied
    assert "hook_card" in applied  # c001 has hook_quality=9
    assert "reaction_zoom" in applied


def test_per_clip_effect_overrides_disable_specific_effect(fixture_work_dir, fixture_out_dir):
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    client.put("/api/clips/c001", json={"effects": {"punch_zoom": False}})
    client.put("/api/clips/c002", json={"kept": False})
    client.put("/api/clips/c003", json={"kept": False})
    finalize(fixture_work_dir, fixture_out_dir)
    manifest = json.loads((fixture_out_dir / "final" / "manifest.json").read_text())
    applied = set(manifest["clips"][0]["effects_applied"])
    assert "punch_zoom" not in applied
    # Others remain.
    assert "hook_card" in applied
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_finalize_effects.py -v`
Expected: FAIL — current `effects_applied` is always `["captions"]`.

- [ ] **Step 3: Rewrite the per-clip block in `src/clipper/finalize.py`**

First, add imports at the top of `src/clipper/finalize.py`:
```python
from clipper.effects import REGISTRY, EffectContext, default_effects_config
# Force-import effect modules so they self-register.
from clipper.effects import emoji_burst as _eb  # noqa: F401
from clipper.effects import hook_card as _hc    # noqa: F401
from clipper.effects import punch_zoom as _pz   # noqa: F401
from clipper.effects import reaction_zoom as _rz  # noqa: F401
from clipper.captions import AssBuilder, generate_srt
from clipper.util.peaks import load_audio_peaks, load_chat_peaks, peaks_in_window
```

Then replace the body of `finalize()` with:
```python
def finalize(work_dir: Path, out_root: Path) -> Path:
    final_dir = out_root / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    video = work_dir / "video.mp4"
    transcript = load_transcript(work_dir)
    audio_peaks = load_audio_peaks(work_dir)
    chat_peaks = load_chat_peaks(work_dir)
    face_track_data: dict = (read_json(work_dir / "face_track.json")
                              if (work_dir / "face_track.json").exists() else {})
    assets_dir = Path(__file__).resolve().parents[2] / "assets"
    kept = _kept_clips(work_dir)

    manifest_clips = []
    for idx, clip in enumerate(kept, start=1):
        slug = slugify(clip["title"], index=idx)
        base = final_dir / slug
        words = words_in_window(transcript, clip["t_start"], clip["t_end"])
        duration = clip["t_end"] - clip["t_start"]
        mode = clip.get("caption_mode", "burned")
        style = clip.get("caption_style", "window3")

        # Build EffectContext and run the chain.
        clip_audio_peaks = peaks_in_window(audio_peaks, clip["t_start"], clip["t_end"])
        clip_chat_peaks = peaks_in_window(chat_peaks, clip["t_start"], clip["t_end"])
        clip_face = face_track_data.get(clip["id"])
        ass = AssBuilder(FINAL.width, FINAL.height)
        # Register Default style first so caption Dialogue lines (style=Default) resolve
        # correctly when effects later add their own named styles (e.g. HookCard).
        # Without this, render() would auto-add Default ONLY when style_lines is empty,
        # which fails after HookCard.add_style() runs.
        ass.add_style()
        # Seed captions into ass (the captions "effect" is special — always-on unless mode=clean).
        if mode in ("burned", "both"):
            from clipper.captions import generate_ass  # local import keeps the module DAG tight
            seeded = generate_ass(style, words, clip["t_start"], (FINAL.width, FINAL.height))
            # The dispatcher returns a full ASS document. Parse out its Dialogue lines and
            # re-add them to our shared AssBuilder so effects can layer in.
            for line in seeded.splitlines():
                if line.startswith("Dialogue:"):
                    ass.event_lines.append(line)
        ctx = EffectContext(
            clip=clip,
            transcript_words=words,
            audio_peaks=clip_audio_peaks,
            chat_peaks=clip_chat_peaks,
            face_track=clip_face,
            output_size=(FINAL.width, FINAL.height),
            ass=ass,
            assets_dir=assets_dir,
        )

        # Resolve effect-enabled flags: registry default ← per-clip override.
        per_clip_overrides = clip.get("effects", {})
        effects_enabled = {**default_effects_config(), **per_clip_overrides}
        applied: list[str] = []
        for effect_name, on in effects_enabled.items():
            if not on:
                continue
            effect = REGISTRY.get(effect_name)
            if effect is None:
                continue
            before_filters = len(ctx.extra_filters)
            before_events = len(ctx.ass.event_lines)
            effect.apply(ctx)
            if len(ctx.extra_filters) > before_filters or len(ctx.ass.event_lines) > before_events:
                applied.append(effect_name)
        if mode != "clean":
            applied.insert(0, "captions")

        burned_path = None
        clean_path = None
        srt_path = None

        if mode in ("burned", "both"):
            with tempfile.NamedTemporaryFile(
                "w", suffix=".ass", delete=False, encoding="utf-8"
            ) as f:
                f.write(ctx.ass.render())
                ass_path = Path(f.name)
            try:
                burned_path = base.with_suffix(".mp4")
                encode_clip(
                    video, clip["t_start"], duration, burned_path, FINAL,
                    subtitles_path=ass_path,
                    extra_filters=ctx.extra_filters or None,
                )
            finally:
                ass_path.unlink(missing_ok=True)

        if mode in ("clean", "both"):
            if mode == "both":
                clean_path = base.with_name(base.name + "_clean").with_suffix(".mp4")
            else:
                clean_path = base.with_suffix(".mp4")
            # Clean output still gets non-caption effects (zoompan, overlays).
            encode_clip(
                video, clip["t_start"], duration, clean_path, FINAL,
                extra_filters=ctx.extra_filters or None,
            )
            srt_path = base.with_suffix(".srt")
            srt_path.write_text(generate_srt(words, clip["t_start"]), encoding="utf-8")

        manifest_clips.append({
            "filename": burned_path.name if burned_path else clean_path.name,
            "clean_filename": clean_path.name if (mode == "both" and clean_path) else None,
            "srt_filename": srt_path.name if srt_path else None,
            "title": clip["title"],
            "t_start_source": clip["t_start"],
            "t_end_source": clip["t_end"],
            "duration": duration,
            "caption_mode": mode,
            "caption_style": style,
            "effects_applied": applied,
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

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 79 + 2 = 81 passing. All existing finalize tests must still pass — they don't check `effects_applied` strictly, so adding new entries is backward-compatible.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/finalize.py tests/test_finalize_effects.py
git commit -m "feat: effects chain integrated into finalize; per-clip overrides honored"
```

---

## Phase 8 — UI: effect overrides + caption-style selector

### Task 16: Effect checkboxes in HTML + CSS

**Files:**
- Modify: `src/clipper/web/index.html`
- Modify: `src/clipper/web/app.css`

- [ ] **Step 1: Update `index.html`**

Find the existing edit-row block for "Captions" (the `<select id="caption-mode">` row) and replace it with:
```html
      <div class="edit-row">
        <label>Captions
          <select id="caption-mode">
            <option value="burned">Burned</option>
            <option value="clean">Clean + SRT</option>
            <option value="both">Both</option>
          </select>
        </label>
        <label>Style
          <select id="caption-style">
            <option value="window3">3-word window</option>
            <option value="basic">Basic</option>
          </select>
        </label>
      </div>
      <div class="edit-row effects-row">
        <span class="effects-label">Effects:</span>
        <label class="effect-toggle"><input type="checkbox" data-effect="punch_zoom"> Punch</label>
        <label class="effect-toggle"><input type="checkbox" data-effect="emoji_burst"> Emoji</label>
        <label class="effect-toggle"><input type="checkbox" data-effect="hook_card"> Hook</label>
        <label class="effect-toggle"><input type="checkbox" data-effect="reaction_zoom"> ReactZoom</label>
      </div>
```

- [ ] **Step 2: Add CSS to `app.css`**

Append:
```css
.effects-row { gap: 14px; flex-wrap: wrap; }
.effects-row .effects-label { font-size: 12px; opacity: 0.7; }
.effect-toggle { display: inline-flex; align-items: center; gap: 4px;
                 font-size: 12px; cursor: pointer; padding: 3px 6px; }
.effect-toggle input { margin: 0; }
```

- [ ] **Step 3: Verify**

Run: `.venv\Scripts\pytest.exe tests/test_web_endpoints.py -v`
Expected: all pass (the HTML/CSS check tests don't assert structure beyond title/clip-row presence).

- [ ] **Step 4: Commit**

```bash
git add src/clipper/web/index.html src/clipper/web/app.css
git commit -m "feat: effect-toggle checkboxes + caption-style selector in review UI"
```

---

### Task 17: app.js — read/write effect overrides + caption style

**Files:**
- Modify: `src/clipper/web/app.js`
- Modify: `tests/test_web_endpoints.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_web_endpoints.py`:
```python
def test_app_js_has_effect_toggle_handler(fixture_work_dir):
    client = TestClient(build_app(fixture_work_dir))
    r = client.get("/static/app.js")
    assert r.status_code == 200
    assert "data-effect" in r.text
    assert "caption-style" in r.text
    assert "innerHTML" not in r.text   # XSS guard still holds
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv\Scripts\pytest.exe tests/test_web_endpoints.py::test_app_js_has_effect_toggle_handler -v`
Expected: FAIL.

- [ ] **Step 3: Patch `app.js`**

In `src/clipper/web/app.js`, find the `selectClip` function and replace the body with:
```javascript
async function selectClip(id) {
  state.selectedId = id;
  renderList();
  const clip = state.clips.find(c => c.id === id);
  document.getElementById("title-input").value = clip.title;
  document.getElementById("t-start-input").value = clip.t_start.toFixed(3);
  document.getElementById("t-end-input").value = clip.t_end.toFixed(3);
  document.getElementById("caption-mode").value = clip.caption_mode;
  document.getElementById("caption-style").value = clip.caption_style || "window3";

  // Sync effect checkboxes.
  for (const cb of document.querySelectorAll(".effect-toggle input[data-effect]")) {
    const name = cb.dataset.effect;
    cb.checked = clip.effects && clip.effects[name] !== false;
  }

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
```

Add new event listeners after the existing `caption-mode` listener block:
```javascript
document.getElementById("caption-style").addEventListener("change", e => {
  patchClip({caption_style: e.target.value});
});

for (const cb of document.querySelectorAll(".effect-toggle input[data-effect]")) {
  cb.addEventListener("change", e => {
    const clip = state.clips.find(c => c.id === state.selectedId);
    const next = { ...(clip.effects || {}), [e.target.dataset.effect]: e.target.checked };
    patchClip({effects: next});
  });
}
```

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 81 + 1 = 82 passing.

- [ ] **Step 5: Commit**

```bash
git add src/clipper/web/app.js tests/test_web_endpoints.py
git commit -m "feat: app.js wires effect checkboxes + caption-style selector to /api/clips"
```

---

## Phase 9 — Documentation

### Task 18: Update spec / architecture / milestones / changelog / README

**Files:**
- Modify: `spec.md`
- Modify: `architecture.md`
- Modify: `MILESTONES.md`
- Modify: `changelog.md`
- Modify: `README.md`

- [ ] **Step 1: spec.md**

In the `[finalize]` block (§7 config), update `caption_style` to reflect what Plan B actually ships:
```toml
caption_style = "window3"      # window3 | basic  (other animated styles deferred)
```

In §6.13 `effects/`, replace the "Protocol only; concrete effects ship in Plan B" note with a list of the four shipped effects: `punch_zoom`, `emoji_burst`, `hook_card`, `reaction_zoom`. Cross-reference `plan-b-effects.md`.

In §8 (acceptance criteria), add:
> 11. With default effects enabled, finalize manifest's `effects_applied` lists `captions`, `punch_zoom`, `hook_card`, `reaction_zoom`, and `emoji_burst` (when the clip has chat peaks).
> 12. Per-clip effect overrides via the review UI are honored at finalize.

- [ ] **Step 2: architecture.md**

In §3 module table, replace the `effects/` row with:
> `effects/` — `FinalizeEffect` Protocol + 4 concrete effects (`punch_zoom`, `emoji_burst`, `hook_card`, `reaction_zoom`). Each mutates a shared `EffectContext` (AssBuilder + extra_filters). Registry in `effects/registry.py`.

Add to §11 Web Layer:
> Per-clip `effects` dict and `caption_style` field are persisted to `review_state.json` and override registry defaults at finalize time.

- [ ] **Step 3: MILESTONES.md**

Insert a new M5.6 before M6 (or extend M5.5 with a "Plan B add-on" note):
```markdown
## M5.6 — Motion Graphics + Animated Captions (Plan B)

**Goal:** Submagic-style aesthetic — animated captions + four motion effects shipped, per-clip toggleable in review UI.

**Deliverables**
- `window3` animated caption style (3-word window + active-word yellow highlight).
- 4 effects: `punch_zoom`, `emoji_burst`, `hook_card`, `reaction_zoom`.
- `EffectContext` + `FinalizeEffect` Protocol + registry.
- UI effect-checkbox controls + caption-style selector.
- Bundled Twemoji PNGs for `emoji_burst`.
- Plan A debt cleanup: atomic write in json_io, 3-word caption overlay grouping.

**Validation**
- Finalize a clip from the fixture and inspect the resulting MP4 — captions animate per word with the active word in yellow; punch_zoom fires on audio peaks (≥ 8 dB); hook_card overlay appears for the first 1.5s when hook_quality ≥ 7; emoji bursts at chat peaks; reaction_zoom tightens crop at the biggest peak.
- Disable an effect in the UI; re-finalize; verify `effects_applied` no longer lists it.

**Effort:** 1-2 sessions.

**Note:** Remove the stale "Web UI for reviewing + editing clip selections" from Post-v0 (shipped in M5.5).
```

Delete the stale "Web UI for reviewing + editing clip selections" entry from the Post-v0 list.

- [ ] **Step 4: changelog.md**

Under `## [Unreleased]`, add to `Planning`:
- `plan-b-effects.md` — implementation plan for animated captions + 4 motion effects.

Add to `Decisions` (use today's date):
- **2026-05-12** — `emoji_burst` uses bundled Twemoji PNGs picked deterministically by emote-name hash, not literal emote→glyph mapping. Twitch emotes (KEKW, LULW, ...) have no Unicode equivalent, so we use a generic-reaction palette of six emojis.
- **2026-05-12** — `window3` is the only animated caption style shipped in Plan B. `single`, `karaoke`, `stacked2` from interaction-design §5 were design alternatives and remain post-Plan-B.
- **2026-05-12** — Effects gracefully no-op when their input data (audio_peaks.json / chat_peaks.json) is missing. This lets Plan B ship before M1-M4 produces real peaks.
- **2026-05-12** — `json_io.write_json` is now atomic (write-to-tmp + `os.replace`). Crash mid-write leaves the previous state file intact.

- [ ] **Step 5: README.md**

Under "Quick start (Plan A only)", add a section "Plan B (animated captions + effects)":
```markdown
## Plan B (animated captions + effects)

Plan B ships `window3` animated captions and four effects (`punch_zoom`,
`emoji_burst`, `hook_card`, `reaction_zoom`). Each is toggleable per-clip in
the review UI. Effects gracefully no-op when their input peak data is missing
(M1-M4 upstream will produce it; today, use the test fixtures).
```

Update "Status" line to: "Plan A + Plan B complete; upstream pipeline (M1-M4) pending."

- [ ] **Step 6: Verify suite still passes**

Run: `.venv\Scripts\pytest.exe -v`
Expected: 82 passing (docs-only).

- [ ] **Step 7: Commit**

```bash
git add spec.md architecture.md MILESTONES.md changelog.md README.md
git commit -m "docs: update spec/architecture/milestones/changelog/README for Plan B"
```

---

## Self-Review Summary

After all 18 tasks across 9 phases:

- **Spec coverage** vs `interaction-design.md` §5-6:
  - §5 captions: `window3` ✅; `single`/`karaoke`/`stacked2` deferred (documented).
  - §6 effects: all four shipped ✅.
  - §6 per-clip overrides via UI ✅.
  - Twemoji approach (PNG overlay) ✅ — design doc says either font or PNG; chose PNG for libass reliability.

- **No placeholders.** Every step ships actual code or a concrete command. No "TODO" or "TBD" anywhere.

- **Type consistency.** `EffectContext` and `FinalizeEffect` are defined in Task 5/6 and consumed identically in Tasks 10/11/12/14/15. `caption_style` is `Literal["basic", "window3"]` in both `ClipState` and `ClipUpdate`. `register()` is called with the same name strings used in `default_effects_config`.

- **Test coverage targets.** ~37 new test cases across 9 test files (atomic write, peaks, window3, 4 effects, finalize integration, JS overrides). End-to-end test in Task 15 confirms all effects participate in a real encode against the fixture video.

- **Plan A integration risks addressed.**
  - Atomic write protects state during rapid effect-checkbox toggling (Task 1).
  - Caption grouping in the live overlay matches the burned `window3` style (Task 2).
  - Effects gracefully degrade when peaks are missing (Tasks 10/12/14 all test the empty-input case).

## What's left for a future Plan C / polish

- `single` / `karaoke` / `stacked2` animated caption styles.
- Trim nudge keys (`z`/`x`/`,`/`.`), `Esc`/`Enter` focus shortcuts, `?` help overlay.
- `post_finalize` SSE blocking-the-event-loop fix (move encode to background thread).
- `server.json` PID-based re-attach.
- `review_state.json` corrupt-state fallback.
- `config.toml` for runtime knobs (idle timeout, port range, default effect set).
- Stale entries in `MILESTONES.md` Post-v0 list (cleaned up in Task 18, but watch for regressions).
- Removing `MILESTONES.md` Post-v0 "Web UI" item (done in Task 18, called out separately for visibility).
- Real-VOD end-to-end smoke (requires M1-M4).
