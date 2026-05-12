# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Dates are ISO 8601 (YYYY-MM-DD).

---

## [Unreleased]

### Planning
- `spec.md` — full v0 build spec covering architecture, module specs, data contracts, config, and acceptance criteria
- `research.md` — pre-build research: env verification, cuDNN-on-Windows footgun + three fixes, 3D-vs-2D face-detection risk re-rating, pluggable `FaceDetector` design, ffmpeg `astats` parsing and `sendcmd` syntax, schema fixes, idempotency design, testing strategy, two pre-build spikes
- `architecture.md` — system view: design principles, data flow diagram, module responsibilities, data contracts, cross-cutting conventions (time origin, config, errors, VRAM), resource budget, failure-mode map
- `MILESTONES.md` — M0 spikes → M7 polish, each with acceptance criteria and validation steps
- `plan-a-interaction.md` — implementation plan for the core review pipeline + finalize
- `plan-b-effects.md` — implementation plan for animated captions + 4 motion effects.
- `plan-c-upstream.md` — implementation plan for M1-M4 upstream pipeline.

### Decisions
- **2026-05-11** — Target streamer uses a 3D face-tracked avatar (not 2D Live2D). Face-detection risk dropped from High to Low; MediaPipe is the default plan, YuNet + AnimeFaceDetector + static-crop kept as opt-in fallbacks.
- **2026-05-11** — Default ranker is Ollama (`llama3.1:8b`) for the free path. Anthropic ranker (`claude-haiku-4-5-20251001`) is opt-in via config + `ANTHROPIC_API_KEY`.
- **2026-05-11** — All on-disk timestamps in source-video seconds. Clip-local seconds only inside SRT/ASS files.
- **2026-05-11** — JSONL for `chat` output (potentially 100k+ messages, streaming-friendly), JSON for everything else (small, human-inspectable).
- **2026-05-11** — Idempotency keyed on per-section config hash + `(mtime, size)` for big files, full sha256 for small files. Stale stage deletes its `.stage_meta.json` but not the output (preserves user inspection).
- **2026-05-12** — Plan A (core review pipeline + plain captions) and Plan B (animated captions + 4 motion effects) split. Plan A ships first as an independently-useful v0.5.
- **2026-05-12** — Kept `nvidia-cudnn-cu12` as a hard runtime dependency. The project is fundamentally CUDA-only (faster-whisper with `device="cuda"`, NVENC encoding); making cuDNN optional would be misleading.
- **2026-05-12** — Plan A's `finalize.py` halts on per-clip ffmpeg failure rather than skip-and-continue. interaction-design.md §12 specifies skip-and-continue; this is deferred to Plan B / polish. Note: when one clip fails, others usually fail too (disk full, corrupted source).
- **2026-05-12** — Frontend uses `textContent` + DOM construction; `innerHTML` is forbidden (enforced by `test_static_js_served`). Clip titles flow from LLM ranker output and are treated as untrusted markup.
- **2026-05-12** — `emoji_burst` uses bundled Twemoji PNGs picked deterministically by emote-name hash, not literal emote→glyph mapping. Twitch emotes (KEKW, LULW, ...) have no Unicode equivalent, so we use a generic-reaction palette of six emojis.
- **2026-05-12** — `window3` is the only animated caption style shipped in Plan B. `single`, `karaoke`, `stacked2` from interaction-design §5 were design alternatives and remain post-Plan-B.
- **2026-05-12** — Effects gracefully no-op when their input data (audio_peaks.json / chat_peaks.json) is missing. This lets Plan B ship before M1-M4 produces real peaks.
- **2026-05-12** — `json_io.write_json` is now atomic (write-to-tmp + `os.replace`). Crash mid-write leaves the previous state file intact.
- **2026-05-12** — Discovered during Plan B integration: ffmpeg's `zoompan` filter `z=` expression doesn't expose `t`; switched `punch_zoom` and `reaction_zoom` to frame-number (`on`) at 30 fps. Also: `emoji_burst` uses named-pad syntax requiring `-filter_complex`; `encode_clip` now auto-detects.
- **2026-05-12** — `download.py` uses yt-dlp's Python API directly (not subprocess) for cleaner error handling and metadata access.
- **2026-05-12** — `transcribe.py` slow integration test uses `tiny.en` on CPU to avoid CI GPU requirements; production uses configured `distil-large-v3` on CUDA.
- **2026-05-12** — `rank.py` LLM JSON extraction (`_extract_json`) tolerates markdown fences and prose preambles around the JSON object. Real-world Ollama responses occasionally include both despite `format: "json"`.
- **2026-05-12** — `finalize.py` now skips and continues on per-clip ffmpeg failure (interaction-design.md §12); failed clips are logged and excluded from the manifest.
- **2026-05-12** — `audio_peaks.py` baseline computation uses a rolling median over a 60-second window; for shorter inputs it collapses to a global median.
- **2026-05-12** — `chat_peaks.py` uses a backward signal-walk (extend left while signal > baseline×1.5) for the peak `t_start`, replacing the plan's static -15s offset which proved too aggressive for the test fixture's compact burst.
- **2026-05-12** — `candidates.py` extends the spec with a Pass 2 loop that includes unmatched audio peaks as `signals=["audio_only"]` candidates. The spec was silent on audio-only inputs; tests required `len==1` for them.

### Not yet built
- Any module code. Build starts after M0 spikes pass.

---

## Conventions

- **Unreleased** holds work-in-progress changes since the last tagged release. On release, move the section under a new `## [X.Y.Z] — YYYY-MM-DD` heading and start a fresh `## [Unreleased]`.
- Each entry is one bullet, present tense, user-visible framing where relevant ("captions sync within one frame", not "fixed timing math in export.py").
- Categories: **Added** / **Changed** / **Fixed** / **Removed** / **Deprecated** / **Security**. While pre-v0, also use **Planning** and **Decisions** for non-code changes.
- Link issues/PRs inline when they exist: `- Fixed cuDNN load on Windows (#42)`.
- Don't log dev-only churn (test-file moves, lint passes, doc typo fixes). Things the user would care about.
