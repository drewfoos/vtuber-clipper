# VTuber Clipper — Interaction & Review Layer Design

Companion to `spec.md`. Specifies the user-facing workflow: how the pipeline is triggered, how clips are reviewed and curated, how motion-graphics effects are composed, and how final clips are produced. Resolves the open question of "what's the user actually doing with this thing."

Date: 2026-05-11

---

## 1. High-Level Flow

```
$ clipper run https://www.twitch.tv/videos/<id>

  download → chat → transcribe → peaks → candidates → rank
    └─ preview_export   (NEW — replaces current §6.9 export)
        ├─ Fast 540×960 NVENC clips, no captions, static crop
        ├─ Output: work/<vod_id>/previews/<id>.mp4
        └─ Wall-clock: ~30s for 20 clips (vs 5+ min for full renders)

  launch web server on 127.0.0.1:<port>, write server.json
  webbrowser.open(http://localhost:<port>)

  [USER REVIEWS IN BROWSER]
  - Keep/drop each clip
  - Edit titles
  - Adjust trim (start/end)
  - Toggle per-clip caption mode (burned / clean+srt / both)
  - Toggle per-clip effects (punch zoom, emoji burst, etc.)

  User clicks "Finalize N kept"
    └─ finalize stage (NEW)
        ├─ Re-cuts only kept clips from video.mp4 with user-edited trim
        ├─ Full 1080×1920 NVENC p5 with dynamic face-tracked crop
        ├─ Captions burned via ASS (or clean+SRT, per clip)
        ├─ Motion effects applied per clip
        └─ Output: out/<vod_id>/final/<NN>_<slug>.mp4 + manifest.json

  User clicks "Done"
    └─ server exits cleanly
```

Net effect: long encode work is deferred to finalize and only happens on kept clips. Wasted encode goes to zero.

---

## 2. Pipeline Changes vs Current Spec

| Spec §6.9 (current) | This design |
|---|---|
| `export.py` produces final 1080×1920 captioned MP4s in `out/<vod_id>/clips/` | `preview_export.py` produces fast 540×960 previews in `work/<vod_id>/previews/`. `finalize.py` produces final MP4s in `out/<vod_id>/final/` from review-UI-curated clips. |
| Static center crop or right-third | Same for preview (fast); dynamic face-tracked crop applied in finalize only |
| Captions burned in via SRT + `force_style` | Live HTML/CSS overlay in review UI (no burn for preview); ASS-based animated burn in finalize |
| One stage produces final output | Two stages: preview_export ends the pipeline, finalize runs from the review UI |
| No interactive review | New `web.py` module + browser-based review dashboard |

### New modules

```
src/clipper/
├── preview_export.py       # replaces export.py for preview path
├── finalize.py             # final encode triggered from review UI
├── captions.py             # ASS generator for burned captions (4 style presets)
├── web.py                  # FastAPI server, endpoints, lifecycle
├── effects/
│   ├── __init__.py
│   ├── base.py             # FinalizeEffect Protocol
│   ├── punch_zoom.py       # scales 1.08× on audio peaks within the clip
│   ├── emoji_burst.py      # animated emoji at chat-peak moments
│   ├── hook_card.py        # "WAIT FOR IT" 1.5s intro card
│   └── reaction_zoom.py    # tighter crop around face at climax
└── web/
    ├── index.html
    ├── app.css
    └── app.js
```

`export.py` from current spec is **removed**. Its acceptance criteria carry over to `finalize.py`.

---

## 3. Web Stack

- **Server:** FastAPI + uvicorn, bound to `127.0.0.1` only.
- **Frontend:** vanilla HTML/CSS/JS. No framework, no build step. `app.js` ~400 lines, `app.css` ~150 lines, `index.html` ~80 lines.
- **Port discovery:** auto-pick first free port in 8765–8800. Writes `{port, url, vod_id, pid}` to `work/<vod_id>/server.json`.
- **Lifecycle:**
  - Started by `clipper run` at end of pipeline, or by `clipper review <vod_id>`.
  - Exits on `POST /api/shutdown` or after 30 min idle (no requests received).
  - On startup, checks `server.json` for an existing PID; if alive, opens browser to that URL instead of starting a new instance.
