"use strict";

const POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF", "NA"];
let STATE = null;

// -- api ----------------------------------------------------------------
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  return res.json();
}

const chip = (pos) => {
  const p = POSITIONS.includes(pos) ? pos : "NA";
  return `<span class="chip ${p}">${pos || "?"}</span>`;
};

const pickLabel = (p) => `${p.round}.${String(((p.pick_no - 1) % STATE.league.num_teams) + 1).padStart(2, "0")}`;

function slotName(slot) {
  const labels = STATE.draft.slot_labels || {};
  return labels[slot] || labels[String(slot)] || `Team ${slot}`;
}

// -- render -----------------------------------------------------------
function render() {
  const s = STATE;
  document.getElementById("leagueName").textContent = s.league.name;

  const cur = s.draft.current_pick_no;
  const clockEl = document.getElementById("clock");
  if (cur) {
    const p = s.draft.picks[cur - 1];
    const mine = p.slot === s.draft.my_slot;
    clockEl.textContent = `Pick ${pickLabel(p)} · On the clock: ${mine ? "You" : slotName(p.slot)}`;
    clockEl.classList.toggle("mine", mine);
  } else {
    clockEl.textContent = "Draft complete";
    clockEl.classList.remove("mine");
  }

  const linked = s.draft.sleeper && s.draft.sleeper.draft_id;
  const syncBtn = document.getElementById("btnSync");
  syncBtn.hidden = !linked;
  if (linked) {
    syncBtn.textContent = s.draft.sleeper.is_mock ? "↻ Sync mock draft" : "↻ Sync draft";
  }

  renderBoard();
  renderClockCard();
  renderRecs();
  renderBestAvailable();
  renderRoster();
}

function renderBoard() {
  const s = STATE;
  const n = s.league.num_teams;
  const board = document.getElementById("board");
  board.style.gridTemplateColumns = `44px repeat(${n}, minmax(122px, 1fr))`;

  const rounds = s.league.roster_positions.length;
  const cells = [];
  cells.push(`<div class="cell rnd"></div>`);
  for (let slot = 1; slot <= n; slot++) {
    const mine = slot === s.draft.my_slot ? " mine" : "";
    cells.push(`<div class="cell head${mine}">${escapeHtml(slotName(slot))}</div>`);
  }

  const bySlotRound = {};
  for (const p of s.draft.picks) bySlotRound[`${p.round}-${p.slot}`] = p;

  for (let r = 1; r <= rounds; r++) {
    cells.push(`<div class="cell rnd">${r}</div>`);
    for (let slot = 1; slot <= n; slot++) {
      const p = bySlotRound[`${r}-${slot}`];
      if (!p) { cells.push(`<div class="cell"></div>`); continue; }
      const cls = [
        "cell",
        slot === s.draft.my_slot ? "mine" : "",
        p.pick_no === s.draft.current_pick_no ? "onclock" : "",
      ].join(" ");
      const inner = p.player
        ? `<span class="pk">${pickLabel(p)}</span>
           <span class="pl">${escapeHtml(p.player)}</span>
           <span class="meta">${chip(p.position)} ${escapeHtml(p.team || "")}</span>`
        : `<span class="pk">${pickLabel(p)}</span><span class="meta">&mdash;</span>`;
      cells.push(`<div class="${cls}" data-pick="${p.pick_no}">${inner}</div>`);
    }
  }
  board.innerHTML = cells.join("");
}

function renderClockCard() {
  const s = STATE;
  const cur = s.draft.current_pick_no;
  const card = document.getElementById("clockCard");
  const team = document.getElementById("clockTeam");
  const sub = document.getElementById("clockSub");
  if (!cur) {
    card.classList.remove("mine");
    team.textContent = "Draft complete";
    sub.textContent = "";
    return;
  }
  const p = s.draft.picks[cur - 1];
  const mine = p.slot === s.draft.my_slot;
  card.classList.toggle("mine", mine);
  team.textContent = mine ? "You" : slotName(p.slot);
  const until = s.draft.picks_until_my_turn;
  sub.textContent = mine
    ? `Pick ${pickLabel(p)} — make your pick`
    : `Pick ${pickLabel(p)} · your turn in ${until} pick${until === 1 ? "" : "s"}`;
}

