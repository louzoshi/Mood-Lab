"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

let CONFIG = null;
let EMOTIONS = [];

const SAMPLES = [
  "Oh great, another Monday. Just what I needed 🙄",
  "Juro que não fui eu que comi o último pedaço do bolo.",
  "I honestly swear on my life I have never, ever been late. Not once.",
  "Meu cachorro morreu hoje de manhã. Ele tinha 14 anos.",
  "WE WON THE CHAMPIONSHIP!!! I can't believe it!",
  "Tem uma barata no meu café. Uma barata. No meu café.",
  "O quê?! Você vai casar? Com QUEM?",
  "There's someone in the house. I can hear footsteps upstairs.",
];

// ── API ────────────────────────────────────────────────────────────────────────
async function analyze(text, extraQuestions = null) {
  const questions = extraQuestions ? { ...CONFIG.presets.questions, ...extraQuestions } : null;
  const res = await fetch("/api/analyze", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text, questions, backend: $("#backend").value, model: $("#model").value }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail ? JSON.stringify(body.detail) : `HTTP ${res.status}`);
  return body;
}

// ── Bars ───────────────────────────────────────────────────────────────────────
function levelName(v) {
  return CONFIG.presets.levels[Math.min(3, Math.round(v * 3))];
}

function renderBars(el, answers, { only = null, targets = {} } = {}) {
  const list = only ? EMOTIONS.filter((e) => only.includes(e.id)) : EMOTIONS;
  if (!el.children.length || el.dataset.keys !== list.map((e) => e.id).join()) {
    el.dataset.keys = list.map((e) => e.id).join();
    el.innerHTML = list.map((e) => `
      <div class="bar" data-id="${e.id}">
        <span class="emo">${e.emoji}</span><span class="label">${e.label}</span>
        <div class="track"><div class="fill"></div></div><span class="num">—</span>
      </div>`).join("");
  }
  for (const e of list) {
    const row = el.querySelector(`[data-id="${e.id}"]`);
    const a = answers?.[e.id];
    const v = a ? a.value : 0;
    row.querySelector(".fill").style.width = `${Math.round(v * 100)}%`;
    row.querySelector(".num").textContent = a ? `${Math.round(v * 100)}%` : "—";
    row.title = a ? `${levelName(v)} · confidence ${Math.round((a.confidence ?? 0) * 100)}%` : "";
    row.querySelector(".target")?.remove();
    if (targets[e.id] !== undefined) {
      const t = document.createElement("div");
      t.className = "target";
      t.style.left = `${targets[e.id] * 100}%`;
      row.querySelector(".track").appendChild(t);
    }
  }
}

// ── Playground ─────────────────────────────────────────────────────────────────
let customQs = store.get("customQs", [
  { type: "noul", instructions: "Is the writer trying to hide something?", criteria: "" },
]);
let pending = 0;

function customQuestionPayload() {
  const out = {};
  customQs.forEach((q, i) => {
    if (!q.instructions.trim()) return;
    const opts = q.criteria.split("|").map((s) => s.trim()).filter(Boolean);
    if (q.type === "noul") out[`custom_${i}`] = { type: "noul", instructions: q.instructions };
    else if (opts.length >= 2) {
      out[`custom_${i}`] = q.type === "score"
        ? { type: "score", instructions: q.instructions, criteria: opts }
        : { type: "choice", instructions: q.instructions, criteria: Object.fromEntries(opts.map((o) => [o, o])) };
    }
  });
  return out;
}

function renderCustomEditor() {
  $("#custom-list").innerHTML = customQs.map((q, i) => `
    <div class="cq" data-i="${i}">
      <select data-f="type">
        ${["noul", "score", "choice"].map((t) => `<option ${t === q.type ? "selected" : ""}>${t}</option>`).join("")}
      </select>
      <input type="text" data-f="instructions" value="${esc(q.instructions)}" placeholder="Question" />
      <button data-del title="Remove">✕</button>
      ${q.type === "noul" ? "" : `<input type="text" class="criteria" data-f="criteria" value="${esc(q.criteria)}"
        placeholder="${q.type === "score" ? "not at all | a bit | very" : "option a | option b | option c"}" />`}
    </div>`).join("");
}

