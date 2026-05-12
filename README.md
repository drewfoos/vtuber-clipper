# VTuber Clipper

Local tool that ingests a Twitch VTuber VOD and produces 10-20 9:16 short-form clips
with burned-in captions. Pipeline runs end-to-end on a single PC; no paid APIs.

## Status: Plan A + Plan B + M1-M4 complete; ready for end-to-end VOD runs.

- Spec: `spec.md`
- Architecture: `architecture.md`
- Research notes & env setup: `research.md`
- Milestones: `MILESTONES.md`
- Interaction design: `interaction-design.md`
- Implementation plan (current): `plan-a-interaction.md`

## Plan B (animated captions + effects)

Plan B ships `window3` animated captions and four effects (`punch_zoom`,
`emoji_burst`, `hook_card`, `reaction_zoom`). Each is toggleable per-clip in
the review UI. Effects gracefully no-op when their input peak data is missing
(M1-M4 upstream will produce it; today, use the test fixtures).

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