function renderRecs() {
  const s = STATE;
  const list = document.getElementById("recList");
  const hint = document.getElementById("nextPicksHint");
  const upcoming = (s.draft.my_upcoming_picks || []).map((no) => pickLabel(s.draft.picks[no - 1]));
  hint.textContent = upcoming.length ? `your picks: ${upcoming.join(", ")}` : "";

  list.innerHTML = s.recommendations
    .map(
      (r) => `
      <li data-player="${escapeAttr(r.player)}" data-position="${r.position}" data-team="${escapeAttr(r.team || "")}">
        <div>
          <div class="rec-name">${escapeHtml(r.player)}</div>
          <div class="rec-sub">${chip(r.position)} ${escapeHtml(r.team || "")} · ${r.projected_points} proj${r.adp != null ? ` · ADP ${r.adp}` : ""}</div>
          <div class="rec-reasons">${r.reasons.map((x) => `<span class="tag">${escapeHtml(x)}</span>`).join("")}</div>
        </div>
        <div class="rec-val">VOR<b>+${r.vor}</b></div>
      </li>`
    )
    .join("");
}

function renderBestAvailable() {
  const list = document.getElementById("baList");
  list.innerHTML = STATE.best_available
    .map(
      (p) => `<li>${chip(p.position)}<span class="grow">${escapeHtml(p.player)}</span>
        <span class="v">${p.adp != null ? `ADP ${p.adp} · ` : ""}+${p.vor}</span></li>`
    )
    .join("");
}

function renderRoster() {
  const s = STATE;
  const mine = s.draft.picks.filter((p) => p.slot === s.draft.my_slot && p.player);
  const list = document.getElementById("rosterList");
  list.innerHTML = mine.length
    ? mine
        .map(
          (p) => `<li>${chip(p.position)}<span class="grow">${escapeHtml(p.player)}</span>
            <span class="v">${pickLabel(p)}</span></li>`
        )
        .join("")
    : `<li class="muted">No picks yet</li>`;
}

// -- pick popover ---------------------------------------------------
const pop = document.getElementById("pickPop");
let popPickNo = null;

function openPickPopover(pickNo, anchorEl) {
  popPickNo = pickNo;
  const p = STATE.draft.picks[pickNo - 1];
  document.getElementById("pickPopTitle").textContent = `Pick ${pickLabel(p)} (Slot ${p.slot})`;
  const rect = anchorEl.getBoundingClientRect();
  pop.style.top = `${window.scrollY + rect.bottom + 6}px`;
  pop.style.left = `${Math.min(window.scrollX + rect.left, window.scrollX + window.innerWidth - 320)}px`;
  pop.hidden = false;
  const search = document.getElementById("pickSearch");
  search.value = "";
  search.focus();
  runSearch("");
}

function closePickPopover() {
  pop.hidden = true;
  popPickNo = null;
}

async function runSearch(q) {
  const results = document.getElementById("searchResults");
  let rows = [];
  try {
    rows = await api(`/api/players?q=${encodeURIComponent(q)}&available=false&limit=15`);
  } catch (e) {
    results.innerHTML = `<li class="muted">${escapeHtml(e.message)}</li>`;
    return;
  }
  const current = STATE.draft.picks[popPickNo - 1];
  const clearRow = current.player
    ? `<li data-clear="1"><span class="grow">✕ Clear ${escapeHtml(current.player)}</span></li>`
    : "";
  results.innerHTML =
    clearRow +
    (rows.length
      ? rows
          .map(
            (r) => `<li class="${r.drafted ? "is-drafted" : ""}"
              data-player="${escapeAttr(r.player)}" data-position="${r.position}" data-team="${escapeAttr(r.team || "")}">
              ${chip(r.position)}<span class="grow">${escapeHtml(r.player)}</span>
              <span class="v">${r.adp != null ? `ADP ${r.adp} · ` : ""}+${r.vor}${r.drafted ? " · drafted" : ""}</span></li>`
          )
          .join("")
      : `<li class="muted">No matches</li>`);
}

async function assignPick(pickNo, { player, position, team }) {
  try {
    STATE = await api(`/api/picks/${pickNo}`, {
      method: "POST",
      body: JSON.stringify({ player, position, team }),
    });
    render();
  } catch (e) {
    alert(e.message);
  }
}

// -- modals -------------------------------------------------------
function openModal(id) { document.getElementById(id).hidden = false; }
function closeModals() {
  document.querySelectorAll(".modal").forEach((m) => (m.hidden = true));
}

function fillSettingsForm() {
  const s = STATE;
  document.getElementById("fName").value = s.league.name;
  document.getElementById("fTeams").value = s.league.num_teams;
  document.getElementById("fMySlot").value = s.draft.my_slot;
  document.getElementById("fRoster").value = s.league.roster_positions.join(", ");
  document.getElementById("fScoring").value = JSON.stringify(s.league.scoring_settings, null, 2);
}