- **Why no framework:** single user, single screen, < 10 endpoints. React/Vue is more code than the actual app and adds a build step we don't otherwise need.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | static `index.html` |
| `GET` | `/api/clips` | JSON: ordered list of clips with all metadata |
| `GET` | `/api/clips/{id}/preview.mp4` | preview video, HTTP range support for seeking |
| `GET` | `/api/clips/{id}/transcript` | word-level transcript (start, end, word) for the clip window |
| `PUT` | `/api/clips/{id}` | update one or more of: `title`, `t_start`, `t_end`, `kept`, `caption_mode`, `effects` |
| `POST` | `/api/finalize` | start re-encode of kept clips; returns SSE stream of progress |
| `POST` | `/api/shutdown` | exit server cleanly |

`PUT /api/clips/{id}` immediately persists to `work/<vod_id>/review_state.json` (see §10).

---

## 4. Review UI Layout

Two-pane dashboard, full-viewport.

```
┌─────────────────────────────────────────────────────────────────┐
│ VOD 2762489406 · streamer_name · 20 clips · 5 kept              │ ← top bar
├──────────────────────┬──────────────────────────────────────────┤
│ ▸ 01 HOLY NO WAY...  │                                          │
│   ★87  0:32  14:23   │       ┌────────────────┐                 │
│ ▾ 02 I cannot bel... │       │                │                 │
│   ★82  0:28  1:42:11 │       │  9:16 preview  │                 │
│ ▸ 03 chat reaction.. │       │     player     │                 │
│   ★79  0:45  2:08    │       │   + captions   │                 │
│ ▸ 04 just a sneeze ✗ │       │    overlay     │                 │
│   ★62  0:18  2:55    │       │                │                 │
│ ▸ 05 ...             │       └────────────────┘                 │
│ ▸ 06 ...             │                                          │
│ ... (scrollable)     │  Title: [I cannot believe this clip]     │
│                      │  Start: [1:42:11.30]  End: [1:42:39.00]  │
│                      │  ▷━━━━━●═══════════●━━━━━ ◁  (scrubber)  │
│                      │                                          │
│                      │  Captions: [Burned ▾]  ▣Punch  ▣Emoji    │
│                      │            ▢Hook   ▢ReactZoom            │
│                      │                                          │
│                      │  [✓ Keep]  [✗ Drop]                      │
│                      │                                          │
│                      │  Score: 82  Reason: "Strong reaction..." │
│                      │  Top emotes: KEKW LULW OMEGALUL          │
├──────────────────────┴──────────────────────────────────────────┤
│ 5 kept · [⏎ Finalize 5 kept]  [Done — exit server]              │ ← footer
└─────────────────────────────────────────────────────────────────┘
```

### Left pane (clip list, ~320px wide)
- Scrollable list, one row per clip (~50px tall)
- Row contents: index, abbreviated title, score (★), duration, source timestamp, keep/drop indicator
- Selected row highlighted; click selects
- Kept clips: green left-border accent
- Dropped clips: dimmed, with `✗` marker

### Right pane (detail, flexible)
- **9:16 video player** at the top (HTML5 `<video>` with controls). Plays the preview MP4. Live caption overlay positioned absolutely over the video.
- **Title field** (text input, autosaves on blur or 500ms debounce)
- **Trim controls:**
  - Numeric inputs for start/end (HH:MM:SS.mmm format)
  - Dual-thumb scrubber positioned over a timeline of the clip duration
  - Keyboard nudge: `z`/`x` to nudge start ±0.1s, `,`/`.` to nudge end ±0.1s
  - Constrains: `t_start < t_end - 2.0s` (min 2-second clip)
- **Captions dropdown:** Burned (default) / Clean + SRT / Both
- **Effects checkboxes:** Punch zoom, Emoji burst, Hook card, Reaction zoom. Each default on/off per config; overridable per clip.
- **Keep / Drop buttons**
- **Read-only metadata:** score, reason, top emotes

