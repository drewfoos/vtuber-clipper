# VTuber Clipper — Pre-Build Research

Companion to `spec.md`. Captures the questions, risks, verification steps, and pre-build spikes that should be resolved before writing module code.

**Build order:** run §1 (env verification) first-first, then §10 (spikes) before any module code. Everything else is reference.

---

## 1. Environment Verification (run these before any code)

```powershell
ffmpeg -version                                  # ffmpeg on PATH
ffmpeg -encoders 2>&1 | findstr nvenc            # must list h264_nvenc
ffmpeg -filters 2>&1 | findstr -i "ass subtitle" # must list libass-backed subtitles
nvidia-smi                                       # CUDA driver + GPU visible
python --version                                 # 3.11.x or 3.12.x (NOT 3.13)
yt-dlp --version
ollama --version
ollama list                                      # llama3.1:8b pulled
```

Then the faster-whisper CUDA smoke (catches the cuDNN issue before it bites mid-pipeline):

```powershell
python -c "from faster_whisper import WhisperModel; m = WhisperModel('tiny', device='cuda', compute_type='float16'); print('cuda ok')"
```

Disk-space pre-flight: `Get-PSDrive` — confirm ≥ 50 GB free on whichever drive `work/` lives on. `download.py` should re-check this at runtime and fail fast with a clear message.

### The cuDNN-on-Windows footgun

`faster-whisper` uses CTranslate2, which dynamically loads cuDNN DLLs. A vanilla CUDA Toolkit install does **not** put those DLLs in a location CT2 can find. Symptom is a DLL load error at `WhisperModel(...)` instantiation, **not** at import — easy to miss in a smoke test that only imports.

Three fixes, in preference order:

1. **`pip install nvidia-cudnn-cu12==9.*`** — easiest; bundles DLLs into site-packages, CT2 ≥ 1.5 picks them up automatically. Add to `pyproject.toml`.
2. **Install PyTorch with CUDA** (`pip install torch --index-url https://download.pytorch.org/whl/cu121`). Torch ships cuDNN; CT2 finds the DLLs if torch is imported first. Wasteful (~2 GB) but reliable.
3. **Manual cuDNN install from NVIDIA**, copy `cudnn*.dll` and `cublas*.dll` onto PATH. Works but maintenance burden.

If the smoke fails with `Unable to load any of {libcudnn_ops.so.9, ...}` — that's this footgun. **This is now the biggest remaining unknown** (see §8).

### VRAM staging

Spec calls out that Whisper (~5 GB) and Ollama llama3.1:8b (~6 GB) shouldn't co-reside on a 10 GB card. The pipeline already runs sequentially, but `WhisperModel.__del__` may not free VRAM promptly — between stages, explicit `del model; gc.collect()` (and `torch.cuda.empty_cache()` if torch happens to be imported) is cheap insurance.

---

## 2. 3D vs 2D — Face Detection Risk Re-Rated

**Earlier draft assumed 2D Live2D. The target streamer uses a 3D model — risk drops significantly.**

A 3D face-tracked avatar is geometrically close to a human face wearing a costume: depth, shading, and motion driven by the same blendshape rigs as real face-tracking. MediaPipe anecdotally hits 80–95% on Hololive 3D, Phase Connect 3D, and indie VRM models.

**Plan as if MediaPipe works.** Spike §10.1 (5 minutes) confirms on the actual streamer's model. Have a fallback ready, don't over-engineer for failure.

### Pluggable detector interface

```python
class FaceDetector(Protocol):
    def detect(self, frame: np.ndarray) -> Optional[BoundingBox]: ...

class MediaPipeDetector: ...   # default
class YuNetDetector: ...       # cv2.FaceDetectorYN_create — better on stylized faces, in OpenCV core
class AnimeFaceDetector: ...   # github.com/hysts/anime-face-detector — ~250 MB model, only install if needed
class StaticCropDetector: ...  # config-driven fixed bbox, fallback of last resort
```

