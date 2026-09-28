"use strict";
// Boar X-Radar tab: collect a post's replies, then draw the dashboard from /radar/api.
// Loaded after app.js and uses its helpers ($, esc, store, EMOTIONS).

const RADAR_API = "/radar/api";
const RADAR = { config: null, dash: null, poll: null, started: false };
const fmt = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
const pct = (v) => `${Math.round(v * 100)}%`;
const emotionById = (id) => EMOTIONS.find((e) => e.id === id);

async function radarFetch(path, opts = {}) {
  const res = await fetch(RADAR_API + path, {
    ...opts, headers: { "content-type": "application/json", ...(opts.headers || {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = body.detail;
    throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : `HTTP ${res.status}`);
  }
  return body;
}

function radarStatus(html, isError = false) {
  $("#radar-status").innerHTML = isError ? `<span class="err">${html}</span>` : html;
}

// ── Tooltip (shared by every chart) ────────────────────────────────────────────
function showTip(evt, html) {
  const tip = $("#viz-tip");
  tip.innerHTML = html;
  tip.classList.remove("hidden");
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + w > innerWidth - 8) x = evt.clientX - w - pad;
  if (y + h > innerHeight - 8) y = evt.clientY - h - pad;
  tip.style.transform = `translate(${Math.max(8, x)}px, ${Math.max(8, y)}px)`;
}
const hideTip = () => $("#viz-tip").classList.add("hidden");

function bindTips(root, htmlFor) {
  root.querySelectorAll("[data-tip]").forEach((el) => {
    const html = () => htmlFor(el.dataset.tip);
    el.addEventListener("pointermove", (e) => showTip(e, html()));
    el.addEventListener("pointerleave", hideTip);
    el.addEventListener("focus", () => {
      const r = el.getBoundingClientRect();
      showTip({ clientX: r.right, clientY: r.top }, html());
    });
    el.addEventListener("blur", hideTip);
  });
}

function replyTip(r, extra = "") {
  const text = r.reply_content.length > 180 ? `${r.reply_content.slice(0, 180)}…` : r.reply_content;
  return `<div class="tip-user">@${esc(r.twitter_username)}</div><div>${esc(text)}</div>
    <div class="tip-meta">♥ ${fmt.format(r.like_count)} · 👁 ${fmt.format(r.view_count)}${extra}</div>`;
}

// ── KPI row ────────────────────────────────────────────────────────────────────
function renderKpis(d) {
  const counts = Object.entries(d.dominant_counts).filter(([k]) => k !== "neutral");
  counts.sort((a, b) => b[1] - a[1]);
  const [topId, topN] = counts[0] || [null, 0];
  const top = topId && emotionById(topId);
  const neutral = d.dominant_counts.neutral || 0;
  const share = (n) => (d.analyzed_total ? n / d.analyzed_total : 0);
  const tiles = [
    { label: "Replies analyzed", value: fmt.format(d.analyzed_total),
      sub: d.pending ? `of ${fmt.format(d.reply_total)} · ${d.pending} scoring…` : `of ${fmt.format(d.reply_total)} collected` },
    { label: "Likes", value: fmt.format(d.like_total), sub: "on the replies" },
    { label: "Views", value: fmt.format(d.view_total), sub: "on the replies" },
    top
      ? { label: "Predominant emotion", value: `${top.emoji} ${pct(share(topN))} ${top.label}`,
          sub: `of replies · ${pct(share(neutral))} neutral` }
      : { label: "Predominant emotion", value: d.analyzed_total ? "😐 Neutral" : "—",
          sub: d.analyzed_total ? "no emotion reached 50%" : "waiting for scores" },
  ];
  $("#radar-kpis").innerHTML = tiles.map((t) => `
    <div class="kpi"><div class="kpi-label">${t.label}</div>
      <div class="kpi-value">${t.value}</div><div class="kpi-sub">${esc(t.sub)}</div></div>`).join("");
}

// ── Emotion mix: share of replies each emotion leads (bars, one hue) ───────────
function renderMix(d) {
  const n = d.analyzed_total || 1;
  const rows = EMOTIONS.map((e) => ({ id: e.id, emoji: e.emoji, label: e.label,
    count: d.dominant_counts[e.id] || 0, mean: d.mean_emotions ? d.mean_emotions[e.id] : 0 }));
  rows.sort((a, b) => b.count - a.count || b.mean - a.mean);
  rows.push({ id: "neutral", emoji: "😐", label: "Neutral", count: d.dominant_counts.neutral || 0, mean: null });
  $("#radar-mix").innerHTML = rows.map((r) => `
    <div class="bar mix-row${r.id === "neutral" ? " neutral" : ""}" data-tip="${r.id}" tabindex="0">
      <span class="emo">${r.emoji}</span><span class="label">${r.label}</span>
      <div class="track"><div class="fill" style="width:${(r.count / n) * 100}%"></div></div>
      <span class="num">${pct(r.count / n)}</span>
    </div>`).join("");
  bindTips($("#radar-mix"), (id) => {
    const r = rows.find((x) => x.id === id);
    return `<b>${r.emoji} ${r.label}</b><div>${r.count} of ${d.analyzed_total} replies</div>` +
      (r.mean === null ? `<div class="tip-meta">no emotion reached 50%</div>`
        : `<div class="tip-meta">average intensity ${pct(r.mean)}</div>`);
  });
}

// ── Scatter: one emotion's intensity vs likes/views ────────────────────────────
function renderScatter(d) {
  const el = $("#radar-scatter");
  const emotion = $("#radar-emotion").value;
  const metric = $("#radar-metric").value;
  const pts = d.replies;
  if (!pts.length) { el.innerHTML = `<p class="hint">No scored replies yet.</p>`; return; }

  const W = Math.max(280, el.clientWidth), H = 280;
  const m = { l: 44, r: 22, t: 12, b: 34 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  // Engagement is heavily skewed, so the y-axis is log10(1 + n), up to the next power of ten.
  const ly = (v) => Math.log10(1 + v);
  const K = Math.max(1, Math.ceil(Math.log10(1 + Math.max(...pts.map((p) => p[metric])))));
  const top = ly(10 ** K);
  const x = (v) => m.l + v * iw;
  const y = (v) => m.t + ih - (ly(v) / top) * ih;
  const yTicks = [0, ...Array.from({ length: K }, (_, i) => 10 ** (i + 1))];

  const grid = yTicks.map((t) => `
    <line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}"/>
    <text class="tick" x="${m.l - 6}" y="${y(t) + 4}" text-anchor="end">${fmt.format(t)}</text>`).join("");
  const xTicks = [0, 0.25, 0.5, 0.75, 1].map((t) => `
    <text class="tick" x="${x(t)}" y="${H - m.b + 16}" text-anchor="middle">${pct(t)}</text>`).join("");
  const label = emotionById(emotion);
  // Draw strong replies last so they sit on top.
  const order = pts.map((p, i) => i).sort((a, b) => pts[a].emotions[emotion] - pts[b].emotions[emotion]);
  const dots = order.map((i) => {
    const p = pts[i], v = p.emotions[emotion];
    return `<g class="dot${v >= RADAR.config.threshold ? " on" : ""}" data-tip="${i}" tabindex="0">
      <circle class="hit" cx="${x(v)}" cy="${y(p[metric])}" r="11"/>
      <circle class="mark" cx="${x(v)}" cy="${y(p[metric])}" r="5"/></g>`;
  }).join("");

  el.innerHTML = `<svg width="${W}" height="${H}" role="img"
      aria-label="${label.label} intensity against ${metric === "like_count" ? "likes" : "views"} for ${pts.length} replies">
    ${grid}
    <line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${m.t + ih}" y2="${m.t + ih}"/>
    <line class="guide" x1="${x(0.5)}" x2="${x(0.5)}" y1="${m.t}" y2="${m.t + ih}"/>
    ${xTicks}
    <text class="axis-label" x="${m.l + iw}" y="${H - 2}" text-anchor="end">${label.emoji} ${label.label} intensity →</text>
    ${dots}
  </svg>`;
  bindTips(el, (i) => replyTip(pts[i], ` · ${label.emoji} ${pct(pts[i].emotions[emotion])}`));
}

// ── BOAR signals: one meter per question ───────────────────────────────────────
function renderSignals(d) {
  const n = d.analyzed_total;
  $("#radar-signals").innerHTML = Object.entries(RADAR.config.signals).map(([id, label]) => {
    const c = d.signal_counts[id] || 0, share = n ? c / n : 0;
    return `<div class="signal">
      <div class="row between"><span>${esc(label)}</span><b>${pct(share)}</b></div>
      <div class="track"><div class="fill" style="width:${share * 100}%"></div></div>
      <div class="kpi-sub">${c} of ${n} replies</div></div>`;
  }).join("");
}

// ── Highlight tables ───────────────────────────────────────────────────────────
function renderTable(el, rows, scoreOf, empty) {
  if (!rows.length) { el.innerHTML = `<p class="hint">${empty}</p>`; return; }
  el.innerHTML = `<table class="tops">
    <thead><tr><th>Reply</th><th class="n">Score</th><th class="n">♥</th><th class="n">👁</th></tr></thead>
    <tbody>${rows.map((r) => {
      const [score, why] = scoreOf(r);
      return `<tr><td><div class="who">@${esc(r.twitter_username)}${why ? ` · <span class="why">${why}</span>` : ""}</div>
        <div class="said">${esc(r.reply_content)}</div></td>
        <td class="n">${pct(score)}</td><td class="n">${fmt.format(r.like_count)}</td>
        <td class="n">${fmt.format(r.view_count)}</td></tr>`;
    }).join("")}</tbody></table>`;
}

const CRITICAL_LABEL = { anger: "😠 anger", disgust: "🤢 disgust", bug_report: "🐞 bug report" };

function renderDash(d) {
  RADAR.dash = d;
  $("#radar-dash").classList.remove("hidden");
  $("#radar-post").href = d.url;
  $("#radar-post").textContent = `@${d.profile_username} · post ${d.post_id} ↗`;
  $("#radar-scraped").textContent = `collected ${new Date(d.last_scraped_at).toLocaleString()}`;
  if (!$("#radar-emotion").dataset.touched) {
    const counts = Object.entries(d.dominant_counts).filter(([k]) => k !== "neutral").sort((a, b) => b[1] - a[1]);
    if (counts.length) $("#radar-emotion").value = counts[0][0];
  }
  renderKpis(d);
  renderMix(d);
  renderScatter(d);
  renderSignals(d);
  renderTable($("#radar-top-positive"), d.top_positive, (r) => [r.emotions.joy, ""],
    "No clearly positive replies (joy ≥ 50%).");
  renderTable($("#radar-top-critical"), d.top_critical, (r) => [r.critical_score, CRITICAL_LABEL[r.critical_reason]],
    "No alerts: no reply reached 50% anger, disgust or bug report.");
}

// ── Loading, polling, history ──────────────────────────────────────────────────
async function loadPost(postId, { quiet = false } = {}) {
  clearTimeout(RADAR.poll);
  if (!quiet) radarStatus("Loading…");
  try {
    const d = await radarFetch(`/posts/${encodeURIComponent(postId)}`);
    renderDash(d);
    store.set("radarPost", postId);
    $("#radar-history").value = postId;
    history.replaceState(null, "", `#radar/${encodeURIComponent(postId)}`);
    if (d.pending) {
      radarStatus(`Scoring on the GPU… ${d.analyzed_total} of ${d.reply_total} replies`);
      RADAR.poll = setTimeout(() => loadPost(postId, { quiet: true }), 1000);
    } else {
      radarStatus(`${d.analyzed_total} replies scored.`);
      refreshHistory();
    }
  } catch (e) {
    radarStatus(esc(e.message), true);
  }
}

async function refreshHistory() {
  const posts = await radarFetch(`/posts`).catch(() => []);
  const current = RADAR.dash?.post_id || "";
  $("#radar-history").innerHTML = `<option value="">${posts.length ? "Pick a post…" : "none yet"}</option>` +
    posts.map((p) => `<option value="${esc(p.post_id)}">@${esc(p.profile_username)} · ${esc(p.post_id)} · ${p.reply_total} replies · ${new Date(p.last_scraped_at).toLocaleDateString()}</option>`).join("");
  $("#radar-history").value = current;
}

async function ingest(body, what) {
  $("#radar-go").disabled = true;
  radarStatus(`${what}…`);
  try {
    const r = await radarFetch("/ingest", { method: "POST", body: JSON.stringify(body) });
    radarStatus(`Stored ${r.stored} replies${r.skipped ? ` (${r.skipped} skipped: no text or not a reply)` : ""}. Scoring…`);
    await refreshHistory();
    await loadPost(r.post_id, { quiet: true });
  } catch (e) {
    radarStatus(esc(e.message), true);
  } finally {
    $("#radar-go").disabled = false;
  }
}

async function initRadar() {
  RADAR.config = await radarFetch("/config");
  $("#radar-emotion").innerHTML = EMOTIONS.map((e) => `<option value="${e.id}">${e.emoji} ${e.label}</option>`).join("");
  $("#radar-source").innerHTML = RADAR.config.scraping
    ? "Replies are collected with the Apify comment scraper and scored on the local GPU; or"
    : "Scraping is off: set <code>APIFY_TOKEN</code> on the server to collect replies; or";

  $("#radar-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const url = $("#radar-url").value.trim();
    if (url) ingest({ post_url: url }, "Collecting replies (this can take a minute)");
  });
  $("#radar-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const url = $("#radar-url").value.trim();
    if (!url) { radarStatus("Paste the post URL or id first, so the replies are filed under it.", true); return; }
    let items;
    try {
      items = JSON.parse(await file.text());
      if (!Array.isArray(items)) throw new Error("expected a JSON array of replies");
    } catch (err) {
      radarStatus(`Could not read ${esc(file.name)}: ${esc(err.message)}`, true);
      return;
    }
    ingest({ post_url: url, items }, `Importing ${items.length} replies`);
  });
  $("#radar-history").addEventListener("change", (e) => e.target.value && loadPost(e.target.value));
  $("#radar-emotion").addEventListener("change", (e) => { e.target.dataset.touched = "1"; RADAR.dash && renderScatter(RADAR.dash); });
  $("#radar-metric").addEventListener("change", () => RADAR.dash && renderScatter(RADAR.dash));
  new ResizeObserver(() => RADAR.dash && renderScatter(RADAR.dash)).observe($("#radar-scatter"));

  await refreshHistory();
  const linked = decodeURIComponent(location.hash.split("/")[1] || "");
  const last = linked || store.get("radarPost", null);
  if (last && [...$("#radar-history").options].some((o) => o.value === last)) loadPost(last);
}

document.addEventListener("tabchange", (e) => {
  if (e.detail !== "radar" || RADAR.started) return;
  RADAR.started = true;
  initRadar().catch((err) => radarStatus(`Radar unavailable: ${esc(err.message)}`, true));
});