### Keyboard shortcuts (power-user mode)
| Key | Action |
|---|---|
| `j` / `k` or `↓` / `↑` | next / prev clip |
| `Space` | play / pause |
| `y` | keep current clip |
| `n` | drop current clip |
| `z` / `x` | nudge `t_start` -0.1s / +0.1s |
| `,` / `.` | nudge `t_end` -0.1s / +0.1s |
| `Enter` | focus title field |
| `Esc` | blur input fields |
| `f` | open finalize modal |
| `?` | show shortcut help overlay |

### Top bar
- VOD ID, streamer name, total clips, kept count
- Refresh button (re-reads `review_state.json` and `ranked.json` from disk — handy if user manually edits)

### Footer
- Kept count + finalize button (disabled if 0 kept)
- "Done" button (POSTs `/api/shutdown`)
- Finalize-in-progress: replaces footer with a progress bar streamed via SSE

---

## 5. Captions

### Live preview (in browser)
- Driven by `<video>` `timeupdate` event (~4 Hz)
- Binary search through transcript words to find the currently-active word(s)
- Render as absolutely-positioned `<div>` over the video
- Styled to match what would be burned (Arial Black, large, white with black outline, yellow active word)

### Burned final (ASS via libass + ffmpeg `subtitles=` filter)

`captions.py` exposes one entry point:

```python
def generate_ass(
    transcript_words: list[Word],   # already trimmed to clip-local time
    style: Literal["window3", "single", "karaoke", "stacked2"],
    output_size: tuple[int, int],   # for positioning
) -> str:                            # path to .ass file
```

Four style presets shipped:
- `single` — one word at a time, scale-pop animation (option A from mockup)
- **`window3`** (default) — 3-word window, active word in yellow at slight scale (option B from mockup)
- `karaoke` — full sentence with left-to-right yellow fill (option C from mockup)
- `stacked2` — past words faded above, present word highlighted below (option D from mockup)

The active style is per-clip in the UI; global default is in `[finalize] caption_style` in `config.toml`.

### Caption modes (per clip)

| Mode | Output |
|---|---|
| `burned` (default) | One MP4 with captions baked in |
| `clean` | One MP4 without captions + sidecar `.srt` file with the same basename |
| `both` | Burned MP4 + clean MP4 (suffixed `_clean.mp4`) + sidecar `.srt` |

SRT generation is independent of the ASS generator; ~15 lines wrapping `srt` library or manual format.

---

## 6. Motion Graphics Effects

Effects are pluggable. v0 ships with five (captions counts as one). Each is a separate file in `clipper/effects/`.

### Protocol

```python
class FinalizeEffect(Protocol):
    name: str
    default_enabled: bool

    def apply(
        self,
        clip: RankedClip,
        face_track: FaceTrack,
        audio_peaks: list[Peak],
        chat_peaks: list[Peak],
        transcript: list[Word],
        ass: AssDocument,           # mutable, accumulates layers
        filter_chain: FilterChain,  # mutable, accumulates ffmpeg filters
    ) -> None: ...
```

The finalize stage iterates effects in a fixed order, each mutating the ASS document and the ffmpeg filter chain. Final ffmpeg invocation is built once at the end.

### Shipped effects (v0)

| Effect | Trigger | Implementation |
|---|---|---|
| `captions` | Always (unless `caption_mode=clean`) | ASS layer per word-window |
| `punch_zoom` | Audio peaks within the clip (≥ 8 dB above baseline) | ffmpeg `zoompan` with time-windowed expression, ramping 1.0→1.08→1.0 over 0.4s |
| `emoji_burst` | Chat peaks within the clip (top emote from that window) | ASS layer with PNG `\p1` graphic or Twemoji font glyph + `\move` `\fad` `\frz` |
| `hook_card` | First 1.5s of clip if `hook_quality >= 7` (from ranker) | ASS title-card layer with background `\p1` drawing |
| `reaction_zoom` | Timestamp with the highest combined audio_intensity + chat_hype_score in the clip | crops 10% tighter around `face_track` x-center for 0.8s window |