Pick at runtime via `[export] detector = "mediapipe"`. Optional auto-degrade per-clip: if MediaPipe finds a face in <50% of sampled frames for a given clip, retry with YuNet, then fall back to static.

YuNet ships in OpenCV core (no extra dep beyond the existing `opencv-python` — model file is a small download). AnimeFaceDetector is a heavy dep — only install if both prior options fail in spike §10.1.

---

## 3. Library Behavior Unknowns

### faster-whisper
- Confirm `distil-large-v3` model string is accepted and downloads from HF.
- `word_timestamps=True` returns word objects with `.start`, `.end`, `.word` attributes. Fully drain the segments generator to a list before persisting — partial transcript on crash otherwise.
- VAD parameters — tune `min_silence_duration_ms` for stream pacing if defaults eat real speech.

### chat-downloader
- Confirm field shape. Library returns `time_in_seconds` (which we want), `time_text`, and `timestamp` (unix). Use `time_in_seconds` only. Assert monotonic.
- Test on the actual VOD — chat replay availability varies.

### Ollama JSON mode + llama3.1:8b
- `format: "json"` is mostly reliable on this model but occasionally wraps in markdown. Wrap response in retry + lenient JSON extractor (strip fences, find outermost `{...}`).
- Latency: 5–15s per candidate on 3080 → up to 10 min for 40 candidates. Use `keep_alive` so the model doesn't reload between calls.
- Token budget is fine (1.5–3k input, 128k context).

### Anthropic ranker (optional path)
- Verify `claude-haiku-4-5-20251001` model ID is still current at build time.
- Use prompt caching on the instruction/schema portion of the prompt — significant cost reduction when ranking 20–40 candidates.

---

## 4. ffmpeg Specifics

### Parsing `astats` output

The `astats + ametadata=print:file=rms.log` chain emits:

```
frame:0    pts:0       pts_time:0
lavfi.astats.Overall.RMS_level=-23.456789
frame:1    pts:11025   pts_time:0.25
lavfi.astats.Overall.RMS_level=-22.123456
```

Parse pairs of (`pts_time:` line, next `RMS_level=` line) with a regex pass — simpler than a state machine. Test this with a fixture file (see §7).

### Dynamic crop via `sendcmd` (post-v0)

v0 uses a single weighted-average x. When upgrading:

```bash
ffmpeg -i in.mp4 -filter_complex \
  "sendcmd=f=crop.cmd,crop=608:1080:0:0,scale=1080:1920" \
  ...
```

Where `crop.cmd` is:

```
0.0  crop x 608;
0.5  crop x 620;
1.0  crop x 615;
```

Times are clip-local seconds from 0. Linear interpolation between commands is automatic.

### Subtitle burn-in

Requires ffmpeg built with libass. gyan.dev's **essentials** and **full** Windows builds have it; **shared** does not. The `findstr` check in §1 verifies this.

`force_style` quoting on PowerShell is painful — easier to generate `.ass` files directly with style baked into the header, and feed those to the `subtitles` filter.

### NVENC tuning notes
- `-preset p5` is the sweet spot per spec; confirmed.
- `-rc:v vbr -cq:v 23` gives more consistent quality than fixed `-b:v 6M` — consider for v1.
- `-bf 3` (B-frames, Ampere supports them) → ~5–10% better compression at no quality cost.

---

## 5. Data Contract Fixes

Inconsistencies in `spec.md` to resolve before building:

- **JSONL vs JSON:** chat output is JSONL (potentially 100k+ messages, streaming-friendly). Everything else is JSON (small, human-inspectable). Modules reading chat iterate line-by-line. Document this once in the spec's data-formats section.
- **`top_emotes` extraction (undefined in spec):** for each chat-peak window, tokenize messages on whitespace, count tokens matching the hype regex (case-insensitive), return top 5 by frequency. Helper lives in `chat_peaks.py`.
- **Time origin rule:** every intermediate JSON stores timestamps in **source-video seconds** (t=0 = first video frame). Caption SRT files are the **only** place we use clip-local seconds. Document at the top of the spec.
- **Candidate IDs:** `c001` zero-padded to 3 is fine for ≤ 999. Bump to 4 if any VOD ever exceeds. Cheap upfront.