function renderCustomResults(answers) {
  const qs = customQuestionPayload();
  const ids = Object.keys(qs);
  if (!ids.length) { $("#custom-results").innerHTML = ""; return; }
  $("#custom-results").innerHTML = `<div class="cr">${ids.map((id) => {
    const q = qs[id], a = answers[id];
    if (!a) return "";
    let main;
    if (a.type === "noul") main = `${a.value >= 0.5 ? "Yes" : "No"} · ${Math.round(a.value * 100)}% yes`;
    else if (a.type === "score") main = `${q.criteria[Math.round(a.value * (q.criteria.length - 1))]} · ${Math.round(a.value * 100)}%`;
    else main = `${a.choice} · ${Math.round(a.value * 100)}%`;
    const dist = a.type === "noul" ? "" : `<div class="dist">${Object.entries(a.probabilities).map(([k, p]) =>
      `<span>${esc(a.type === "score" ? q.criteria[k] : k)} ${Math.round(p * 100)}%</span>`).join("")}</div>`;
    return `<div class="cr-item"><div class="q">${esc(q.instructions)}</div><div class="a">${esc(main)}</div>${dist}</div>`;
  }).join("")}</div>`;
}

function vibeOf(a) {
  const pos = a.joy.value;
  const neg = Math.max(a.sadness.value, a.anger.value, a.fear.value, a.disgust.value);
  if (pos >= 0.5 && neg >= 0.5) return "mixed";
  if (Math.max(pos, neg) < 0.3) return "neutral";
  return pos > neg ? "positive" : "negative";
}

async function runPlayground() {
  const text = $("#text").value.trim();
  if (!text) return;
  const seq = ++pending;
  $("#bars").classList.add("loading");
  try {
    const r = await analyze(text, customQuestionPayload());
    if (seq !== pending) return; // a newer request superseded this one
    renderBars($("#bars"), r.answers);
    const vibe = vibeOf(r.answers);
    $("#vibe").className = `vibe ${vibe}`;
    $("#vibe").textContent = vibe;
    renderCustomResults(r.answers);
    $("#meta").textContent = `${r.model} · ${r.latency_ms} ms${r.reason ? ` · ${r.reason}` : ""}`;
  } catch (e) {
    if (seq === pending) $("#meta").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  } finally {
    if (seq === pending) $("#bars").classList.remove("loading");
  }
}

function initPlayground() {
  renderBars($("#bars"), null);
  $("#samples").innerHTML = SAMPLES.map((s) => `<span class="chip" title="${esc(s)}">${esc(s)}</span>`).join("");
  $("#samples").addEventListener("click", (e) => {
    if (!e.target.classList.contains("chip")) return;
    $("#text").value = e.target.title;
    runPlayground();
  });

  let timer;
  $("#text").addEventListener("input", () => {
    if (!$("#live").checked) return;
    clearTimeout(timer);
    timer = setTimeout(runPlayground, 450);
  });
  $("#text").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); runPlayground(); }
  });
  $("#analyze").addEventListener("click", runPlayground);

  renderCustomEditor();
  $("#custom-list").addEventListener("input", (e) => {
    const i = +e.target.closest(".cq").dataset.i, f = e.target.dataset.f;
    if (!f) return;
    customQs[i][f] = e.target.value;
    store.set("customQs", customQs);
    if (f === "type") renderCustomEditor();
  });
  $("#custom-list").addEventListener("click", (e) => {
    if (!e.target.hasAttribute("data-del")) return;
    customQs.splice(+e.target.closest(".cq").dataset.i, 1);
    store.set("customQs", customQs);
    renderCustomEditor();
  });
  $("#custom-add").addEventListener("click", () => {
    customQs.push({ type: "noul", instructions: "", criteria: "" });
    renderCustomEditor();
  });
}

// ── Game: Hit the Mood ─────────────────────────────────────────────────────────
// Everyone gets the same target each round (e.g. Joy HIGH + Sarcasm HIGH), writes a line,
// and scores by how close the model's reading lands to the target levels.
const LEVEL_VALUES = { none: 0, low: 1 / 3, medium: 2 / 3, high: 1 };
const game = { players: store.get("players", ["Player 1", "Player 2"]), rounds: 3, round: 0, turn: 0, target: null, scores: {}, log: [] };

