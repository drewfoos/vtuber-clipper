# VTuber Clipper — Architecture

Companion to `spec.md` (the *what to build*) and `research.md` (the *unknowns*). This doc is the *how it fits together* — the data flow, contracts between modules, and cross-cutting concerns.

---

## 1. Design Principles

1. **Pipeline of pure-ish stages.** Each module reads files, writes files. No shared in-memory state between stages. Lets us debug, resume, and replay any stage in isolation.
2. **Disk is the integration bus.** Intermediate state is human-readable JSON (or JSONL for chat). If a stage is broken, the output of the prior stage is right there to inspect or feed to a different implementation.
3. **Idempotency by default.** Re-running the pipeline skips completed stages. Config changes invalidate only the affected stages and their downstream consumers. See §6.
4. **Free path is the default path.** Ollama + local Whisper + MediaPipe. Cloud APIs (Anthropic) are opt-in and configured the same way as Ollama — interchangeable backends behind a `Protocol`.
5. **Time is in source-video seconds everywhere except SRT files.** One coordinate system removes a whole category of bugs. See §5.
6. **No premature abstraction.** v0 uses static crop, single ranker call per candidate, sequential stages. Pluggable face detectors and dynamic crop come in M6. Don't build seams the spec doesn't require.

---

## 2. System Diagram

```
                ┌──────────────────────────────────────┐
                │       Twitch VOD URL (input)         │
                └──────────────────┬───────────────────┘
                                   │
                ┌──────────────────┴──────────────────┐
                │                                     │
                ▼                                     ▼
        ┌──────────────┐                      ┌──────────────┐
        │  download    │── video.mp4 ───┐     │    chat      │
        │              │                │     │              │
        │              │── audio.opus ──┤     │              │── chat.jsonl ──┐
        └──────────────┘                │     └──────────────┘                │
                                        │                                     │
                                        ▼                                     │
                                ┌──────────────┐                              │
                                │  transcribe  │── transcript.json ─┐        │
                                └──────────────┘                    │        │
                                        │                           │        │
                                        ▼                           │        │
        ┌──────────────┐                                            │        │
        │ audio_peaks  │── audio_peaks.json ──┐                     │        │
        └──────────────┘                      │                     │        │
                                              ▼                     │        │
                                      ┌──────────────┐              │        │
              ┌─── chat_peaks.json ─→ │  candidates  │              │        │
              │                       │              │── candidates.json ──┐ │
        ┌──────────────┐              └──────────────┘                     │ │
        │  chat_peaks  │←─── chat.jsonl ──────────────────────────────────────┘
        └──────────────┘                                                   │
                                                                           ▼
                                                              ┌─────────────────────┐
                                                              │       rank          │
                                                              │ (Ollama/Anthropic)  │
                                                              │   reads:            │
                                                              │   - candidates.json │
                                                              │   - transcript.json │
                                                              │   - chat.jsonl      │
                                                              └──────────┬──────────┘
                                                                         │
                                                                  ranked.json
                                                                         │
                                                                         ▼
                                                              ┌─────────────────────┐
                                                              │     face_track      │
                                                              │ (MediaPipe/YuNet)   │
                                                              │   reads:            │
                                                              │   - video.mp4       │
                                                              │   - ranked.json     │
                                                              └──────────┬──────────┘
                                                                         │
                                                                 face_track.json
                                                                         │
                                                                         ▼
                                                              ┌─────────────────────┐
                                                              │   preview_export    │
                                                              │ (540×960, no caps)  │
                                                              │   reads:            │
                                                              │   - video.mp4       │
                                                              │   - ranked.json     │
                                                              └──────────┬──────────┘
                                                                         │
                                                              work/<vod>/previews/*.mp4
                                                                         │
                                                                         ▼
                                                              ┌─────────────────────┐
                                                              │  web (FastAPI +     │
                                                              │    browser UI)      │
                                                              │  review_state.json  │
                                                              └──────────┬──────────┘
                                                                         │
                                                                         ▼
                                                              ┌─────────────────────┐
                                                              │     finalize        │
                                                              │ (1080×1920, capts)  │
                                                              │   reads:            │
                                                              │   - video.mp4       │
                                                              │   - review_state    │
                                                              │   - transcript.json │
                                                              └──────────┬──────────┘
                                                                         │
                                                                         ▼
                                                              out/<vod>/final/*.mp4
                                                              out/<vod>/final/manifest.json
```