---

## 6. Idempotency Design

Per stage, write `.stage_meta.json` next to the output:

```json
{
  "stage": "audio_peaks",
  "version": "0.1.0",
  "config_hash": "<sha256 of THIS STAGE'S config section only>",
  "input_hashes": {
    "audio.opus": "(mtime, size) tuple — not full sha256 for big files"
  },
  "completed_at": "2026-05-11T12:34:56Z"
}
```

- **`config_hash`** covers only the relevant `[section]` for this stage. Whole-file hash would spuriously invalidate everything on any tweak.
- **`input_hashes`** uses `(mtime, size)` for big files (25 GB video), full sha256 for small JSON inputs. Hashing the video adds minutes.
- **`schema_version`** constant per module — bump when output shape changes so cached files invalidate even when config is unchanged.
- **Downstream invalidation:** when a stage's meta is stale, delete the `.stage_meta.json` (but **not** the output file — user may want to inspect it). Next stage sees missing meta on its input and re-runs.
- **CLI flags:** `--force` (this stage only) and `--force-from <stage>` (cascade) wipe metas accordingly.

---

## 7. Testing Strategy

Spec mandates one test (`test_candidates.py`). Add these because their failure modes are silent, not crashes:

| Test | Why |
|---|---|
| `test_candidates.py` (spec-required) | Peak-merge: overlapping, adjacent-within-tolerance, isolated chat-only. Enforce min/max duration. |
| `test_chat_peaks.py` | Synthetic stream with known spike at t=120s. Assert `find_peaks` lands within ±2s. |
| `test_audio_peaks_parse.py` | Feed a fixture `rms.log` string, verify parser emits expected `(t, db)` array. Guards against ffmpeg `astats` format drift. |
| **`test_caption_timing.py`** | Words at t=[100,101,102], clip [99.5,103.0] → SRT entries at [0.5,1.5,2.5]. **Highest-ROI test in the suite** — the #1 gotcha in spec §9, invisible until someone actually watches a clip. |
| `test_rank_response.py` | Mock LLM with malformed responses (trailing prose, missing keys, wrong types, trailing comma). Ranker retries once with stricter prompt, then skip-and-log. No crash. |

Use `pytest` + `pytest-mock`. **Don't** mock ffmpeg or yt-dlp — those are integration territory and any test there is brittle without being valuable.

---

## 8. Risks & Mitigations (re-rated)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **cuDNN DLL load failure on Windows** | **High** | Blocks pipeline | Bundle `nvidia-cudnn-cu12` in deps; 1-line startup smoke catches it before a 4-hour run |
| MediaPipe misses the 3D avatar's face | Low (3D) | Wrong crop, ugly clips | Pluggable detector + per-clip auto-fallback to YuNet → static |
| Ollama returns malformed JSON | Medium | One clip skipped | One retry with stricter prompt; log + skip on second failure |
| Twitch VOD expires before download finishes | Low | Total failure | Detect 404 in yt-dlp output, clear error message; not auto-recoverable |
| `astats` output format changes between ffmpeg versions | Low | Audio peaks broken | Parser test fixture; pin minimum ffmpeg version in README |
| Chat-downloader rate-limited | Low | Slow chat fetch | Library handles; surface the wait via rich progress |
| NVENC concurrent-encode limit (consumer cards) | Very Low | Slower export | Already sequential per design |
| Disk fills mid-pipeline (25 GB video + intermediates) | Medium | Hard crash | Pre-flight disk-space check in `download.py`, fail fast |
| libass missing from ffmpeg build | Low | No captions | Env-check in §1 catches at setup |