function pickTarget() {
  const pool = EMOTIONS.filter((e) => e.game).sort(() => Math.random() - 0.5);
  const count = Math.random() < 0.35 ? 3 : 2;
  const levels = Object.keys(LEVEL_VALUES);
  let picks;
  do {
    picks = pool.slice(0, count).map((e) => ({ ...e, level: levels[Math.floor(Math.random() * 4)] }));
  } while (picks.every((p) => p.level === "none"));
  return picks;
}

function targetCard(target) {
  return `<div class="target-card">${target.map((t) => `
    <div class="pill"><span class="emo">${t.emoji}</span><span>${t.label}</span>
    <span class="lvl ${t.level}">${t.level}</span></div>`).join("")}</div>`;
}

function points(target, answers) {
  const closeness = target.map((t) => 1 - Math.abs(answers[t.id].value - LEVEL_VALUES[t.level]));
  return Math.round(100 * closeness.reduce((a, b) => a + b, 0) / closeness.length);
}

function gameSetup() {
  $("#game-root").innerHTML = `
    <h1>🎯 Hit the Mood</h1>
    <p class="muted">Every round shows a mood target. Each player writes one line that should land on
    it, then the model scores how close you got. House rule: you can't use the emotion's own name.</p>
    <div class="players" id="players">${game.players.map((p, i) => `
      <div class="row"><input type="text" value="${esc(p)}" data-i="${i}" /><button data-del="${i}">✕</button></div>`).join("")}
    </div>
    <div class="row between">
      <button id="add-player" class="ghost">+ player</button>
      <label class="row">Rounds <select id="rounds">${[3, 5, 7].map((n) => `<option ${n === game.rounds ? "selected" : ""}>${n}</option>`).join("")}</select></label>
    </div>
    <button id="start" class="primary">Start game</button>`;
  $("#players").addEventListener("input", (e) => { game.players[+e.target.dataset.i] = e.target.value; });
  $("#players").addEventListener("click", (e) => {
    if (e.target.dataset.del === undefined || game.players.length <= 1) return;
    game.players.splice(+e.target.dataset.del, 1); gameSetup();
  });
  $("#add-player").onclick = () => { game.players.push(`Player ${game.players.length + 1}`); gameSetup(); };
  $("#start").onclick = () => {
    game.players = game.players.map((p) => p.trim()).filter(Boolean);
    if (!game.players.length) return;
    store.set("players", game.players);
    game.rounds = +$("#rounds").value;
    game.round = 0;
    game.scores = Object.fromEntries(game.players.map((p) => [p, 0]));
    nextRound();
  };
}

function nextRound() {
  game.round += 1;
  game.turn = 0;
  game.target = pickTarget();
  game.log = [];
  passScreen();
}

function passScreen() {
  const player = game.players[game.turn];
  $("#game-root").innerHTML = `
    <div class="muted center">Round ${game.round} / ${game.rounds}</div>
    <div class="big center">📱 Pass to <b>${esc(player)}</b></div>
    <button id="ready" class="primary">I'm ${esc(player)}, show me the target</button>`;
  $("#ready").onclick = writeScreen;
}

function writeScreen() {
  const player = game.players[game.turn];
  $("#game-root").innerHTML = `
    <div class="row between"><b>${esc(player)}</b><span class="muted">Round ${game.round} / ${game.rounds}</span></div>
    ${targetCard(game.target)}
    <textarea id="line" rows="3" maxlength="400" placeholder="Write a line that hits this mood…"></textarea>
    <div class="row between"><span id="gerr" class="err"></span><button id="submit" class="primary">Lock it in</button></div>`;
  $("#line").focus();
  const submit = async () => {
    const text = $("#line").value.trim();
    if (!text) return;
    $("#submit").disabled = true; $("#submit").textContent = "Reading…";
    try {
      const r = await analyze(text);
      revealScreen(text, r.answers);
    } catch (e) {
      $("#gerr").textContent = e.message;
      $("#submit").disabled = false; $("#submit").textContent = "Lock it in";
    }
  };
  $("#submit").onclick = submit;
  $("#line").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } });
}