Dependency direction is one-way: downstream stages read upstream outputs. No cycles. No stage writes to another stage's output directory.

---

## 3. Module Responsibilities (one-line each)

| Module | Reads | Writes | Notes |
|---|---|---|---|
| `download.py` | URL | `video.mp4`, `audio.opus` | yt-dlp Python API wrapper; downloads VOD and extracts low-bitrate Opus audio via ffmpeg. |
| `chat.py` | URL | `chat.jsonl` | chat-downloader wrapper; writes lean JSONL `{t, user, msg}`. |
| `transcribe.py` | `audio.opus` | `transcript.json` | faster-whisper word-level transcript with explicit VRAM release. |
| `audio_peaks.py` | `audio.opus` | `audio_peaks.json` | ffmpeg astats RMS parser + rolling-median-baseline peak detection. |
| `chat_peaks.py` | `chat.jsonl` | `chat_peaks.json` | 2-second bucket hype-weighted rate + scipy peak finding. |
| `candidates.py` | both peak files | `candidates.json` | overlap-merges audio + chat peaks into candidate windows with min/max duration enforcement. |
| `rank.py` | `candidates.json`, `transcript.json`, `chat.jsonl` | `ranked.json` | Ranker Protocol + OllamaRanker (default, free) + AnthropicRanker (opt-in cloud); JSON-extracting LLM call per candidate. |
| `config.py` | `config.toml` | — | pydantic Config from `config.toml` at repo root. |
| `face_track.py` | `video.mp4`, `ranked.json` | `face_track.json` | per-clip MediaPipe sampling at 2 fps; writes face center series + summary (avg_x, avg_y, avg_bbox_w, hit_rate) to `face_track.json`. |
| `layout.py` | `face_track.json` (summary) | — | classifies per-clip layout from face-track summary (tracking / stacked / static). |
| `preview_export.py` | `video.mp4`, `ranked.json` | `previews/<id>.mp4` | fast 540×960 NVENC previews, no captions; shared `encode_clip` + `PREVIEW` profile |
| `finalize.py` | `video.mp4`, `review_state.json`, `transcript.json` | `final/<NN>_<slug>.mp4`, `manifest.json` | full-quality 1080×1920 re-encode of kept clips; burned/clean/both caption modes |
| `captions.py` | `transcript.json` | `.ass`, `.srt` | `AssBuilder` + `generate_srt` + `generate_basic_ass`; Plan A basic style only |
| `web.py` | `ranked.json`, `previews/`, `review_state.json` | `review_state.json` | FastAPI + uvicorn localhost server; 6 endpoints; SSE finalize progress; 30-min idle timeout |
| `effects/` | — | — | `FinalizeEffect` Protocol + 4 concrete effects (`punch_zoom`, `emoji_burst`, `hook_card`, `reaction_zoom`). Each mutates a shared `EffectContext` (AssBuilder + extra_filters). Registry in `effects/registry.py`. |

Detail beyond one line lives in `spec.md` §6.

---

## 4. Data Contracts (the seams)

Stages talk through these files only. Schema changes here cascade — bump the relevant module's `SCHEMA_VERSION` constant.

### `chat.jsonl` (one JSON object per line)
```json
{"t": 1234.56, "user": "viewer123", "msg": "KEKW HOLY"}
```

### `transcript.json`
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