### Configuration

```toml
[finalize.effects]
captions = "window3"          # also accepts: "single" | "karaoke" | "stacked2" | "off"
punch_zoom = true
emoji_burst = true
hook_card = true
reaction_zoom = true
```

Per-clip overrides via review-UI checkboxes are stored in `review_state.json` under each clip's `effects` field.

### Emoji rendering notes
- Emoji-burst requires a font with color emoji glyphs. Bundle `Twemoji.ttf` (open-source) in the repo and reference it via ASS `Fontname=Twemoji`.
- Fallback: render emoji as transparent PNGs from a pre-generated sprite sheet (Twemoji ships PNGs too). Slightly faster than font rendering in libass.
- Decision deferred to implementation — pick whichever Spike 1 of M5.5 proves out.

---

## 7. Render Strategy

### Preview (`preview_export.py`)
- Resolution: 540×960
- Codec: `h264_nvenc -preset p7 -cq:v 28`
- Audio: AAC 96k
- Crop: single weighted-average x from `face_track.json` (static per clip, like spec)
- No captions burned, no effects applied
- Wall-clock target: ≤ 2s per clip on RTX 3080 → 30–40s for 20 clips

### Finalize (`finalize.py`)
- Resolution: 1080×1920
- Codec: `h264_nvenc -preset p5 -cq:v 23`
- Audio: AAC 128k
- Crop: dynamic via `sendcmd` (per `research.md` §4) using full `face_track` series
- Captions burned per per-clip mode
- Effects applied per per-clip flags
- Wall-clock target: ≤ 15s per clip → 75s for 5 kept clips typical, < 5 min worst case

---

## 8. Output Layout

```
out/<vod_id>/
├── final/
│   ├── 01_holy-no-way-that-happened.mp4
│   ├── 01_holy-no-way-that-happened_clean.mp4    # only if mode=both
│   ├── 01_holy-no-way-that-happened.srt          # if mode in {clean, both}
│   ├── 02_i-cannot-believe-this.mp4
│   ├── ...
│   └── manifest.json
```

### Final `manifest.json`
```json
{
  "vod_id": "2762489406",
  "streamer": "...",
  "source_url": "...",
  "generated_at": "2026-05-11T18:23:45Z",
  "finalize_run_id": "uuid",
  "clips": [
    {
      "filename": "01_holy-no-way-that-happened.mp4",
      "clean_filename": null,
      "srt_filename": null,
      "title": "HOLY NO WAY THAT HAPPENED",
      "t_start_source": 14.23,
      "t_end_source": 46.78,
      "duration": 32.55,
      "caption_mode": "burned",
      "effects_applied": ["captions", "punch_zoom", "emoji_burst", "reaction_zoom"],
      "score": 87,
      "hook_quality": 9,
      "reason": "Strong audio + chat peak; clean sentence boundaries...",
      "top_emotes": ["KEKW", "LULW", "OMEGALUL"]
    }
  ]
}
```

Filename slug derived via single helper: lowercase, ASCII only, spaces → `-`, strip punctuation, max 60 chars, prefix with zero-padded index.

---

## 9. CLI Integration

### Updated commands

| Command | Behavior |
|---|---|
| `clipper run <url>` | Full pipeline → preview_export → launch server → open browser. The pipeline command terminates after `webbrowser.open()`; server stays up until user clicks Done or idle-times out. |
| `clipper review <vod_id>` | Skip pipeline; just launch server for an already-processed VOD. Re-opens browser even if a server is already running for that VOD. |
| `clipper finalize <vod_id>` | Run finalize headlessly using the latest `review_state.json` (escape hatch if browser fails). |
| `clipper run <url> --no-review` | Old-style behavior: pipeline runs, no server launched, no preview previews kept — runs finalize directly using ranker's default selections. Useful for batch jobs. |
| `clipper rank-only <vod_id>` | (unchanged from spec) |
| `clipper export-only <vod_id>` | **Removed**. Replaced by `clipper review` (interactive) and `clipper finalize` (headless). |