function revealScreen(text, answers) {
  const player = game.players[game.turn];
  const pts = points(game.target, answers);
  game.scores[player] += pts;
  game.log.push({ player, text, pts });
  const targets = Object.fromEntries(game.target.map((t) => [t.id, LEVEL_VALUES[t.level]]));
  const verdict = pts >= 90 ? "🔥 Bullseye!" : pts >= 75 ? "😎 Close!" : pts >= 55 ? "🤔 Meh." : "💀 Way off.";
  $("#game-root").innerHTML = `
    <div class="muted center">${esc(player)} said: <i>“${esc(text)}”</i></div>
    <div class="score">${pts}</div>
    <div class="big center">${verdict}</div>
    <div class="bars" id="gbars"></div>
    <p class="muted center" style="margin:0">The black mark is the target.</p>
    <details><summary class="muted">Full reading</summary><div class="bars" id="gall" style="margin-top:10px"></div></details>
    <button id="next" class="primary">${game.turn + 1 < game.players.length ? "Next player" : "Round results"}</button>`;
  renderBars($("#gbars"), answers, { only: game.target.map((t) => t.id), targets });
  renderBars($("#gall"), answers);
  $("#next").onclick = () => {
    game.turn += 1;
    game.turn < game.players.length ? passScreen() : roundScreen();
  };
}

function roundScreen() {
  const ranked = [...game.log].sort((a, b) => b.pts - a.pts);
  const last = game.round >= game.rounds;
  $("#game-root").innerHTML = `
    <h1>Round ${game.round} results</h1>
    ${targetCard(game.target)}
    <div class="board">${ranked.map((l, i) => `
      <div class="line"><span>${["🥇", "🥈", "🥉"][i] ?? "·"}</span><b>${esc(l.player)}</b><span>${l.pts}</span>
      <span class="said">“${esc(l.text)}”</span></div>`).join("")}</div>
    <button id="go" class="primary">${last ? "Final scores" : "Next round"}</button>`;
  $("#go").onclick = last ? finalScreen : nextRound;
}

function finalScreen() {
  const ranked = Object.entries(game.scores).sort((a, b) => b[1] - a[1]);
  $("#game-root").innerHTML = `
    <div class="score">🏆</div>
    <div class="big center">${esc(ranked[0][0])} wins!</div>
    <div class="board">${ranked.map(([p, s], i) => `
      <div class="line"><span>${["🥇", "🥈", "🥉"][i] ?? "·"}</span><b>${esc(p)}</b><span>${s}</span></div>`).join("")}</div>
    <button id="again" class="primary">Play again</button>`;
  $("#again").onclick = gameSetup;
}

// ── Boot ───────────────────────────────────────────────────────────────────────
async function boot() {
  CONFIG = await (await fetch("/api/config")).json();
  EMOTIONS = CONFIG.presets.emotions;
  $("#backend").innerHTML = CONFIG.backends.map((b) => `<option value="${b}">${b === "laya" ? "Laya (local)" : "Jev (cloud)"}</option>`).join("");
  $("#model").innerHTML = CONFIG.laya_models.map((m) => `<option>${m}</option>`).join("");
  $("#backend").addEventListener("change", () => { $("#model").classList.toggle("hidden", $("#backend").value !== "laya"); });

  const tabs = document.querySelectorAll(".tab");
  tabs.forEach((t) => t.addEventListener("click", () => {
    tabs.forEach((x) => x.classList.toggle("active", x === t));
    tabs.forEach((x) => $(`#tab-${x.dataset.tab}`).classList.toggle("hidden", x !== t));
    // The radar is scored with the server's settings, not this backend/model picker.
    $(".engine").classList.toggle("hidden", t.dataset.tab === "radar");
    if (location.hash.slice(1).split("/")[0] !== t.dataset.tab) {
      history.replaceState(null, "", t.dataset.tab === "play" ? location.pathname : `#${t.dataset.tab}`);
    }
    document.dispatchEvent(new CustomEvent("tabchange", { detail: t.dataset.tab }));
  }));

  initPlayground();
  gameSetup();
  // "#game", "#radar" or "#radar/<post id>" opens that tab.
  document.querySelector(`.tab[data-tab="${location.hash.slice(1).split("/")[0]}"]`)?.click();
}

boot();
