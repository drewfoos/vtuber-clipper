# VTuber Clipper — Milestones

Each milestone produces something concretely verifiable. Don't move to the next one until the current one's validation step passes on a real VOD.

Total estimate to v0 complete: **3–5 focused build sessions**, plus one ~1-hour end-to-end run on a real VOD per session.

---

## M0 — Environment & Spikes ✅ gate

**Goal:** Prove every binary in the stack works on this exact machine + streamer before any module code.

**Deliverables**
- All env-verification commands in `research.md` §1 pass
- faster-whisper CUDA smoke succeeds (no cuDNN DLL error)
- Spike 1 (MediaPipe hit-rate on real VOD frames) recorded in `notes/spike_face_results.md`
- Spike 2 (5-minute shell smoke producing `smoke_clip.mp4`) recorded with the resulting MP4 watched and confirmed playable

**Validation**
- A 30-second NVENC-encoded 9:16 MP4 exists on disk, plays in VLC, captions deferred
- Decision recorded: which face detector backend goes into `config.toml` as default

**Effort:** ~1 hour. Do not skip — this catches the cuDNN footgun before it ruins a 4-hour run.

---

## M1 — Ingestion (download + chat)

**Goal:** Given a Twitch URL, land `video.mp4`, `audio.opus`, `chat.jsonl` in `work/<vod_id>/`.

**Deliverables**
- `src/clipper/download.py` — `download_vod()` returning `DownloadResult`
- `src/clipper/chat.py` — `download_chat()` writing JSONL
- `src/clipper/main.py` — minimal CLI: `clipper run <url> --stop-after ingest`
- `src/clipper/util/timing.py` — basic seconds/timestamp helpers
- `src/clipper/util/logging.py` — rich-based progress wrapper
- Idempotency: re-running with same URL skips download if files exist

**Validation**
- `clipper run <real_url> --stop-after ingest` produces all three files
- `chat.jsonl` first/last lines have monotonic `t` fields
- `video.mp4` plays; `audio.opus` plays; both have matching durations

**Effort:** half a session.

---

## M2 — Signal Detection

**Goal:** From audio + chat, produce two peak lists and a merged candidate list.

**Deliverables**
- `src/clipper/audio_peaks.py` with `astats` log parser
- `src/clipper/chat_peaks.py` with hype-weighted bucketing + `scipy.signal.find_peaks` + `top_emotes` helper
- `src/clipper/candidates.py` with overlap-merge + min/max duration enforcement
- `.stage_meta.json` writers for each (per `research.md` §6)
- `tests/test_candidates.py`, `tests/test_chat_peaks.py`, `tests/test_audio_peaks_parse.py` all green

**Validation**
- `candidates.json` exists with 20–80 entries on a 4-hour VOD
- Spot-check 3 candidates by `t_start`: open the VOD at that timestamp, confirm something interesting is happening
- Re-running the stage with same config skips work; bumping a config value triggers re-run

**Effort:** one session. The peak-detection tuning is where the time goes; have a sample VOD's intermediate JSONs ready as fixtures.

---

## M3 — Transcription

**Goal:** Word-level transcript on disk, used by downstream stages.

**Deliverables**
- `src/clipper/transcribe.py` with `WhisperModel(distil-large-v3, cuda, float16)`, VAD on, word timestamps on
- VRAM released after completion (explicit `del model; gc.collect()`)
- Resume-friendly: if `transcript.json` exists, skip

**Validation**
- `transcript.json` parses; first 5 segments look sensible
- VRAM is back below 1 GB after the stage exits (`nvidia-smi`)
- Wall-clock on 4-hour VOD < 20 minutes

**Effort:** half a session. Mostly waiting on Whisper.

---

## M4 — Ranking

**Goal:** Candidates → ranked, scored clips with TikTok-ready titles.

**Deliverables**
- `src/clipper/rank.py` with `Ranker` protocol, `OllamaRanker`, `AnthropicRanker`
- Prompt template lives as a module constant (don't redesign — per spec)
- Lenient JSON extractor + one retry with stricter prompt on parse failure
- `Ollama keep_alive` so the model doesn't reload between candidates
- `tests/test_rank_response.py` covering malformed-response paths

**Validation**
- `ranked.json` exists with ≤ 20 entries, all with `score >= 60` and `standalone: true`
- Read 3 titles aloud — they should feel TikTok-y, not generic
- `--ranker anthropic` works when `ANTHROPIC_API_KEY` is set

**Effort:** one session. Most of the work is wrangling JSON output reliability.

---

## M5 — Export (static crop)

**Goal:** First watchable clips on disk. Static center-or-right crop, burned-in captions, NVENC encoded.

**Deliverables**
- `src/clipper/export.py` with single-x weighted-average crop (per spec §11 step 5 — defer dynamic)
- `.ass` subtitle generation (easier than `force_style` quoting on PowerShell)
- Caption timing in clip-local seconds (NOT source seconds — the spec §9 gotcha)
- `tests/test_caption_timing.py` green
- `out/<vod_id>/manifest.json` lists every clip

**Validation**
- 10–20 MP4s exist in `out/<vod_id>/clips/`
- Watch 3 of them top-to-bottom. Captions sync. Faces are visible (even if not perfectly centered). No mid-word starts/ends.
- `manifest.json` round-trips through `json.loads`

**This is the v0 done line.** Everything past M5 is polish.

**Effort:** one session. Subtitle styling iteration is the time sink.

---

## M6 — Face Tracking (dynamic crop)

**Goal:** Crop x-position follows the avatar's face per-clip.

**Deliverables**
- `src/clipper/face_track.py` with the pluggable `FaceDetector` protocol from `research.md` §2
- Default MediaPipe; auto-degrade to YuNet on <50% hit rate; static fallback last
- `face_track.json` with per-clip per-sample x positions
- `export.py` upgraded to use `sendcmd` with `crop.cmd` files (per `research.md` §4)

**Validation**
- Re-export the same 3 clips from M5. Avatar's face stays roughly centered through the clip even when they move.
- Compare side-by-side with the static-crop versions. Improvement should be visible.

**Effort:** half to one session. Most risk is `sendcmd` syntax; static fallback is already proven.

---

## M7 — Polish & First-Run UX

**Goal:** A new user can run `clipper run <url>` from a fresh clone and succeed.

**Deliverables**
- `README.md` documenting install, prereqs (link to research.md §1), one-command pipeline, how to swap rankers, where outputs land
- Pre-flight disk-space check in `download.py`
- Clear error message on Twitch VOD 404 ("VOD has expired")
- cuDNN smoke at startup so the user gets a clear error early, not deep into transcribe
- `--force` and `--force-from <stage>` flags wired
- `clipper rank-only <vod_id>` and `clipper export-only <vod_id>` subcommands

**Validation**
- Fresh `git clone`, follow README only (no spec reading), produce clips on a real VOD
- Intentionally trigger each failure mode (expired VOD, full disk, missing cuDNN) — confirm error messages are actionable

**Effort:** half a session.

---

## Post-v0 (out of scope, tracked for later)

- Per-frame dynamic crop refinement (better smoothing, scene-cut detection)
- Multi-VOD batch processing
- Auto-upload to TikTok / Shorts / Reels
- Web UI for reviewing + editing clip selections before export
- JP language support (swap distil-large-v3 → large-v3)
- Per-clip override file (`overrides.json`) so user can hand-edit titles or in/out points