### Pipeline output to terminal
- `rich.progress` bars during pipeline stages (unchanged from spec)
- After `preview_export` completes: `Opening review browser at http://localhost:8765 — make selections and click 'Done' when finished.`
- After server exits: `Wrote 5 clips to out/<vod_id>/final/`
- Errors at any stage produce a clear actionable message before exit

---

## 10. State Persistence (`review_state.json`)

Lives at `work/<vod_id>/review_state.json`. Updated on every `PUT /api/clips/{id}`.

```json
{
  "vod_id": "2762489406",
  "schema_version": "0.1.0",
  "last_modified": "2026-05-11T18:12:34Z",
  "clips": {
    "c001": {
      "title": "HOLY NO WAY THAT HAPPENED",
      "t_start": 14.23,
      "t_end": 46.78,
      "kept": true,
      "caption_mode": "burned",
      "effects": {
        "punch_zoom": true,
        "emoji_burst": true,
        "hook_card": false,
        "reaction_zoom": true
      }
    },
    "c002": { ... }
  }
}
```

- Initial state seeded from `ranked.json` when the server first starts (or when state file is missing).
- Server reads on startup, merges with `ranked.json` to handle the case where re-ranking added/removed candidates.
- Survives server restart, crash, or `clipper review` re-launch.
- User can hand-edit it in a text editor between sessions if desired.

---

## 11. Server-to-Browser Communication

### Loading data
- Browser fetches `GET /api/clips` once on load. Receives full list with all metadata + per-clip state.
- Subsequent edits PUT immediately; server returns the updated clip object.

### Video streaming
- `GET /api/clips/{id}/preview.mp4` supports HTTP `Range` requests so the `<video>` element can seek.
- FastAPI doesn't ship with range support out of the box — implement as ~30-line dependency that wraps `FileResponse` to handle `Range:` header and return `206 Partial Content`.

### Finalize progress (SSE)
- `POST /api/finalize` starts the encode and returns text/event-stream
- Events: `{"clip_id": "c001", "status": "started"}`, `{"clip_id": "c001", "status": "encoded", "duration_s": 12.3}`, etc.
- Frontend renders progress in the footer
- Final event: `{"status": "complete", "manifest_url": "out/<vod>/final/manifest.json"}`

---

## 12. Error Handling

| Failure | User-facing surface |
|---|---|
| Server port range exhausted | Pipeline exits with: `No free port in 8765-8800. Pass --port <N> or kill an old server.` |
| Browser fails to auto-open | URL printed to terminal; pipeline waits for `--no-wait` to skip |
| Preview file missing when browser requests it | 404 + UI error toast: "Preview file missing — re-run preview_export" |
| Finalize ffmpeg fails on one clip | Logged + skipped; manifest excludes the failed clip; SSE emits `{"clip_id": "...", "status": "error", "msg": "..."}`; finalize continues |
| User closes browser before finalize | Server keeps running; user reopens via the same URL or `clipper review` |
| `review_state.json` corrupt or schema mismatch | Fall back to fresh state from `ranked.json`, with a warning toast |

---

## 13. Updates Required to Existing Docs

This design changes the surface area of the project. After this doc is approved:

### `spec.md`
- Replace the `export.py` module spec with two specs: `preview_export.py` (fast previews) and `finalize.py` (full-quality re-encode from review state). Renumber following module subsections.
- Add module specs for `captions.py` (ASS generator), `web.py` (FastAPI server + endpoints), and the `effects/` package (Protocol + the five v0 implementations).
- Extend the `config.toml` section with `[finalize]` (caption_style, caption_mode, server port range) and `[finalize.effects]` (per-effect enabled flags).
- Update the v0 acceptance-criteria section to include the ten review-UI criteria from §16 below.

### `architecture.md`
- Revise §2 system diagram to add preview_export → web → finalize branch
- Add §3 row for each new module
- Add §11 "Web layer" subsection covering server lifecycle, SSE, range requests
- Update §6 idempotency model to handle the finalize-from-review_state-only path

