# VTuber Clip Generator — Build Spec

> Hand this file to Claude Code as the project brief. It contains the full architecture, module-by-module responsibilities, data contracts, config, and acceptance criteria for a v0 that runs end-to-end on a single Twitch VOD.

---

## 1. Goal

Build a local Python tool that ingests a Twitch VOD URL of an English-speaking VTuber and produces 10–20 ready-to-post 9:16 TikTok/Shorts/Reels clips with burned-in captions. The system identifies highlight moments by fusing chat velocity, audio energy, and avatar expression signals, uses an LLM to rank candidates and pick clean in/out points, then exports the clips with face-tracked vertical cropping.

The whole pipeline must run for free on the user's hardware. No paid APIs in the default path.

---

## 2. Target Environment

- **OS:** Windows 11 (PowerShell)
- **GPU:** NVIDIA RTX 3080 (10 GB VRAM, CUDA available)
- **Python:** 3.11 or 3.12 (NOT 3.13 — `mediapipe` wheels lag)
- **External binaries on PATH:**
  - `ffmpeg` with NVENC support (`ffmpeg -encoders | findstr nvenc` should list `h264_nvenc`)
  - `yt-dlp` (latest)
- **Disk:** plan for ~30 GB free per 4-hour 1080p60 VOD during processing

---

## 3. Architecture

```
                   ┌─────────────────────────┐
                   │  Twitch VOD URL (input) │
                   └────────────┬────────────┘
                                │
                ┌───────────────┴────────────────┐
                ▼                                ▼
        ┌──────────────┐                ┌──────────────┐
        │  download.py │                │   chat.py    │
        │ (yt-dlp 1080p│                │(chat-download│
        │  60 + audio) │                │  -er, JSON)  │
        └──────┬───────┘                └──────┬───────┘
               │                               │
               ▼                               │
        ┌──────────────┐                       │
        │ transcribe.py│                       │
        │   (faster-   │                       │
        │   whisper,   │                       │
        │distil-large- │                       │
        │     v3)      │                       │
        └──────┬───────┘                       │
               │                               │
               ▼                               ▼
        ┌──────────────┐                ┌──────────────┐
        │audio_peaks.py│                │chat_peaks.py │
        │ (ffmpeg+RMS) │                │(rolling msg/s│
        │              │                │ + emote regex│
        └──────┬───────┘                └──────┬───────┘
               │                               │
               └───────────────┬───────────────┘
                               ▼
                       ┌──────────────┐
                       │ candidates.py│
                       │  (merge over-│
                       │   lapping    │
                       │   peaks)     │
                       └──────┬───────┘
                              │
                              ▼
                       ┌──────────────┐
                       │   rank.py    │
                       │ (Ollama llama│
                       │  3.1 8B or   │
                       │  Anthropic   │
                       │  API)        │
                       └──────┬───────┘
                              │
                              ▼
                       ┌──────────────┐
                       │ face_track.py│
                       │ (MediaPipe → │
                       │   x-center   │
                       │   per frame) │
                       └──────┬───────┘
                              │
                              ▼
                       ┌──────────────┐
                       │  export.py   │
                       │ (ffmpeg NVENC│
                       │   9:16 crop  │
                       │  + captions) │
                       └──────┬───────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │  out/clips/*.mp4      │
                  │  out/manifest.json    │
                  └───────────────────────┘
```

---

## 4. Project Structure

```
vtuber-clipper/
├── pyproject.toml
├── README.md
├── config.toml                  # user-edited settings
├── .env.example                 # optional API keys
├── src/
│   └── clipper/
│       ├── __init__.py
│       ├── main.py              # CLI entry point
│       ├── download.py
│       ├── chat.py
│       ├── transcribe.py
│       ├── audio_peaks.py
│       ├── chat_peaks.py
│       ├── candidates.py
│       ├── rank.py              # has OllamaRanker and AnthropicRanker
│       ├── face_track.py
│       ├── export.py
│       └── util/
│           ├── __init__.py
│           ├── timing.py        # timestamp/seconds helpers
│           └── logging.py       # rich-based progress
├── work/                        # gitignored, intermediate files per VOD
│   └── <vod_id>/
│       ├── video.mp4
│       ├── audio.opus
│       ├── chat.json
│       ├── transcript.json
│       ├── audio_peaks.json
│       ├── chat_peaks.json
│       ├── candidates.json
│       ├── ranked.json
│       └── face_track.json
├── out/
│   └── <vod_id>/
│       ├── clips/
│       │   ├── 01_<slug>.mp4
│       │   └── ...
│       └── manifest.json        # titles, scores, source timestamps
└── tests/
    └── test_candidates.py       # at minimum, unit test the peak-merge logic
```

