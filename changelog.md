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

### Not yet built
- Any module code. Build starts after M0 spikes pass.

---

## Conventions

- **Unreleased** holds work-in-progress changes since the last tagged release. On release, move the section under a new `## [X.Y.Z] — YYYY-MM-DD` heading and start a fresh `## [Unreleased]`.
- Each entry is one bullet, present tense, user-visible framing where relevant ("captions sync within one frame", not "fixed timing math in export.py").
- Categories: **Added** / **Changed** / **Fixed** / **Removed** / **Deprecated** / **Security**. While pre-v0, also use **Planning** and **Decisions** for non-code changes.
- Link issues/PRs inline when they exist: `- Fixed cuDNN load on Windows (#42)`.
- Don't log dev-only churn (test-file moves, lint passes, doc typo fixes). Things the user would care about.
