"use strict";

// ---------- tiny helpers ----------
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

let toastTimer;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.innerHTML = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = "toast"), 3200);
}

// ---------- minimal markdown -> html ----------
function md(src) {
  if (!src) return '<p class="empty">Nothing here yet.</p>';
  const lines = src.replace(/<details>|<\/details>|<summary>.*?<\/summary>/g, "").split("\n");
  let html = "", inUl = false, inCode = false, code = "";
  const flushUl = () => { if (inUl) { html += "</ul>"; inUl = false; } };
  for (let raw of lines) {
    if (raw.trim().startsWith("```")) {
      if (inCode) { html += `<pre><code>${esc(code)}</code></pre>`; code = ""; inCode = false; }
      else { flushUl(); inCode = true; }
      continue;
    }
    if (inCode) { code += raw + "\n"; continue; }
    let line = esc(raw);
    line = line.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
    line = line.replace(/_(.+?)_/g, "<em>$1</em>");
    line = line.replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank">$1</a>');
    if (/^#{1,4}\s/.test(raw)) {
      flushUl();
      const lvl = raw.match(/^#+/)[0].length;
      html += `<h${lvl}>${line.replace(/^#{1,4}\s/, "")}</h${lvl}>`;
    } else if (/^\s*[-*]\s/.test(raw)) {
      if (!inUl) { html += "<ul>"; inUl = true; }
      html += `<li>${line.replace(/^\s*[-*]\s/, "")}</li>`;
    } else if (raw.trim() === "") {
      flushUl();
    } else {
      flushUl();
      html += `<p>${line}</p>`;
    }
  }
  flushUl();
  if (inCode) html += `<pre><code>${esc(code)}</code></pre>`;
  return html;
}

// ---------- scoring presentation ----------
function bandClass(score, gate) {
  if (score == null) return ["s-none", "unscored"];
  if (!gate) return ["s-fail", "FAIL"];
  if (score >= 4) return ["s-strong", "strong"];
  if (score >= 3) return ["s-solid", "solid"];
  if (score >= 2) return ["s-weak", "marginal"];
  return ["s-weak", "weak"];
}

const STATUS_ORDER = ["discovered", "scored", "tailored", "applied", "screening", "interview", "offer", "rejected", "skipped"];

// ---------- state / render ----------
let STATE = null;
let HUMAN_ONLY = [];

async function refresh() {
  STATE = await api("/api/state");
  HUMAN_ONLY = STATE.human_only || [];
  renderStats();
  renderBoard();
}

function renderStats() {
  const c = STATE.counts || {};
  const total = Object.values(c).reduce((a, b) => a + b, 0);
  const lead = STATE.gap_lead;
  const cards = [
    ["Tracked jobs", total],
    ["Applied (7d)", STATE.weekly_applications],
    ["In interview", (c.interview || 0) + (c.offer || 0)],
  ];
  let html = cards.map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
  if (lead) {
    html += `<div class="stat gap"><div class="k">Highest-leverage skill to learn next</div>
      <div class="v"><span class="skill">${esc(lead.skill)}</span> · wanted by ${lead.jobs} job(s)<br>
      <span style="color:var(--muted);font-weight:500;font-size:13px">${esc(lead.suggestion)}</span></div></div>`;
  }
  $("#stats").innerHTML = html;

  // action bar: score-all + follow-up reminders
  const bar = $("#actionbar");
  let abHtml = "";
  if (STATE.unscored > 0) {
    abHtml += `<button class="btn sm primary" id="score-all">⚖ Score all (${STATE.unscored})</button>`;
  }
  const fu = STATE.followups || [];
  if (fu.length) {
    const items = fu.slice(0, 4).map((f) =>
      `<span class="fu-item" data-id="${f.job_id}">${esc(f.company || f.title || ("#" + f.job_id))} · ${f.days_since}d</span>`).join("");
    abHtml += `<div class="fu"><span class="fu-label">⏰ Follow up (${fu.length}):</span> ${items}</div>`;
  }
  bar.innerHTML = abHtml;
  const sa = $("#score-all");
  if (sa) sa.addEventListener("click", () => scoreAll(sa));
  $$(".fu-item", bar).forEach((el) => el.addEventListener("click", () => openDrawer(+el.dataset.id)));
}

async function scoreAll(btn) {
  const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<span class="spin"></span> scoring`;
  try {
    const r = await api("/api/score-all", { method: "POST" });
    toast(r.failed ? `Scored ${r.scored}. ${r.failed} need jd_agent.` : `Scored ${r.scored} job(s). Board re-ranked.`, r.failed > 0);
    await refresh();
  } catch (e) { toast(e.message, true); btn.disabled = false; btn.innerHTML = old; }
}

function renderBoard() {
  const byStatus = {};
  STATUS_ORDER.forEach((s) => (byStatus[s] = []));
  (STATE.jobs || []).forEach((j) => (byStatus[j.status] || (byStatus[j.status] = [])).push(j));

  const board = $("#board");
  board.innerHTML = STATUS_ORDER.map((s) => {
    const jobs = byStatus[s] || [];
    const cards = jobs.map(cardHtml).join("") || `<div class="empty">—</div>`;
    return `<div class="col"><h3>${s}<span class="count">${jobs.length}</span></h3><div class="col-body">${cards}</div></div>`;
  }).join("");

  $$(".card", board).forEach((el) => el.addEventListener("click", () => openDrawer(+el.dataset.id)));
}

function cardHtml(j) {
  const [cls, label] = bandClass(j.score, j.gate_passed);
  let pill;
  if (j.score != null) {
    pill = `<span class="score-pill ${cls}">${j.score.toFixed(1)} · ${label}</span>`;
  } else if (j.quick_fit != null) {
    const qc = j.quick_fit >= 60 ? "s-strong" : j.quick_fit >= 35 ? "s-solid" : "s-weak";
    pill = `<span class="score-pill ${qc}" title="Quick fit estimate — run Score all for the full rubric">≈${j.quick_fit}% fit</span>`;
  } else {
    pill = `<span class="score-pill s-none">unscored</span>`;
  }
  return `<div class="card" data-id="${j.id}">
    <div class="ct">${esc(j.title || "(untitled)")}</div>
    <div class="cc">${esc(j.company || "—")}${j.location ? " · " + esc(j.location) : ""}</div>
    <div class="crow">${pill}<span class="cc">#${j.id}</span></div>
  </div>`;
}

// ---------- drawer ----------
let CURRENT = null;

async function openDrawer(id) {
  $("#overlay").classList.add("show");
  $("#drawer").classList.add("show");
  $("#drawer-body").innerHTML = `<p class="empty">Loading…</p>`;
  try {
    CURRENT = await api(`/api/jobs/${id}`);
    renderDrawer(CURRENT);
  } catch (e) {
    $("#drawer-body").innerHTML = `<p class="empty">${esc(e.message)}</p>`;
  }
}
function closeDrawer() {
  $("#overlay").classList.remove("show");
  $("#drawer").classList.remove("show");
  CURRENT = null;
}

function renderDrawer(j) {
  const statusOpts = STATE.statuses.map((s) =>
    `<option value="${s}" ${s === j.status ? "selected" : ""}>${s}</option>`).join("");

  let scoreHtml = `<p class="empty">Not scored yet.</p>`;
  if (j.score != null && j.dimensions) {
    const [cls, label] = bandClass(j.score, j.gate_passed);
    const dims = j.dimensions;
    const rat = parseRationale(j.rationale);
    const order = WEIGHTS_ORDER(j.weights);
    const dimHtml = order.map((name) => {
      const v = dims[name] ?? 0;
      const isGate = (j.gates || []).includes(name);
      const gateCls = isGate ? (v >= 3 ? "gate" : "gatefail") : "";
      return `<div class="dim">
        <div class="dl"><span class="name">${esc(name)}${isGate ? '<span class="g">GATE</span>' : ""}</span><span class="why">${v}/5</span></div>
        <div class="bar ${gateCls}"><span style="width:${(v / 5) * 100}%"></span></div>
        <div class="why" style="font-size:11.5px;margin-top:3px">${esc(rat[name] || "")}</div>
      </div>`;
    }).join("");
    scoreHtml = `<div class="overall-wrap">
        <div class="overall">${j.score.toFixed(1)}<small>/5</small></div>
        <span class="gate ${j.gate_passed ? "pass" : "fail"}">${j.gate_passed ? "GATE PASS · " + label : "GATE FAIL"}</span>
      </div>
      <div style="margin-top:14px">${dimHtml}</div>`;
  }

  let atsHtml = `<p class="empty">ATS analysis needs the resume engine (jd_agent).</p>`;
  if (j.ats && j.ats.available) {
    const have = (j.ats.present || []).map((k) => `<span class="chip have">${esc(k)}</span>`).join("");
    const miss = (j.ats.missing || []).map((k) => `<span class="chip miss">${esc(k)}</span>`).join("") || `<span class="chip have">none — full coverage</span>`;
    atsHtml = `<div class="ring-wrap">
        <div class="ring" style="--p:${j.ats.coverage}"><div class="inner">${j.ats.coverage}%</div></div>
        <div>
          <div style="font-weight:600">Best resume: ${esc(j.ats.track)}</div>
          <div class="why" style="font-size:12.5px;color:var(--muted)">${j.ats.coverage}% of JD keywords already in your resume.</div>
        </div>
      </div>
      <h4 style="margin-top:16px">Missing keywords (close these to raise hire odds)</h4>
      <div class="chips">${miss}</div>
      <h4 style="margin-top:14px">Already covered</h4>
      <div class="chips">${have || '<span class="empty">—</span>'}</div>`;
  }

  const docLinks = [];
  if (j.resume_path) docLinks.push(`<a class="btn sm" href="/api/jobs/${j.id}/file/resume.pdf" target="_blank">⬇ Resume PDF</a>`);
  if (j.cover_path) docLinks.push(`<a class="btn sm" href="/api/jobs/${j.id}/file/coverletter.pdf" target="_blank">⬇ Cover PDF</a>`);

  const human = HUMAN_ONLY.includes(j.status);

  let legitHtml = "";
  if (j.legitimacy && j.legitimacy.risk && j.legitimacy.risk !== "clear") {
    const high = j.legitimacy.risk === "high_risk";
    legitHtml = `<div class="legit ${high ? "high" : "caution"}">${high ? "🚩 High risk" : "⚠️ Caution"} — ${esc(j.legitimacy.summary)}</div>`;
  }

  $("#drawer-body").innerHTML = `
    <div class="d-head">
      <div>
        <h2>${esc(j.title || "(untitled)")}</h2>
        <div class="sub">${esc(j.company || "—")}${j.location ? " · " + esc(j.location) : ""}</div>
      </div>
      <button class="x" id="close-x">×</button>
    </div>
    ${j.url ? `<a class="btn primary apply-cta" href="${esc(j.url)}" target="_blank" rel="noopener">Open posting & Apply ↗</a>` : ""}
    ${legitHtml}

    <div class="d-section">
      <h4>Actions</h4>
      <div class="actions">
        <button class="btn sm" data-act="score">⚖ Score</button>
        <button class="btn sm" data-act="tailor">✍ Tailor</button>
        <button class="btn sm" data-act="research">🏢 Research</button>
        <button class="btn sm" data-act="prep">🎤 Prep</button>
        <button class="btn sm" data-act="outreach">🤝 Outreach</button>
        <button class="btn sm primary" data-act="packet">📄 Packet</button>
        ${docLinks.join("")}
        <button class="btn sm danger" data-act="delete">🗑</button>
      </div>
      <div class="statusline">
        <span class="why" style="color:var(--muted)">Status</span>
        <select id="status-sel">${statusOpts}</select>
        <input id="status-note" placeholder="note (optional)" style="flex:1" />
        <button class="btn sm" id="status-save">Update</button>
      </div>
      ${human ? '<p class="hint">You are recording an action you took. JobPilot never sets applied/interview/offer for you.</p>' : ""}
    </div>

    <div class="d-section"><h4>Fit score</h4>${scoreHtml}</div>
    <div class="d-section"><h4>ATS keyword match</h4>${atsHtml}</div>

    <div class="d-section">
      <h4>Materials &amp; briefs</h4>
      <div class="arttabs" id="arttabs"></div>
      <div class="md" id="artview"></div>
    </div>`;

  $("#close-x").addEventListener("click", closeDrawer);
  $$("[data-act]").forEach((b) => b.addEventListener("click", () => doAction(b.dataset.act, j.id, b)));
  $("#status-save").addEventListener("click", () => saveStatus(j.id));
  renderArtTabs(j);
}

function WEIGHTS_ORDER(weights) {
  // gates first, then by weight desc
  const names = Object.keys(weights || {});
  const gates = ["Role Match", "Skills Alignment"];
  const rest = names.filter((n) => !gates.includes(n)).sort((a, b) => (weights[b] - weights[a]));
  return [...gates.filter((g) => names.includes(g)), ...rest];
}

function parseRationale(text) {
  const out = {};
  (text || "").split("\n").forEach((ln) => {
    const m = ln.match(/^(.+?)\s*\(\d\/5\):\s*(.*)$/);
    if (m) out[m[1].trim()] = m[2].trim();
  });
  return out;
}

function renderArtTabs(j) {
  const arts = j.artifacts || {};
  const tabs = [
    ["packet", "Packet"], ["research", "Research"], ["prep", "Prep"], ["outreach", "Outreach"],
    ["evidence", "Evidence"], ["receipt", "Honesty receipt"], ["tailor_prompt", "Tailor prompt"],
  ].filter(([k]) => arts[k]);
  const tabBar = $("#arttabs");
  if (!tabs.length) {
    tabBar.innerHTML = "";
    $("#artview").innerHTML = `<p class="empty">Run an action above to generate briefs (packet, research, prep, tailored docs).</p>`;
    return;
  }
  tabBar.innerHTML = tabs.map(([k, label], i) =>
    `<div class="arttab ${i === 0 ? "active" : ""}" data-art="${k}">${label}</div>`).join("");
  const show = (k) => {
    const isProm = k === "tailor_prompt";
    $("#artview").innerHTML = isProm ? `<pre>${esc(arts[k])}</pre>` : md(arts[k]);
  };
  $$(".arttab", tabBar).forEach((t) => t.addEventListener("click", () => {
    $$(".arttab", tabBar).forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    show(t.dataset.art);
  }));
  show(tabs[0][0]);
}

// ---------- actions ----------
async function doAction(act, id, btn) {
  if (act === "delete") {
    if (!confirm("Delete this job and its files?")) return;
    await api(`/api/jobs/${id}`, { method: "DELETE" });
    closeDrawer(); toast("Deleted."); refresh();
    return;
  }
  const labels = { score: "Scoring", tailor: "Tailoring", research: "Researching", prep: "Building prep", packet: "Assembling packet", outreach: "Drafting outreach" };
  const old = btn.innerHTML;
  btn.disabled = true; btn.innerHTML = `<span class="spin"></span>`;
  try {
    let body = "{}";
    if (act === "tailor") {
      const reply = prompt("Optional: paste a Claude reply (TRACK/SUMMARY/COVER LETTER) to also build the cover letter. Leave blank to just build the tailored resume + prompt.");
      body = JSON.stringify({ reply: reply || null });
    }
    const r = await api(`/api/jobs/${id}/${act}`, { method: "POST", body });
    if (act === "tailor" && r.honesty_ok === false) {
      toast(`Tailored. ⚠ Honesty guard rejected a summary adding: ${esc((r.violations || []).join(", "))}. Used your real summary.`, true);
    } else {
      toast(`${labels[act]} done.`);
    }
    CURRENT = await api(`/api/jobs/${id}`);
    renderDrawer(CURRENT);
    refresh();
  } catch (e) {
    toast(e.message, true);
    btn.disabled = false; btn.innerHTML = old;
  }
}

async function saveStatus(id) {
  const status = $("#status-sel").value;
  const note = $("#status-note").value;
  try {
    const r = await api(`/api/jobs/${id}/status`, { method: "POST", body: JSON.stringify({ status, note }) });
    toast(r.human_action ? "Recorded as your action." : "Status updated.");
    CURRENT = await api(`/api/jobs/${id}`);
    renderDrawer(CURRENT);
    refresh();
  } catch (e) { toast(e.message, true); }
}

// ---------- add / discover ----------
async function addPaste() {
  const jd = $("#p-jd").value.trim();
  if (!jd) return toast("Paste a job description first.", true);
  try {
    const r = await api("/api/jobs", { method: "POST", body: JSON.stringify({
      title: $("#p-title").value, company: $("#p-company").value, location: $("#p-location").value, jd_text: jd,
    }) });
    ["p-jd", "p-title", "p-company", "p-location"].forEach((i) => ($("#" + i).value = ""));
    toast(r.created ? "Job added." : "Already tracked.");
    await refresh();
    openDrawer(r.id);
  } catch (e) { toast(e.message, true); }
}

async function addUrl(btn) {
  const url = $("#u-url").value.trim();
  if (!url) return toast("Enter a URL.", true);
  const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<span class="spin"></span> fetching`;
  try {
    const r = await api("/api/jobs/fetch", { method: "POST", body: JSON.stringify({ url }) });
    $("#u-url").value = "";
    toast(r.created ? "Fetched and added." : "Already tracked.");
    await refresh();
    openDrawer(r.id);
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.innerHTML = old; }
}

async function bulkAddScore(results, btn) {
  const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<span class="spin"></span> adding`;
  try {
    // Instant: add with a quick fit estimate; full rubric is deferred to "Score all".
    const r = await api("/api/jobs/bulk", { method: "POST", body: JSON.stringify({
      jobs: results.map((j) => ({ url: j.url, title: j.title, company: j.company, location: j.location, jd_text: j.jd_text })),
      score: false,
    }) });
    toast(`Added ${r.added} job(s), ranked by quick fit. Hit “Score all” for the full rubric.`);
    await refresh();
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.innerHTML = old; }
}

function renderCandidates(boxSel, results, totalFound) {
  const box = $(boxSel);
  if (!results.length) {
    const note = totalFound
      ? `${totalFound} roles found, but none matched your resumes at an early-career level. Tick “Include senior” or try another keyword.`
      : "No results. Try a different keyword.";
    box.innerHTML = `<p class="empty">${note}</p>`;
    return;
  }
  const found = totalFound && totalFound > results.length
    ? `${results.length} best-fit of ${totalFound} found` : `${results.length} roles, best fit first`;
  const header = `<div class="cand-head"><span>${found}</span>
    <button class="btn sm primary" id="bulk-${boxSel.slice(1)}">⚡ Add all</button></div>`;
  box.innerHTML = header + results.map((j, i) => {
    const fit = (j.fit != null)
      ? `<span class="fitbadge ${j.fit >= 60 ? "hi" : j.fit >= 35 ? "mid" : "lo"}">${j.fit}% fit</span>` : "";
    const track = j.track ? `<span class="trackbadge">${esc(j.track)}</span>` : "";
    const sen = j.seniority === "senior" ? `<span class="senbadge">senior</span>` : "";
    const applyUrl = j.apply_url || j.url;
    const apply = applyUrl ? `<a class="btn sm" href="${esc(applyUrl)}" target="_blank" rel="noopener">Apply ↗</a>` : "";
    return `
    <div class="dres">
      <div>
        <div class="t">${fit} ${esc(j.title)} ${sen}</div>
        <div class="meta">${esc(j.company || "—")} · ${esc(j.location || "")} · ${esc(j.source)}${j.remote ? " · remote" : ""} ${track}</div>
      </div>
      <div class="dres-actions">${apply}<button class="btn sm primary" data-i="${i}">Add</button></div>
    </div>`;
  }).join("");
  $$("[data-i]", box).forEach((b) => b.addEventListener("click", async () => {
    const j = results[+b.dataset.i];
    b.disabled = true; b.innerHTML = `<span class="spin"></span>`;
    try {
      const r = await api("/api/jobs", { method: "POST", body: JSON.stringify({
        url: j.url, title: j.title, company: j.company, location: j.location, jd_text: j.jd_text,
      }) });
      toast(r.created ? "Added." : "Already tracked.");
      await refresh();
      b.innerHTML = r.created ? "✓ Added" : "Tracked";
    } catch (e) { toast(e.message, true); b.disabled = false; b.innerHTML = "Add"; }
  }));
  const bulkBtn = $(`#bulk-${boxSel.slice(1)}`, box);
  if (bulkBtn) bulkBtn.addEventListener("click", () => bulkAddScore(results, bulkBtn));
}

function updateAdzBanner(configured) {
  const b = $("#adz-banner");
  if (b) b.style.display = configured ? "none" : "block";
}

async function saveAdzunaKey(btn) {
  const id = $("#adz-id").value.trim(), key = $("#adz-key").value.trim();
  if (!id || !key) return toast("Enter both App ID and App Key.", true);
  const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<span class="spin"></span> verifying`;
  try {
    const r = await api("/api/settings", { method: "POST", body: JSON.stringify({ adzuna_app_id: id, adzuna_app_key: key }) });
    if (r.verified) { toast("Adzuna connected — full search unlocked."); updateAdzBanner(true); }
    else if (r.adzuna) toast("Saved, but the key didn't return results. Double-check it.", true);
    else toast("Could not save key.", true);
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.innerHTML = old; }
}

async function searchJobs(btn) {
  const query = $("#x-query").value.trim();
  const location = $("#x-location").value.trim();
  const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<span class="spin"></span> searching 30+ companies…`;
  $("#x-results").innerHTML = `<p class="empty">Searching top companies and job boards…</p>`;
  try {
    const r = await api("/api/search", { method: "POST", body: JSON.stringify({
      query, location,
      include_senior: $("#x-senior").checked,
      include_intern: $("#x-intern").checked,
      include_phd: $("#x-phd").checked,
      limit: 60,
    }) });
    renderCandidates("#x-results", r.results || [], r.total_found);
    updateAdzBanner(r.adzuna);
    if ((r.results || []).length) toast(`${r.results.length} best-fit roles (of ${r.total_found} found).`);
    else if (!r.adzuna) toast("Add a free Adzuna key (banner above) for full job search.", true);
  } catch (e) { toast(e.message, true); $("#x-results").innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
  finally { btn.disabled = false; btn.innerHTML = old; }
}

// ---------- wire up ----------
function init() {
  $$(".tab").forEach((t) => t.addEventListener("click", () => {
    $$(".tab").forEach((x) => x.classList.remove("active"));
    $$(".tabpane").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $(`.tabpane[data-pane="${t.dataset.tab}"]`).classList.add("active");
  }));
  $("#p-add").addEventListener("click", addPaste);
  $("#u-add").addEventListener("click", (e) => addUrl(e.target));
  $("#x-search").addEventListener("click", (e) => searchJobs(e.target.closest("button")));
  $("#x-query").addEventListener("keydown", (e) => { if (e.key === "Enter") searchJobs($("#x-search")); });
  $("#adz-save").addEventListener("click", (e) => saveAdzunaKey(e.target.closest("button")));
  api("/api/settings").then((s) => updateAdzBanner(s.adzuna)).catch(() => {});
  $("#overlay").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

  api("/api/health").then((h) => {
    const el = $("#jdagent");
    el.textContent = h.jd_agent ? "engine: ready" : "engine: jd_agent missing";
    el.className = "badge " + (h.jd_agent ? "badge-ok" : "badge-muted");
  }).catch(() => {});

  refresh().catch((e) => toast("Could not load: " + e.message, true));
}

init();