---

## 5. Dependencies

### Python packages (pyproject.toml)

```toml
[project]
name = "vtuber-clipper"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = [
    "faster-whisper>=1.0.3",
    "chat-downloader>=0.2.8",
    "yt-dlp>=2024.10.0",
    "numpy>=1.26",
    "scipy>=1.13",                 # peak finding
    "mediapipe>=0.10.14",
    "opencv-python>=4.10",
    "pydantic>=2.8",
    "tomli>=2.0; python_version<'3.11'",
    "rich>=13.7",                  # progress + pretty logging
    "click>=8.1",                  # CLI
    "httpx>=0.27",                 # Ollama HTTP client
    "anthropic>=0.39; extra=='anthropic'",
]

[project.optional-dependencies]
anthropic = ["anthropic>=0.39"]

[project.scripts]
clipper = "clipper.main:cli"
```

### External tools

- **ffmpeg** — download a static build from gyan.dev, ensure NVENC is included, add to PATH
- **yt-dlp** — `pip install` works, or download the standalone exe
- **Ollama** (for the default free ranker path) — install from ollama.com, then `ollama pull llama3.1:8b`

---

## 6. Module Specs

### 6.1 `download.py`

**Responsibility:** Fetch the Twitch VOD video file and a separately-extracted low-bitrate audio file.

**Interface:**
```python
def download_vod(url: str, work_dir: Path, quality: str = "1080p60") -> DownloadResult:
    """Returns paths to video.mp4 and audio.opus."""

@dataclass
class DownloadResult:
    video_path: Path
    audio_path: Path
    vod_id: str
    duration_seconds: float
    title: str
    streamer: str
```

**Implementation notes:**
- Use `yt-dlp` as a subprocess (`subprocess.run`), parsing JSON output with `--print-json` to capture metadata
- Video: `yt-dlp -f <quality> -o video.mp4 <url>`
- Audio: extract from the downloaded video with ffmpeg rather than re-downloading: `ffmpeg -i video.mp4 -vn -c:a libopus -b:a 32k audio.opus`
- 32 kbps Opus is plenty for ASR and keeps the file small (~80 MB for 4 hours)
- VOD ID is the numeric part of the URL — parse with regex
- If the video file already exists, skip the download (idempotent)

### 6.2 `chat.py`

**Responsibility:** Fetch full Twitch chat replay as a JSON list of `{timestamp_seconds, user, message}` objects.

**Interface:**
```python
def download_chat(url: str, work_dir: Path) -> Path:
    """Returns path to chat.json."""
```

**Implementation:**
- Use `chat-downloader` Python package (NOT a subprocess — import it directly)
- `from chat_downloader import ChatDownloader; cd = ChatDownloader(); chat = cd.get_chat(url)`
- For each message, store `{"t": time_in_seconds, "user": author_name, "msg": message_text}` — keep the schema lean
- Write as JSON Lines (`.jsonl`) for streaming-friendly later reads, not a single JSON array

### 6.3 `transcribe.py`

**Responsibility:** Generate a word-level timestamped transcript of the audio.

**Interface:**
```python
def transcribe(audio_path: Path, work_dir: Path, model_size: str = "distil-large-v3") -> Path:
    """Returns path to transcript.json with word-level timestamps."""
```

**Implementation:**
```python
from faster_whisper import WhisperModel
model = WhisperModel(
    model_size,
    device="cuda",
    compute_type="float16",
)
segments, _ = model.transcribe(
    str(audio_path),
    language="en",
    word_timestamps=True,
    vad_filter=True,        # skip silence, makes long VODs much faster
    beam_size=5,
)
```

Output JSON shape:
```json
{
  "segments": [
    {
      "start": 12.34, "end": 16.78, "text": "...",
      "words": [{"start": 12.34, "end": 12.61, "word": "hello"}, ...]
    }
  ]
}
```

VAD filtering is important — it skips dead air and roughly halves wall-clock time on a typical stream with long pauses.

