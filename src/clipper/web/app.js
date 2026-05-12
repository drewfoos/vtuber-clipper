const state = {
  clips: [],
  selectedId: null,
  transcript: [],
  saveTimer: null,
};

async function loadClips() {
  const r = await fetch("/api/clips");
  state.clips = await r.json();
  renderTopbar();
  renderList();
  if (state.clips.length) selectClip(state.clips[0].id);
}

function renderTopbar() {
  const kept = state.clips.filter(c => c.kept).length;
  document.getElementById("vod-label").textContent = `${state.clips.length} clips`;
  document.getElementById("kept-summary").textContent = `${kept} kept`;
}

function renderList() {
  const list = document.getElementById("clip-list");
  list.replaceChildren();
  state.clips.forEach((c, i) => {
    const row = document.createElement("div");
    row.className = "clip-row"
      + (c.id === state.selectedId ? " selected" : "")
      + (c.kept ? " kept" : " dropped");
    row.dataset.clipId = c.id;

    const titleDiv = document.createElement("div");
    titleDiv.className = "title";
    titleDiv.textContent = `${String(i + 1).padStart(2, "0")} · ${c.title}`;

    const metaDiv = document.createElement("div");
    metaDiv.className = "meta";
    metaDiv.textContent = `★${c.score} · ${(c.t_end - c.t_start).toFixed(1)}s`;

    row.appendChild(titleDiv);
    row.appendChild(metaDiv);
    row.addEventListener("click", () => selectClip(c.id));
    list.appendChild(row);
  });
}

async function selectClip(id) {
  state.selectedId = id;
  renderList();
  const clip = state.clips.find(c => c.id === id);
  document.getElementById("title-input").value = clip.title;
  document.getElementById("t-start-input").value = clip.t_start.toFixed(3);
  document.getElementById("t-end-input").value = clip.t_end.toFixed(3);
  document.getElementById("caption-mode").value = clip.caption_mode;

  const meta = document.getElementById("metadata");
  meta.replaceChildren();
  const ln1 = document.createElement("div");
  ln1.textContent = `Score: ${clip.score} · Hook: ${clip.hook_quality}`;
  const ln2 = document.createElement("div");
  ln2.textContent = `Reason: ${clip.reason}`;
  const ln3 = document.createElement("div");
  ln3.textContent = `Emotes: ${(clip.top_emotes || []).join(" ")}`;
  meta.appendChild(ln1);
  meta.appendChild(ln2);
  meta.appendChild(ln3);

  const player = document.getElementById("player");
  player.src = `/api/clips/${id}/preview.mp4`;
  const tr = await fetch(`/api/clips/${id}/transcript`).then(r => r.json());
  state.transcript = tr.map(w => ({
    word: w.word,
    start: w.start - clip.t_start,
    end: w.end - clip.t_start,
  }));
}

async function patchClip(patch) {
  const r = await fetch(`/api/clips/${state.selectedId}`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(patch),
  });
  if (!r.ok) return;
  const updated = await r.json();
  const idx = state.clips.findIndex(c => c.id === updated.id);
  state.clips[idx] = updated;
  renderList();
  renderTopbar();
}

function debouncedPatch(patch) {
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => patchClip(patch), 400);
}

document.getElementById("title-input").addEventListener("input", e => {
  debouncedPatch({title: e.target.value});
});
document.getElementById("caption-mode").addEventListener("change", e => {
  patchClip({caption_mode: e.target.value});
});
document.getElementById("keep-btn").addEventListener("click", () => patchClip({kept: true}));
document.getElementById("drop-btn").addEventListener("click", () => patchClip({kept: false}));
document.getElementById("t-start-input").addEventListener("change", e => {
  patchClip({t_start: parseFloat(e.target.value)});
});
document.getElementById("t-end-input").addEventListener("change", e => {
  patchClip({t_end: parseFloat(e.target.value)});
});

const player = document.getElementById("player");
const overlay = document.getElementById("captions-overlay");
player.addEventListener("timeupdate", () => {
  const t = player.currentTime;
  const active = state.transcript.find(w => w.start <= t && t < w.end);
  overlay.textContent = active ? active.word : "";
  overlay.style.top = "70%";
});

document.getElementById("finalize-btn").addEventListener("click", async () => {
  const r = await fetch("/api/finalize", {method: "POST"});
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  const progressDiv = document.getElementById("finalize-progress");
  while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value);
    for (const line of chunk.split("\n")) {
      if (line.startsWith("data:")) {
        const evt = JSON.parse(line.slice(5).trim());
        progressDiv.textContent = JSON.stringify(evt);
      }
    }
  }
});

document.getElementById("done-btn").addEventListener("click", async () => {
  await fetch("/api/shutdown", {method: "POST"});
  document.body.replaceChildren();
  const h = document.createElement("h1");
  h.style.padding = "32px";
  h.textContent = "Done. You can close this tab.";
  document.body.appendChild(h);
});

document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  const currentIdx = state.clips.findIndex(c => c.id === state.selectedId);
  if (e.key === "j" || e.key === "ArrowDown") {
    if (currentIdx < state.clips.length - 1) selectClip(state.clips[currentIdx + 1].id);
    e.preventDefault();
  } else if (e.key === "k" || e.key === "ArrowUp") {
    if (currentIdx > 0) selectClip(state.clips[currentIdx - 1].id);
    e.preventDefault();
  } else if (e.key === "y") {
    patchClip({kept: true});
  } else if (e.key === "n") {
    patchClip({kept: false});
  } else if (e.key === " ") {
    player.paused ? player.play() : player.pause();
    e.preventDefault();
  }
});

loadClips();