### `audio_peaks.json` / `chat_peaks.json` / `candidates.json` / `ranked.json` / `face_track.json` / `manifest.json`
See `spec.md` §6 for shapes. All times are source-video seconds. All filenames slugify clip titles using a single shared helper in `util/timing.py` (despite the name — keep slug there for now, it's tiny).

### `.stage_meta.json` (one per stage output)
```json
{
  "stage": "audio_peaks",
  "schema_version": "0.1.0",
  "config_hash": "<sha256 of [audio_peaks] config section only>",
  "input_hashes": {"audio.opus": "<mtime>:<size>"},
  "completed_at": "2026-05-11T12:34:56Z"
}
```

Hash strategy is in `research.md` §6.

---

## 5. Cross-Cutting Conventions

### Time
- **Source-video seconds** everywhere on disk. `t=0` is the first frame of `video.mp4`.
- **Clip-local seconds** only inside SRT/ASS files produced for caption burn-in. The conversion is `t_local = t_source - t_start_refined`. Caption-timing test (`tests/test_caption_timing.py`) is the regression guard.
- All timestamp fields are `float` (seconds). Never store ms unless the source library forces it — convert at the boundary.

### Configuration
- One `config.toml` at project root. Each section maps to one module: `[download]`, `[transcribe]`, `[audio_peaks]`, etc.
- A stage hashes **only its own section** for `config_hash`. Tweaking `[export]` does not invalidate `[transcribe]`'s cache.
- Env-var overrides for secrets only (`ANTHROPIC_API_KEY`). Config values go in TOML.

### Errors
- Stages raise on unrecoverable failure; the CLI translates to a non-zero exit and a human message.
- Per-candidate failures in `rank.py` log + skip, never crash. (One bad LLM response shouldn't kill a 4-hour pipeline.)
- Per-clip failures in `export.py` log + skip. `manifest.json` lists only successful exports.
- Twitch VOD 404 produces a specific message ("VOD has expired") — not a stack trace.

### Logging & Progress
- `rich.progress` for any stage that takes > 5 seconds.
- One `logger` per module via `clipper.util.logging.get_logger(__name__)`.
- No print statements outside the CLI entry point.

### VRAM
- Stages that load CUDA models (`transcribe`, possibly `face_track`) release before exit: `del model; gc.collect()`.
- Whisper and Ollama never run concurrently (the spec already orders them; just don't accidentally parallelize them later).

---

## 6. Idempotency Model

The skip-or-rerun decision per stage:

```
INPUTS:  output file exists?
         .stage_meta.json exists and parseable?
         meta.schema_version == module's SCHEMA_VERSION?
         meta.config_hash == hash of current [section]?
         meta.input_hashes match current inputs?

DECISION: skip if and only if ALL true.
          otherwise: delete .stage_meta.json (NOT the output — user may want to diff)
                     and re-run.
```

CLI overrides:
- `--force` re-runs the explicitly-named stage regardless of meta.
- `--force-from <stage>` re-runs `<stage>` and every downstream stage.

This is implemented once in a `util/staging.py` helper, not duplicated per module.

`finalize` is driven by `review_state.json` rather than config-hash, since user intent (kept/edit decisions) is the input. Config hash still covers ffmpeg/caption settings, but the "what to encode" decision comes from the review state file.

Every M1-M4 module uses the existence of its output file as the skip signal. There's no per-stage config-hash check yet — that's a future polish item. For now, `--force` is the escape hatch (rerunning manually after deleting the output file).

---

## 7. Resource Budget (4-hour 1080p60 VOD, RTX 3080)

| Stage | Wall clock | Peak VRAM | Peak disk |
|---|---|---|---|
| download | 15–25 min | 0 | +25 GB video |
| audio extract | 1–2 min | 0 | +80 MB opus |
| chat download | 1–3 min | 0 | +50 MB jsonl |
| transcribe | 8–15 min | ~5 GB | +5 MB json |
| audio_peaks | <1 min | 0 | +1 MB json |
| chat_peaks | <1 min | 0 | +0.5 MB json |
| candidates | seconds | 0 | +0.1 MB json |
| rank (Ollama) | 2–5 min | ~6 GB | +0.1 MB json |
| rank (Anthropic) | 1–2 min | 0 | same |
| face_track | 1–2 min | ~0.5 GB | +1 MB json |
| export (20 clips) | 3–6 min | ~1 GB | +400 MB clips |

Total: ~30–55 min, ~26 GB peak disk in `work/`, ~400 MB final output. Per `spec.md` §10.

---

## 8. Failure-Mode Map

What breaks where, and what the user sees:

| Failure | Stage | Surface to user |
|---|---|---|
| Twitch URL invalid | download | "Bad URL format. Expected https://www.twitch.tv/videos/<id>" |
| VOD deleted/expired | download | "VOD has expired (Twitch returned 404)" |
| Disk full | download or export | Pre-flight check fails before download starts |
| cuDNN DLLs not found | transcribe | "faster-whisper failed to load CUDA. See research.md §1." Startup smoke catches this. |
| Ollama not running | rank | "Ollama daemon not reachable at :11434. Start with `ollama serve`." |
| No face detected anywhere in a clip | face_track | Auto-fallback to static crop, logged as warning |
| ffmpeg lacks libass | export | Env-check at startup catches this |
| Sub-only VOD (no chat replay) | chat | "Chat replay disabled. Re-run with `--no-chat-signal` to skip." |

---

## 9. Open Architectural Questions

Things we deliberately defer because v0 doesn't require resolution:

- **Process isolation for Whisper vs Ollama?** A subprocess wrapper would guarantee VRAM release. Today's sequential-in-one-process design works because we explicitly del. Revisit if VRAM contention bites.
- **Parallel candidate ranking?** Could parallelize Ollama calls 2-3x with `httpx.AsyncClient` + concurrency limit. Not needed for v0's 2–5 min ranking.
- **Per-clip dynamic crop interpolation strategy.** `sendcmd` does linear by default; spline might look smoother. Defer until M6 is in user hands.
- **Multiple-VOD batch mode.** Each VOD's pipeline state is in `work/<vod_id>/`, which already supports it — the CLI just doesn't expose a batch verb yet.

---

## 10. Where to Read Next

- Building a specific module → `spec.md` §6
- Got an error → `research.md` §1 (env) and §8 (risks)
- Deciding what to build now → `MILESTONES.md`
- What changed recently → `changelog.md`

---

## 11. Web Layer

`web.py` provides a localhost-only FastAPI + uvicorn server bound to `127.0.0.1` on a port found free in the `[finalize] server_port_start`–`server_port_end` range.

**Endpoints** (per `plan-a-interaction.md` §3):
- `GET /api/clips` — list all clips from `ranked.json` merged with `review_state.json`
- `PUT /api/clips/{id}` — update a clip's title, trim, kept flag, or caption_mode; round-trips `review_state.json` immediately
- `GET /api/clips/{id}/preview.mp4` — serve the preview MP4 with HTTP Range support for seek-capable browser playback
- `GET /api/clips/{id}/transcript` — return the windowed transcript for the clip
- `POST /api/finalize` — trigger `finalize.py`; streams progress as SSE events until done or error
- `POST /api/shutdown` — graceful server shutdown (called by the CLI on Ctrl-C or idle timeout)

**State persistence:** every `PUT` writes through to `review_state.json` synchronously before returning 200. The server re-reads `review_state.json` at startup, so edits survive a restart.

**Idle timeout:** the server shuts down after 30 minutes of no HTTP activity (configurable via `[finalize] idle_timeout_seconds`). The CLI also shuts the server on Ctrl-C.

Per-clip `effects` dict and `caption_style` field are persisted to `review_state.json` and override registry defaults at finalize time.

Per-clip `layout` field on ClipState (auto/tracking/stacked/static) gives the user override control; defaults to auto, resolved via `layout.classify_layout` at finalize.