### 6.4 `audio_peaks.py`

**Responsibility:** Identify moments where audio energy spikes (screams, laughter, loud reactions).

**Interface:**
```python
def detect_audio_peaks(audio_path: Path, work_dir: Path) -> Path:
    """Returns path to audio_peaks.json: list of {t_start, t_end, intensity}."""
```

**Implementation:**
- Use ffmpeg to extract RMS energy per ~250ms window:
  ```
  ffmpeg -i audio.opus -af "astats=metadata=1:reset=0.25,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=rms.log" -f null -
  ```
- Parse `rms.log` into a numpy array of (time, db) pairs
- Compute a baseline (rolling median over 60s window)
- Flag windows where current RMS exceeds `baseline + 6 dB` for at least 1 second
- Merge adjacent flagged windows within 2 seconds of each other
- Output: list of `{"t_start": float, "t_end": float, "intensity": float}` where intensity is peak dB above baseline

### 6.5 `chat_peaks.py`

**Responsibility:** Identify moments where chat goes wild.

**Interface:**
```python
def detect_chat_peaks(chat_path: Path, duration: float, work_dir: Path) -> Path:
    """Returns path to chat_peaks.json."""
```

**Implementation:**
- Bin messages into 2-second buckets across the VOD timeline
- Compute messages-per-second per bucket
- Also compute "hype-weighted" rate where each message is weighted by:
  - 1.0 baseline
  - +2.0 if it matches the hype regex: `\b(KEKW|LULW|PogChamp|POG|OMEGALUL|LMAO|LOL|W|WTF|HOLY|JESUS|NO WAY|LETS GO|LETSGO|GG)\b`
  - +3.0 if the message is ALL CAPS and >3 chars
- Find peaks using `scipy.signal.find_peaks` on the hype-weighted series with `prominence=baseline*2, distance=15` (15 buckets = 30s minimum gap)
- For each peak, define the window as ±15 seconds from peak center, then refine: extend the end forward while the rate stays above baseline*1.5 (catches sustained reactions)
- Output: list of `{"t_start": float, "t_end": float, "msg_count": int, "hype_score": float, "top_emotes": [str, ...]}`

### 6.6 `candidates.py`

**Responsibility:** Merge audio + chat peaks into candidate clip windows.

**Interface:**
```python
def build_candidates(audio_peaks_path: Path, chat_peaks_path: Path, work_dir: Path) -> Path:
    """Returns path to candidates.json."""
```

**Logic:**
- A candidate exists when an audio peak and chat peak overlap (or are within 5 seconds of each other)
- Chat peaks that have no audio peak nearby are ALSO kept, but flagged with `signal: ["chat_only"]` — VTuber audiences sometimes react to visual things the audio doesn't catch
- Merge overlapping candidates into one
- Cap windows at 90 seconds max; expand to at least 25 seconds min by padding evenly on both sides
- Output:
  ```json
  [
    {
      "id": "c001",
      "t_start": 1234.5,
      "t_end": 1267.0,
      "signals": ["audio", "chat"],
      "audio_intensity": 14.2,
      "chat_hype_score": 87.3,
      "msg_count": 142,
      "top_emotes": ["KEKW", "LULW", "OMEGALUL"]
    }
  ]
  ```

This is the module to **unit test** — feed it synthetic peak inputs and verify the merge logic.

### 6.7 `rank.py`

**Responsibility:** Use an LLM to score each candidate, pick clean in/out points, and write a TikTok title.

**Interface:**
```python
class Ranker(Protocol):
    def rank(self, candidates: list[Candidate], context: TranscriptContext) -> list[RankedClip]: ...

class OllamaRanker:   # default, free
    model: str = "llama3.1:8b"
    base_url: str = "http://localhost:11434"

class AnthropicRanker:   # optional, requires ANTHROPIC_API_KEY
    model: str = "claude-haiku-4-5-20251001"
```

**For each candidate:**
- Pull the transcript text for `[t_start - 5, t_end + 5]` from `transcript.json`, with word-level timestamps preserved
- Pull the chat messages for the same window
- Build a prompt containing:
  - Candidate metadata (signals, scores, top emotes)
  - Windowed transcript (with timestamps)
  - Windowed chat (max 30 messages, sample if more)