### `MILESTONES.md`
- **Rescope existing M5** from "Export (static crop)" to "Preview export" — fast 540×960 previews only. Static crop stays as the v0 approach for previews.
- **Insert new M5.5 — Review UI + Finalize** between M5 and M6. Deliverables: `web.py`, `captions.py` (window3 only initially), all five effects modules at MVP fidelity, `index.html`/`app.js`/`app.css`, `finalize.py`, `review_state.json` round-trip, full 1080×1920 NVENC encode with burned captions.
- **M6 (face tracking)** stays, but rescope: dynamic per-frame `sendcmd` crop applies to finalize output only (preview keeps static).
- **M7 (polish)** unchanged in intent, but acceptance criteria now include the review UI working from a fresh clone.
- **Additional caption styles** (single / karaoke / stacked2) beyond `window3` move to a new post-v0 milestone.

### `changelog.md`
- Add: "Decided web-based review UI as the interaction layer"
- Add: "Pipeline split: preview_export ends the auto-run; finalize triggered from UI"
- Add: "Five motion-graphics effects shipped in v0: captions, punch_zoom, emoji_burst, hook_card, reaction_zoom"
- Add: "Caption styles: four presets (single / window3 default / karaoke / stacked2)"
- Add: "Caption modes: burned / clean+srt / both, per-clip"

---

## 14. Out of Scope (deferred to post-v0)

- Multi-VOD server mode (one VOD per session)
- "Show all candidates" view for sub-threshold clips
- Auto-upload to TikTok/Shorts/Reels
- Sound effects layer
- Animated chat ticker side strip
- Spring-physics / particle effects
- Custom per-clip transitions (clips are single continuous cuts in v0)
- AI-generated emoji selection per moment (uses top-emote-from-chat instead)
- Mobile-responsive review UI (single-user desktop only)
- Multi-user / shared editing (single user only)

---

## 15. Open Questions / Risks

| Question / Risk | Resolution path |
|---|---|
| HTTP range requests in FastAPI | Implement custom range responder (~30 lines, well-known pattern). Test with `<video>` seeking. |
| Emoji rendering in libass — font vs PNG sprite | Spike in M5.5 build. Twemoji font is cleaner if libass renders it correctly on Windows; PNG sprite is reliable fallback. |
| ASS `\t` animation timing on libass for Windows ffmpeg builds | Verify with the simplest `\fscx120` test before building all five effects. |
| Browser auto-open on Windows | `webbrowser.open()` uses default browser; may not respect work profiles. Print URL to terminal regardless so user can copy. |
| Server lifecycle if user runs two pipelines back-to-back | Second pipeline detects existing server.json with live PID, kills the old server, starts a new one. (Documented in CLI help.) |
| Finalize wall-clock for 20 kept clips | Worst-case ~5 min on RTX 3080. Acceptable; show SSE progress so user knows it's working. |
| Performance of live caption overlay in browser | 4 Hz `timeupdate` should be fine; if jittery, switch to `requestVideoFrameCallback` for finer-grained sync. |

---

## 16. Acceptance Criteria (for the interaction layer)

The interaction layer meets v0 when:

1. `clipper run <url>` completes with a browser auto-opening to a working review UI.
2. The UI displays all 20 ranked clips with metadata, preview players play smoothly, and seeking works.
3. Live caption overlay matches the (currently selected) burn style within ±100ms of word boundaries.
4. Editing title / trim / kept / caption mode / effects persists to `review_state.json` and survives browser refresh.
5. Clicking Finalize re-encodes only kept clips at full quality with edits applied, with SSE progress visible.
6. Final clips land in `out/<vod_id>/final/` with the expected filename + manifest shape.
7. Clicking Done shuts down the server cleanly and exits the original `clipper run` process.
8. `clipper review <vod_id>` re-opens the UI for an existing VOD with state preserved.
9. All five v0 effects (captions, punch_zoom, emoji_burst, hook_card, reaction_zoom) produce visible output on a test clip.
10. Caption-mode dropdown produces the right combination of MP4 + clean MP4 + SRT files per mode.