**Top remaining unknown:** cuDNN/CTranslate2 on Windows. Validate with the smoke in §1 before anything else.

---

## 9. Docs to Fetch (via Context7)

Hand Claude Code this list before writing module code:

- `faster-whisper` — `WhisperModel` constructor flags, `transcribe()` return shape
- `chat-downloader` — `get_chat()` iteration interface, exact per-message fields for Twitch
- `mediapipe` Python — `solutions.face_detection` and the newer `tasks.vision.FaceDetector` (confirm which is current)
- `opencv-python` — `FaceDetectorYN` for the YuNet fallback
- `scipy.signal.find_peaks` — `prominence` / `distance` / `height` semantics
- `click` — group/command/option patterns
- `rich.progress` — `Progress` with multiple tasks
- `anthropic` Python SDK — `messages.create` with `response_format` + prompt caching
- ffmpeg filter docs: `astats`, `ametadata`, `crop`, `scale`, `subtitles`, `sendcmd`, `h264_nvenc`

---

## 10. Pre-Build Spikes (run BEFORE writing module code)

### Spike 1 — MediaPipe hit-rate on this exact streamer

```python
# spike_face.py
import cv2, mediapipe as mp, subprocess
subprocess.run([
    "yt-dlp", "-f", "720p60",
    "--download-sections", "*00:10:00-00:11:00",
    "-o", "sample.mp4",
    "https://www.twitch.tv/videos/2762489406"
], check=True)

cap = cv2.VideoCapture("sample.mp4")
det = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.3)
hits = total = 0
while cap.isOpened():
    ok, frame = cap.read()
    if not ok: break
    total += 1
    if total % 10 != 0:    # 6 fps sampling at 60fps source
        continue
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    if det.process(rgb).detections:
        hits += 1
sampled = total // 10
print(f"hit rate: {hits}/{sampled} = {hits/sampled:.1%}")
```

Decision rule:
- **> 70%** → proceed with MediaPipe (expected path for a 3D model)
- **50–70%** → plan on YuNet as default
- **< 50%** → AnimeFaceDetector or static crop

### Spike 2 — End-to-end shell smoke on a 5-minute slice

No Python pipeline yet — just confirms every binary works on this streamer's content before committing to architecture.

```powershell
# 5-minute sample download
yt-dlp -f 1080p60 --download-sections "*00:30:00-00:35:00" -o sample.mp4 https://www.twitch.tv/videos/2762489406

# Audio extract
ffmpeg -i sample.mp4 -vn -c:a libopus -b:a 32k sample.opus

# Chat fetch
chat_downloader https://www.twitch.tv/videos/2762489406 --start_time 1800 --end_time 2100 --output sample_chat.json

# Whisper smoke (also doubles as the cuDNN check)
python -c "from faster_whisper import WhisperModel; m=WhisperModel('distil-large-v3',device='cuda',compute_type='float16'); s,_=m.transcribe('sample.opus',word_timestamps=True); print(list(s)[0])"

# NVENC + crop + subtitle-less encode smoke
ffmpeg -i sample.mp4 -t 30 -vf "crop=608:1080:660:0,scale=1080:1920" -c:v h264_nvenc -preset p5 -b:v 6M -c:a aac -t 30 smoke_clip.mp4
```

If all four succeed and `smoke_clip.mp4` plays correctly, the rest of the build is glue around things already proven to work on this machine. If any one fails, fix it at the binary level before wrapping it in Python.

---

## Net Effect on the Build

The spec stands. Claude Code should:

1. Run §1 env verification.
2. Run §10 spikes.
3. If spike 1 hit-rate > 70%, proceed with MediaPipe as default.
4. If the cuDNN smoke fails, install `nvidia-cudnn-cu12==9.*` and re-run.
5. Then begin module implementation in the order suggested by spec §11.

3D avatar risk: **down**. cuDNN-on-Windows risk: **now the top remaining unknown**, mitigatable in one `pip install`.
