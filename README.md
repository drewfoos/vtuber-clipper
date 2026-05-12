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