- Ask the LLM to return JSON with: `score` (0-100), `t_start_refined` (snap to a clean sentence boundary using the word timestamps), `t_end_refined` (same), `hook_quality` (0-10), `standalone` (bool — does the clip make sense without the surrounding context?), `title` (TikTok-ready, ≤60 chars), `reason` (one sentence)

**Prompt template** (keep this in `rank.py` as a constant — Claude Code should not redesign it):

```
You are a viral short-form video editor. You're picking clips from a VTuber stream
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
{
  "score": int,
  "t_start_refined": float,
  "t_end_refined": float,
  "hook_quality": int,
  "standalone": bool,
  "title": str,
  "reason": str
}
```

**After ranking all candidates:**
- Filter to `score >= 60 AND standalone == True`
- Sort by score descending
- Take top N (configurable, default 20)
- Write `ranked.json`

**Ollama call shape:**
```python
import httpx
r = httpx.post(
    f"{base_url}/api/chat",
    json={
        "model": self.model,
        "messages": [{"role": "user", "content": prompt}],
        "format": "json",     # forces JSON output on Ollama
        "stream": False,
    },
    timeout=120,
)
```

### 6.8 `face_track.py`

**Responsibility:** For each ranked clip, sample the video at 2 fps, run MediaPipe Face Detector, and write a per-clip face-track series plus a summary used by `layout.py` to classify the clip's layout mode.

**Interface:**
```python
def track_face(video_path: Path, ranked_path: Path, work_dir: Path) -> Path:
    """Returns path to face_track.json with per-clip track series and summary."""
```

**Implementation:**
- For each ranked clip, sample 2 fps from the source video using OpenCV (`cv2.VideoCapture`)
- Run MediaPipe Face Detector (`mp.solutions.face_detection`, min_detection_confidence=0.3)
- For each sampled frame, record `{t, x, y, bbox_w, bbox_h}` where coordinates are normalized to [0, 1]. All four values are `None` when MediaPipe missed the frame (no carry-forward — `None` is the honest signal).
- Compute a per-clip summary: `avg_x`, `avg_y`, `avg_bbox_w`, `avg_bbox_h` (averaged over detected frames only), and `hit_rate` (fraction of sampled frames where a face was found).

**Per-clip schema:**
```json
{
  "c001": {
    "fps_sampled": 2,
    "track": [
      {"t": 0.0, "x": 0.52, "y": 0.31, "bbox_w": 0.41, "bbox_h": 0.38},
      {"t": 0.5, "x": null, "y": null, "bbox_w": null, "bbox_h": null},
      {"t": 1.0, "x": 0.53, "y": 0.30, "bbox_w": 0.40, "bbox_h": 0.37}
    ],
    "summary": {
      "avg_x": 0.525,
      "avg_y": 0.305,
      "avg_bbox_w": 0.405,
      "avg_bbox_h": 0.375,
      "hit_rate": 0.667
    }
  }
}
```

**Layout modes** (classified by `layout.classify_layout` in `layout.py`):
- `tracking` — face bbox width ≥ 0.25 of frame width; full-avatar mode, vertical-stripe crop follows face x-center.
- `stacked` — face bbox is smaller (< 0.25); corner-cam over gameplay; output is game letterboxed top + avatar zoomed bottom via vstack, producing 1080×1920.
- `static` — hit_rate < 0.50; face detection unreliable; fixed right-third crop fallback.

`face_track.py` runs as a pipeline stage immediately after `rank.py`. `face_track.json` ships in `work/<vod>/` alongside the other intermediate files — make this fallback configurable in `config.toml`.

### 6.9 `preview_export.py`

**Responsibility:** Fast 540×960 NVENC preview encodes with no captions burned. Reads `ranked.json` + `video.mp4`; writes `work/<vod>/previews/<id>.mp4`. See `plan-a-interaction.md` Task 6. Uses shared `encode_clip` + `PREVIEW` profile from `clipper.util.ffmpeg`.

### 6.10 `finalize.py`

**Responsibility:** Full-quality 1080×1920 re-encode of clips marked kept in `review_state.json`. Supports `caption_mode` burned/clean/both. Writes `out/<vod>/final/<NN>_<slug>.mp4` + `manifest.json`. See `plan-a-interaction.md` Task 12.

### 6.11 `captions.py`