async function saveSettings() {
  let scoring;
  try {
    scoring = JSON.parse(document.getElementById("fScoring").value || "{}");
  } catch (e) {
    alert("Scoring settings must be valid JSON");
    return;
  }
  const roster = document.getElementById("fRoster").value
    .split(/[\s,]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
  try {
    STATE = await api("/api/league", {
      method: "PUT",
      body: JSON.stringify({
        name: document.getElementById("fName").value || "My League",
        num_teams: parseInt(document.getElementById("fTeams").value, 10) || 12,
        my_slot: parseInt(document.getElementById("fMySlot").value, 10) || 1,
        roster_positions: roster,
        scoring_settings: scoring,
      }),
    });
    closeModals();
    render();
  } catch (e) {
    alert(e.message);
  }
}

async function doImport() {
  const errEl = document.getElementById("importError");
  errEl.hidden = true;
  const body = {
    league_id: document.getElementById("iLeague").value.trim() || null,
    draft_id: document.getElementById("iDraft").value.trim() || null,
    username: document.getElementById("iUser").value.trim() || null,
    my_slot: parseInt(document.getElementById("iMySlot").value, 10) || null,
  };
  try {
    STATE = await api("/api/import/sleeper", { method: "POST", body: JSON.stringify(body) });
    closeModals();
    render();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.hidden = false;
  }
}

let syncing = false;
async function syncSleeper(manual) {
  if (syncing) return;
  syncing = true;
  const btn = document.getElementById("btnSync");
  const label = btn.textContent;
  if (manual) btn.textContent = "Syncing…";
  try {
    STATE = await api("/api/sync/sleeper", { method: "POST" });
    render();
  } catch (e) {
    if (manual) alert(e.message);
  } finally {
    syncing = false;
    if (manual) document.getElementById("btnSync").textContent = label;
  }
}

// -- utils ------------------------------------------------------
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const escapeAttr = escapeHtml;

// -- events ---------------------------------------------------
document.getElementById("board").addEventListener("click", (e) => {
  const cell = e.target.closest(".cell[data-pick]");
  if (cell) openPickPopover(parseInt(cell.dataset.pick, 10), cell);
});

document.getElementById("searchResults").addEventListener("click", async (e) => {
  const li = e.target.closest("li");
  if (!li || popPickNo == null) return;
  const pickNo = popPickNo;
  closePickPopover();
  if (li.dataset.clear) {
    STATE = await api(`/api/picks/${pickNo}`, { method: "DELETE" });
    render();
    return;
  }
  if (li.dataset.player) {
    await assignPick(pickNo, { player: li.dataset.player, position: li.dataset.position, team: li.dataset.team });
  }
});

let searchTimer = null;
document.getElementById("pickSearch").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value;
  searchTimer = setTimeout(() => runSearch(q), 120);
});

document.getElementById("recList").addEventListener("click", (e) => {
  const li = e.target.closest("li");
  if (!li) return;
  const cur = STATE.draft.current_pick_no;
  if (!cur) return;
  assignPick(cur, { player: li.dataset.player, position: li.dataset.position, team: li.dataset.team });
});

document.addEventListener("click", (e) => {
  if (!pop.hidden && !pop.contains(e.target) && !e.target.closest(".cell[data-pick]")) closePickPopover();
  if (e.target.matches("[data-close-pop]")) closePickPopover();
  if (e.target.matches("[data-close-modal]")) closeModals();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closePickPopover(); closeModals(); }
});

document.getElementById("btnSettings").addEventListener("click", () => { fillSettingsForm(); openModal("settingsModal"); });
document.getElementById("btnImport").addEventListener("click", () => openModal("importModal"));
document.getElementById("saveSettings").addEventListener("click", saveSettings);
document.getElementById("doImport").addEventListener("click", doImport);
document.getElementById("btnSync").addEventListener("click", () => syncSleeper(true));
document.getElementById("btnReset").addEventListener("click", async () => {
  if (!confirm("Clear every pick on the board?")) return;
  STATE = await api("/api/reset", { method: "POST" });
  render();
});

// -- boot + polling ---------------------------------------------
async function loadState() {
  STATE = await api("/api/state");
  render();
}

function uiBusy() {
  return !pop.hidden || [...document.querySelectorAll(".modal")].some((m) => !m.hidden);
}

loadState();
setInterval(() => {
  if (uiBusy()) return;
  const sl = STATE && STATE.draft.sleeper;
  if (sl && sl.draft_id && sl.status !== "complete") {
    syncSleeper(false);  // linked to a (mock) draft — pull new picks
  } else {
    loadState().catch(() => {});
  }
}, 7000);
