# VTuber Clipper

Local tool that ingests a Twitch VTuber VOD and produces 10-20 9:16 short-form clips
with animated burned-in captions, motion effects, and layout-aware cropping.
Pipeline runs end-to-end on a single PC; no paid APIs.

**Status:** Plan A + Plan B + M1-M4 + M6 complete — full-feature v0 ready.

## Quick start

Prereqs (see `research.md` §1 for full env-verification commands):
- Windows 11 / Linux / macOS
- Python 3.11 or 3.12
- ffmpeg with NVENC + libass on PATH
- NVIDIA GPU with CUDA (or edit `config.toml` to use CPU)
- Ollama with `llama3.1:8b` pulled (or `--ranker anthropic` with `ANTHROPIC_API_KEY`)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
pytest

# Full pipeline on a real Twitch VOD (downloads → transcribes → ranks → opens review UI):
clipper run https://www.twitch.tv/videos/<id>

# Headless: run the pipeline without launching the review browser
clipper run https://www.twitch.tv/videos/<id> --no-review

# Re-open the review UI for an already-processed VOD
clipper review <vod_id>

# Headless finalize using the latest review_state.json
clipper finalize --work-dir work/<vod_id> --out-dir out/<vod_id>

# Use Anthropic instead of Ollama for ranking
ANTHROPIC_API_KEY=... clipper run https://www.twitch.tv/videos/<id> --ranker anthropic
```

After the pipeline finishes the review UI opens in your browser. Review the 10-20
clip candidates, edit titles/trim, toggle effects + layout per clip, click
**Finalize**. Final MP4s land in `out/<vod_id>/final/` ready to post.

## What it does

```
Twitch VOD URL
   ↓
1. download         (yt-dlp → video.mp4 + Opus audio)
2. chat             (chat-downloader → chat.jsonl)
3. transcribe       (faster-whisper distil-large-v3 → word-level transcript)
4. audio_peaks      (ffmpeg astats → RMS spike detection)
5. chat_peaks       (hype-regex + scipy.find_peaks)
6. candidates       (overlap-merge audio + chat peaks)
7. rank             (Ollama llama3.1:8b OR Anthropic Claude → scored clips)
8. face_track       (MediaPipe Tasks API → per-clip face center series)
9. preview_export   (fast 540×960 NVENC previews)
   ↓
Browser opens for review (FastAPI + vanilla JS UI)
   ↓
User clicks Finalize
   ↓
10. finalize        (1080×1920 NVENC + animated ASS captions + effects + layout)
   ↓
out/<vod_id>/final/*.mp4 + manifest.json
```

## Features at finalize

**Animated captions** (Plan B): `window3` style — 3-word sliding window with the
active word highlighted in yellow at slight scale-up. Burned via libass.
Per-clip toggleable: `burned` / `clean + sidecar SRT` / `both`.

**Four motion-graphics effects** (Plan B), per-clip toggleable:
- `punch_zoom` — sinusoidal scale ramp on audio peaks ≥ 8 dB
- `emoji_burst` — deterministic Twemoji PNG overlay at chat peaks
- `hook_card` — "WAIT FOR IT" overlay first 1.5s when LLM hook_quality ≥ 7
- `reaction_zoom` — 10% tighter crop at the biggest combined peak

**Three output layouts** (M6), auto-detected from face bbox size or overridden in UI:
- **Tracking** — vertical-stripe crop biased toward the avatar's x-position (full-avatar streams)
- **Stacked** — game letterboxed top + avatar zoomed bottom (corner-cam gameplay)
- **Static** — fixed right-third crop fallback (face detection failed)

## Documentation map

| File | What's in it |
|---|---|
| `spec.md` | Full v0 build spec — modules, data contracts, config, acceptance criteria |
| `architecture.md` | System diagram, module responsibilities, idempotency model, failure modes |
| `research.md` | Env verification, cuDNN footgun, mediapipe/3D avatar notes, pre-build spikes |
| `MILESTONES.md` | M0-M7 milestone breakdown with deliverables + validation |
| `interaction-design.md` | Web review UI design — endpoints, layout, state persistence |
| `changelog.md` | Decisions log + planning entries |
| `plan-a-interaction.md` | Plan A — core review pipeline (preview_export + web + finalize) |
| `plan-b-effects.md` | Plan B — animated captions + 4 motion effects |
| `plan-c-upstream.md` | Plan C — M1-M4 upstream (download/chat/transcribe/peaks/rank) |
| `plan-d-m6.md` | Plan D — M6 face tracking + stacked layout |

## Configuration

`config.toml` at the project root drives every stage. Common knobs:
- `[transcribe] model` — `distil-large-v3` (default) or `large-v3` for non-English
- `[transcribe] device` — `cuda` (default) or `cpu`
- `[rank] backend` — `ollama` (default) or `anthropic`
- `[rank] min_score` — drop candidates the LLM scores below this (default 60)
- `[finalize] caption_style` — `window3` (default) or `basic`
- `[finalize] caption_mode` — `burned` / `clean` / `both`
- `[chat_peaks] hype_regex` — regex of Twitch emote / hype words to weight messages

## Project state at a glance

- **Lines of code:** ~3,000 across 19 production modules
- **Tests:** 133 passing (130 fast + 3 slow integration)
- **Pipeline stages:** 10
- **Output layouts:** 3 (tracking / stacked / static)
- **Caption styles shipped:** `basic` + `window3` (animated)
- **Effects shipped:** 4 (punch_zoom, emoji_burst, hook_card, reaction_zoom)