**Responsibility:** `AssBuilder` class + `generate_srt` + `generate_basic_ass`. Plan A ships the basic non-animated style only; animated styles (window3, single, karaoke, stacked2) are Plan B.

### 6.12 `web.py`

**Responsibility:** FastAPI + uvicorn server with 6 endpoints: `GET /api/clips`, `PUT /api/clips/{id}`, `GET /api/clips/{id}/preview.mp4`, `GET /api/clips/{id}/transcript`, `POST /api/finalize` (SSE), `POST /api/shutdown`. State persisted to `review_state.json`. 30-min idle timeout.

### 6.13 `effects/` package

**Responsibility:** `FinalizeEffect` Protocol + four concrete effects shipped in Plan B: `punch_zoom`, `emoji_burst`, `hook_card`, `reaction_zoom`. Each mutates a shared `EffectContext` (AssBuilder + extra_filters). Registry in `effects/registry.py`. See `plan-b-effects.md` for implementation detail.

### 6.14 `layout.py`

Maps a face-track per-clip summary to a `LayoutMode`:
- `tracking` when face bbox width >= 0.25 of frame width (full avatar mode)
- `stacked` when face bbox is smaller (corner cam over gameplay)
- `static` when face detection hit rate < 0.50 (fallback)

`classify_layout(summary, *, tracking_bbox_threshold=0.25, min_hit_rate=0.50) -> LayoutMode`.

### 6.15 `main.py`

CLI built with `click`:

```bash
clipper run <twitch_url>                    # full pipeline
clipper run <twitch_url> --skip-download    # reuse cached video
clipper run <twitch_url> --max-clips 10
clipper run <twitch_url> --ranker anthropic # swap from default ollama
clipper rank-only <vod_id>                  # rerun just the ranking step
clipper export-only <vod_id>                # rerun just the export step
```

Each stage writes its output to `work/<vod_id>/` and the next stage reads it. If a stage's output file exists, skip it unless `--force` is passed. This makes the pipeline resumable when something fails 80% through a 4-hour transcribe.

Use `rich.progress` for the progress bars.

---

## 7. Config (`config.toml`)

```toml
[download]
quality = "1080p60"

[transcribe]
model = "distil-large-v3"   # or "large-v3" for non-English
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
backend = "ollama"          # "ollama" | "anthropic"
ollama_model = "llama3.1:8b"
anthropic_model = "claude-haiku-4-5-20251001"
max_clips = 20
min_score = 60

[export]
output_width = 1080
output_height = 1920
nvenc_preset = "p5"
nvenc_bitrate = "6M"
fallback_crop_x_fraction = 0.66  # right-third fallback when no face detected
caption_style = "Fontname=Arial Black,Fontsize=18,PrimaryColour=&Hffffff,OutlineColour=&H000000,Outline=3,Shadow=0,Alignment=2,MarginV=200"

[finalize]
caption_style = "window3"      # window3 | basic  (other animated styles deferred)
caption_mode = "burned"        # burned | clean | both
server_port_start = 8765
server_port_end = 8800
idle_timeout_seconds = 1800
```

---

## 8. Acceptance Criteria for v0

A successful first runnable version meets all of these:

1. `clipper run <twitch_url>` runs end-to-end on a real 1–4 hour VTuber VOD without crashing.
2. The pipeline is idempotent and resumable — re-running after a crash skips completed stages.
3. Each intermediate file (`audio_peaks.json`, `chat_peaks.json`, `candidates.json`, `ranked.json`) is human-readable JSON.
4. The default ranker is Ollama (free). Anthropic ranker works when `ANTHROPIC_API_KEY` is set and `--ranker anthropic` is passed.
5. Output clips are 1080×1920 MP4s, ≤90 seconds, with the avatar's face roughly centered in the crop and readable burned-in captions.
6. `out/<vod_id>/manifest.json` lists every clip with title, score, source timestamps, and reason.
7. The `candidates.py` peak-merge logic has at least one unit test with synthetic inputs.
8. README documents: install steps, the one-command pipeline, how to swap rankers, where outputs land.
9. `clipper review <vod_id>` launches the browser-based two-pane review UI; edits (title, trim, kept, caption_mode) persist to `review_state.json` and survive server restart.
10. Clicking Finalize re-encodes only kept clips to `out/<vod_id>/final/` with a manifest.
11. With default effects enabled, finalize manifest's `effects_applied` lists `captions`, `punch_zoom`, `hook_card`, `reaction_zoom`, and `emoji_burst` (when the clip has chat peaks).
12. Per-clip effect overrides via the review UI are honored at finalize.
13. `clipper run <twitch_url>` runs the M1-M4 pipeline (download → chat → transcribe → peaks → candidates → rank) end-to-end before launching the review UI.
14. Each upstream stage is idempotent — re-running with the same work dir skips completed stages.
15. `face_track.py` runs as a pipeline stage; `face_track.json` ships in `work/<vod>/` alongside the other intermediate files.
16. `finalize` honors per-clip `layout` overrides; stacked-mode clips produce 1080×1920 output via vstack (game top + avatar bottom).

**Out of scope for v0 (note for later):**
- Per-frame dynamic crop tracking (use single weighted x for now)
- Auto-upload to TikTok/YouTube Shorts
- Multi-VOD batching
- Web UI
- JP language support

---

## 9. Implementation Notes & Gotchas

- **VRAM contention:** `faster-whisper` with `float16` on the large-v3 distil model uses ~4–5 GB. MediaPipe is CPU-fine. The 3080 has 10 GB so there's no conflict, but don't try to run Ollama with `llama3.1:8b` (which wants ~6 GB) at the same time as Whisper. Stage them sequentially — Whisper finishes long before ranking starts, and the pipeline already runs them in order.
- **NVENC quality:** `-preset p5` is the sweet spot. `p7` (slowest) is barely better and 3× slower. `p1`–`p3` look noticeably worse.
- **Caption timing:** when generating per-clip SRTs, subtract `t_start_refined` from every word timestamp so captions start at 0 in clip-local time. This is the #1 thing that breaks first-time implementations.
- **Twitch VOD expiry:** the user's VOD URL works today (May 2026) but Twitch deletes non-highlight VODs after 14–60 days. Don't bake the URL into tests — make the pipeline fail gracefully if `yt-dlp` returns 404 and tell the user the VOD has expired.
- **chat-downloader auth:** for public VODs no auth is needed. For sub-only VODs the user would need to pass cookies. Don't worry about that in v0.
- **Idempotency check:** use the existence of the output file as the skip signal, but compare a hash of relevant config to detect when settings changed (e.g., user lowered `min_score` and wants to re-rank). Store config hash in a `.stage_meta.json` per stage.
- **Don't shell out to yt-dlp for the audio extraction step** — go through ffmpeg on the already-downloaded video. Re-downloading audio from Twitch wastes bandwidth and triggers a second auth handshake.
- **MediaPipe model:** use the "short range" face detector (`model_selection=0`), not the full-range one. VTuber webcam cutouts are close-up.
- **Hype regex is conservative on purpose** — better to miss some chat spikes than to false-positive on every "lol". Tune by inspecting `chat_peaks.json` after the first run.

---

## 10. First-run Smoke Test

After Claude Code finishes the build, the user should be able to run:

```powershell
# one-time setup
cd vtuber-clipper
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
ollama pull llama3.1:8b

# run on the user's actual VOD
clipper run https://www.twitch.tv/videos/2762489406
```

Expected wall-clock on the user's machine (RTX 3080, 4-hour VOD):
- Download: 15–25 min (network-bound, ~25 GB)
- Audio extract: 1–2 min
- Chat download: 1–3 min
- Transcribe (distil-large-v3): 8–15 min
- Audio + chat peaks: <1 min
- Candidates: instant
- Rank (Ollama): 2–5 min depending on candidate count
- Face track + export (20 clips): 3–6 min

Total: roughly 30–55 minutes for a 4-hour VOD, output in `out/2762489406/clips/`.

---

## 11. What to Build First

Suggested implementation order so the user can see something running quickly:

1. `download.py` + `chat.py` — prove yt-dlp and chat-downloader work on the target VOD
2. `audio_peaks.py` + `chat_peaks.py` + `candidates.py` — get a list of candidate windows printed to console
3. `transcribe.py` — add the transcript
4. `rank.py` with Ollama — get ranked titles printed
5. `export.py` with static center-crop and burned captions — first watchable clips
6. `face_track.py` and dynamic crop — final polish

Land step 5 before step 6. A static-cropped clip with good content beats a perfectly-tracked clip from a bad moment.