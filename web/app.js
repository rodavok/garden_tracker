/* Garden Tracker front-end. Vanilla JS against the /api JSON endpoints. */
"use strict";

const API = "/api";
const $ = s => document.querySelector(s);
const state = { crops: [], varieties: [], settings: {}, seasons: [], view: "log", season: new Date().getFullYear(), month: null, analyzeCrop: "" };
const U = { metric: (localStorage.getItem("units") || "metric") === "metric" };

/* ---------- helpers ---------- */
function esc(s) { return (s ?? "").toString().replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
/* toast("Saved") or toast("Deleted", { label: "Undo", run: async () => … }) */
function toast(m, action) {
  const t = $("#toast"); clearTimeout(t._t);
  t.innerHTML = `<span>${esc(m)}</span>${action ? `<button type="button">${esc(action.label)}</button>` : ""}`;
  if (action) t.querySelector("button").onclick = guard(async () => { t.classList.remove("show"); await action.run(); });
  t.classList.add("show"); t._t = setTimeout(() => t.classList.remove("show"), action ? 8000 : 2400);
}
function todayISO() { const d = new Date(); return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, "0"), String(d.getDate()).padStart(2, "0")].join("-"); }
function pd(iso) { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); }
function fmtD(iso, withYear) { if (!iso) return "—"; return pd(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", ...(withYear ? { year: "numeric" } : {}) }); }
function fmtDW(iso) { return pd(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }); }
function fmtMonth(ym) { const [y, m] = ym.split("-").map(Number); return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" }); }
const MONTH_DOY = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335];
const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function doyLabel(doy) { let m = 0; while (m < 11 && MONTH_DOY[m + 1] <= doy) m++; return MONTH_ABBR[m] + " " + (doy - MONTH_DOY[m] + 1); }
function cropColor(c) { const slot = (typeof c === "number") ? c : (c ? c.color : 0); return `var(--s${slot || 0})`; }
function seasonColor(season) { const i = state.seasons.indexOf(Number(season)); return `var(--s${i >= 0 ? (i % 8) + 1 : 0})`; }
function cropById(id) { return state.crops.find(c => c.id === Number(id)); }
function plural(n, w) { return n + " " + w + (n === 1 ? "" : "s"); }

/* ---------- units ---------- */
const OZ = 28.349523125;
function unitW() { return U.metric ? "g" : "oz"; }
function toG(v) { v = parseFloat(v); if (isNaN(v)) return NaN; return U.metric ? v : v * OZ; }
function fromG(g) { return U.metric ? g : g / OZ; }
function fmtW(g) {
  if (g == null || isNaN(g)) return "—";
  if (U.metric) return g >= 1000 ? (g / 1000).toFixed(2).replace(/\.?0+$/, "") + " kg" : Math.round(g) + " g";
  const oz = g / OZ;
  if (oz < 16) return oz.toFixed(1) + " oz";
  const lb = Math.floor(oz / 16), rem = oz - lb * 16;
  return lb + " lb" + (rem >= 0.05 ? " " + rem.toFixed(1) + " oz" : "");
}
function fmtWAxis(g) {
  if (U.metric) return g >= 1000 ? (g / 1000).toFixed(g >= 10000 ? 0 : 1) + " kg" : Math.round(g) + " g";
  const oz = g / OZ; return oz >= 16 ? (oz / 16).toFixed(oz >= 160 ? 0 : 1) + " lb" : Math.round(oz) + " oz";
}
function fmtT(c) { if (c == null) return "—"; return Math.round(U.metric ? c : c * 9 / 5 + 32) + "°"; }
function tIn(c) { return c == null ? "" : (U.metric ? Math.round(c * 10) / 10 : Math.round((c * 9 / 5 + 32) * 10) / 10); }
function tOut(v) { v = parseFloat(v); if (isNaN(v)) return null; return U.metric ? v : (v - 32) * 5 / 9; }
function fmtP(mm) { if (mm == null) return "—"; return U.metric ? mm.toFixed(1) + " mm" : (mm / 25.4).toFixed(2) + " in"; }
function pIn(mm) { return mm == null ? "" : (U.metric ? Math.round(mm * 10) / 10 : Math.round(mm / 25.4 * 100) / 100); }
function pOut(v) { v = parseFloat(v); if (isNaN(v)) return null; return U.metric ? v : v * 25.4; }
function fmtSun(s) { return s == null ? "—" : (s / 3600).toFixed(1) + " h"; }
function setUnits(metric) {
  U.metric = metric; localStorage.setItem("units", metric ? "metric" : "imperial");
  $("#u-metric").setAttribute("aria-pressed", metric); $("#u-imperial").setAttribute("aria-pressed", !metric);
  render();
}

/* ---------- API ---------- */
async function api(path, opts = {}) {
  const r = await fetch(API + path, opts);
  if (!r.ok) { let d; try { d = (await r.json()).detail; } catch (e) { } throw new Error(typeof d === "string" ? d : (d ? JSON.stringify(d) : "Request failed (" + r.status + ")")); }
  return r.status === 204 ? null : r.json();
}
const J = { "Content-Type": "application/json" };
const jpost = (p, b) => api(p, { method: "POST", headers: J, body: JSON.stringify(b) });
const jpatch = (p, b) => api(p, { method: "PATCH", headers: J, body: JSON.stringify(b) });
const jput = (p, b) => api(p, { method: "PUT", headers: J, body: JSON.stringify(b) });
const jdel = p => api(p, { method: "DELETE" });
async function loadBase() {
  [state.crops, state.varieties, state.settings, state.seasons] = await Promise.all([api("/crops"), api("/varieties"), api("/settings"), api("/seasons")]);
  if (!state.seasons.includes(state.season) && state.seasons.length && !state.seasonPinned) state.season = state.seasons[state.seasons.length - 1];
  $("#locname").textContent = state.settings.location_name || "";
}
function guard(fn) { return async (...a) => { try { await fn(...a); } catch (e) { toast(e.message || String(e)); console.error(e); } }; }

/* ---------- navigation ---------- */
const VIEWS = [
  ["log", "Log", "M12 20V10M12 10c0-5 3-8 8-8 0 5-3 8-8 8zM12 14c0-4-3-6-7-6 0 4 3 6 7 6z"],
  ["harvests", "Harvests", "M4 6h16M4 12h16M4 18h10"],
  ["weather", "Weather", "M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4M12 8a4 4 0 100 8 4 4 0 000-8z"],
  ["plantings", "Plantings", "M4 20h16M6 20V10l6-6 6 6v10M10 20v-6h4v6"],
  ["analyze", "Analyze", "M4 19V5M4 19h16M8 15l4-5 3 3 5-7"],
  ["settings", "Settings", "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"],
];
function renderNav() {
  const icon = d => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
  const nav = VIEWS.filter(([k]) => k !== "settings");
  $("#tabs").innerHTML = nav.map(([k, l]) => `<button role="tab" data-v="${k}" aria-selected="${state.view === k}">${l}</button>`).join("");
  $("#bottomnav").innerHTML = nav.map(([k, l, d]) => `<button data-v="${k}" aria-selected="${state.view === k}">${icon(d)}${l}</button>`).join("");
  $("#gear").innerHTML = icon(VIEWS.find(([k]) => k === "settings")[2]); $("#gear").setAttribute("aria-pressed", state.view === "settings");
  document.querySelectorAll("[data-v]").forEach(b => b.onclick = () => { state.view = b.dataset.v; location.hash = b.dataset.v; render(); });
}
const RENDER = { log: renderLog, harvests: renderHarvests, weather: renderWeather, plantings: renderPlantings, analyze: renderAnalyze, settings: renderSettings };
async function render() {
  renderNav();
  const v = $("#view"); v.style.opacity = ".6";
  try { await RENDER[state.view](); } catch (e) { v.innerHTML = `<div class="card"><p class="muted">Couldn't load: ${esc(e.message)}</p></div>`; console.error(e); }
  v.style.opacity = "1";
}

/* ---------- modal ---------- */
function openModal({ title, body, submitLabel = "Save", onSubmit, extra = [], danger }) {
  const root = $("#modalRoot");
  root.innerHTML = `<div class="modal" id="modal"><form class="sheet" id="mform" autocomplete="off">
    <h3>${esc(title)}</h3>${body}
    <div class="acts">
      ${danger ? `<button type="button" class="btn danger" id="m-danger">${esc(danger.label)}</button>` : ""}
      ${extra.map((x, i) => `<button type="button" class="btn" data-x="${i}">${esc(x.label)}</button>`).join("")}
      <span class="grow"></span>
      <button type="button" class="btn" id="m-cancel">Cancel</button>
      ${onSubmit ? `<button type="submit" class="btn primary">${esc(submitLabel)}</button>` : ""}
    </div></form></div>`;
  const close = () => { root.innerHTML = ""; };
  $("#m-cancel").onclick = close;
  $("#modal").onclick = e => { if (e.target.id === "modal") close(); };
  if (danger) $("#m-danger").onclick = guard(async () => { if (danger.confirm === false || confirm(danger.confirm || "Are you sure?")) { await danger.run(); close(); } });
  extra.forEach((x, i) => root.querySelector(`[data-x="${i}"]`).onclick = guard(async () => { await x.run(); close(); }));
  $("#mform").onsubmit = guard(async e => { e.preventDefault(); const fd = Object.fromEntries(new FormData(e.target).entries()); await onSubmit(fd, e.target); close(); });
  const first = root.querySelector("input:not([type=hidden]),select,textarea"); if (first) first.focus();
  return close;
}
function cropSelect(name, selected, { allowNew = true } = {}) {
  const opts = state.crops.filter(c => !c.archived || c.id === Number(selected)).map(c => `<option value="${c.id}" ${c.id === Number(selected) ? "selected" : ""}>${esc(c.name)}</option>`).join("");
  return `<select name="${name}" id="sel-${name}">${opts}${allowNew ? `<option value="__new">+ New crop…</option>` : ""}</select><input type="text" name="${name}_new" id="sel-${name}-new" class="hidden" placeholder="New crop name" style="margin-top:6px">`;
}
function varietySelect(name, cropId, selected) {
  const vs = state.varieties.filter(v => v.crop_id === Number(cropId));
  return `<select name="${name}" id="sel-${name}"><option value="">— none —</option>${vs.map(v => `<option value="${v.id}" ${v.id === Number(selected) ? "selected" : ""}>${esc(v.name)}</option>`).join("")}<option value="__new">+ New variety…</option></select><input type="text" name="${name}_new" id="sel-${name}-new" class="hidden" placeholder="New variety name" style="margin-top:6px">`;
}
function wireNewToggle(name) { const s = $(`#sel-${name}`), n = $(`#sel-${name}-new`); if (!s) return; s.onchange = () => { n.classList.toggle("hidden", s.value !== "__new"); if (s.value === "__new") n.focus(); }; }
function wireCropVariety(cropName, varName, cur) {
  wireNewToggle(cropName); wireNewToggle(varName);
  const cs = $(`#sel-${cropName}`);
  cs.addEventListener("change", () => {
    if (cs.value === "__new") { $(`#sel-${varName}`).outerHTML = varietySelect(varName, -1, null); }
    else { $(`#sel-${varName}`).outerHTML = varietySelect(varName, cs.value, null); }
    $(`#sel-${varName}-new`).classList.add("hidden"); wireNewToggle(varName);
  });
}
/* Resolve crop/variety select values (including "+ new") into API fields. */
function resolveCV(fd, cropName, varName) {
  const out = {};
  if (fd[cropName] === "__new") out.crop_name = (fd[cropName + "_new"] || "").trim(); else out.crop_id = Number(fd[cropName]);
  if (fd[varName] === "__new") out.variety_name = (fd[varName + "_new"] || "").trim(); else out.variety_id = fd[varName] ? Number(fd[varName]) : null;
  if (out.crop_name === "") throw new Error("Enter the new crop's name");
  if (out.variety_name === "") delete out.variety_name;
  return out;
}

/* ===================== LOG ===================== */
/* Phone-first: tap a crop, punch the weight on the keypad, Save. The view
   fetches once (loadLog) and redraws locally (drawLog) on taps, so picking a
   crop or typing a digit never waits on the network. */
const COARSE = matchMedia("(pointer: coarse)").matches;
let logForm = { date: todayISO(), crop_id: null, variety_id: "", planting_id: "", w: "", notes: "", noteOpen: false };
let logData = null;

async function renderLog() { await loadLog(); drawLog(); }
async function loadLog() {
  const [recent, plantings, wx, pulse] = await Promise.all([api("/harvests?limit=12"), api("/plantings"), api("/weather/" + logForm.date), api("/stats/pulse")]);
  logData = { recent, plantings, wx, pulse };
}
function dateChipLabel(iso) {
  const t = todayISO(); if (iso === t) return "Today";
  const y = new Date(); y.setDate(y.getDate() - 1);
  if (iso === [y.getFullYear(), String(y.getMonth() + 1).padStart(2, "0"), String(y.getDate()).padStart(2, "0")].join("-")) return "Yesterday";
  return fmtDW(iso);
}
function logWeightG() { return toG(COARSE ? logForm.w : ($("#f-weight")?.value ?? "")); }
function weightHint() {
  const crop = cropById(logForm.crop_id); const el = $("#w-hint"); if (!el) return;
  const typ = crop ? logData.pulse.typical_g[String(crop.id)] : null;
  const g = logWeightG();
  if (typ && g > 0 && g >= 8 * typ && g > 300) { el.className = "hint warn"; el.textContent = `That's ${Math.round(g / typ)}× a typical ${crop.name.toLowerCase()} pick (${fmtW(typ)}). Right units?`; }
  else { el.className = "hint"; el.textContent = typ ? `Typical pick: ${fmtW(typ)}` : ""; }
}
function keypadHTML() {
  const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "⌫"];
  return `<div class="keypad">${keys.map(k => `<button type="button" data-k="${k}" ${k === "⌫" ? 'aria-label="Delete digit"' : ""}>${k}</button>`).join("")}</div>`;
}
function pressKey(k) {
  let w = logForm.w;
  if (k === "⌫") w = w.slice(0, -1);
  else if (k === "C") w = "";
  else if (k === ".") { if (!w.includes(".")) w = (w || "0") + "."; }
  else if (w.length < 7 && !/\.\d$/.test(w)) w = (w === "0" ? "" : w) + k;   // one decimal place is plenty
  logForm.w = w;
  const d = $("#f-wval"); if (d) { d.textContent = w || "0"; d.classList.toggle("muted", !w); }
  weightHint();
}

function drawLog() {
  const { recent, plantings, wx, pulse } = logData;
  const active = state.crops.filter(c => !c.archived).sort((a, b) => (b.last_harvest || "").localeCompare(a.last_harvest || "") || b.harvests - a.harvests || a.name.localeCompare(b.name));
  const crop = cropById(logForm.crop_id);
  const vs = crop ? state.varieties.filter(v => v.crop_id === crop.id) : [];
  const ps = crop ? plantings.filter(p => p.crop_id === crop.id && String(p.season) === logForm.date.slice(0, 4)) : [];
  const grouped = {}; recent.forEach(h => (grouped[h.date] = grouped[h.date] || []).push(h));
  const dueIds = new Set(pulse.crops.filter(c => c.due).map(c => c.crop_id));
  const showNote = logForm.noteOpen || logForm.notes || !COARSE;

  $("#view").innerHTML = `
  <div class="two">
  <div class="card logcard">
    <h2>Log a harvest
      <span class="row" style="gap:4px">
        <label class="datechip" title="Change date">${dateChipLabel(logForm.date)} ▾<input type="date" id="f-date" value="${logForm.date}" max="${todayISO()}" aria-label="Harvest date"></label>
        <button class="btn ghost" id="repeat" title="Copy crop, variety and planting from the last entry">↺ Repeat</button>
      </span>
    </h2>
    <div class="chips" id="cropchips">
      ${active.map(c => `<button type="button" class="chip" data-id="${c.id}" aria-pressed="${c.id === logForm.crop_id}"><span class="dot" style="--c:${cropColor(c)}"></span>${esc(c.name)}${dueIds.has(c.id) ? `<span class="due" title="Usually picked more often than this">•</span>` : ""}</button>`).join("")}
      <button type="button" class="chip add" id="newcrop">+ New</button>
    </div>
    <div id="newcropbox" class="hidden inl" style="margin-top:8px"><input type="text" id="f-newcrop" placeholder="Crop name" autocapitalize="words"><button class="btn" id="f-newcrop-ok" style="flex:0 0 auto">Add</button></div>
    ${crop ? `
    <div class="inl opts">
      <div><select id="f-variety" aria-label="Variety"><option value="">Any variety</option>${vs.map(v => `<option value="${v.id}" ${String(v.id) === String(logForm.variety_id) ? "selected" : ""}>${esc(v.name)}</option>`).join("")}<option value="__new">+ New variety…</option></select>
        <input type="text" id="f-variety-new" class="hidden" placeholder="Variety name" style="margin-top:6px" autocapitalize="words"></div>
      ${ps.length ? `<div><select id="f-planting" aria-label="Planting"><option value="">No planting</option>${ps.map(p => `<option value="${p.id}" ${String(p.id) === String(logForm.planting_id) ? "selected" : ""}>${esc(plantingLabel(p))}</option>`).join("")}</select></div>` : ""}
      ${showNote ? "" : `<button type="button" class="btn" id="f-addnote" style="flex:0 0 auto" title="Add a note">+ Note</button>`}
    </div>
    ${showNote ? `<input type="text" id="f-notes" placeholder="Note, e.g. first ripe one, some blossom-end rot" value="${esc(logForm.notes)}" style="margin-top:8px">` : ""}` : ""}
    ${COARSE ? `
    <div class="wdisp ${crop ? "" : "off"}"><span id="f-wval" class="${logForm.w ? "" : "muted"}">${esc(logForm.w || "0")}</span><span class="u">${unitW()}</span></div>
    <div id="w-hint" class="hint"></div>
    ${crop ? keypadHTML() : ""}` : `
    <label class="f">Weight</label>
    <div class="inl"><input type="number" id="f-weight" inputmode="decimal" step="${U.metric ? "1" : "0.1"}" min="0" placeholder="0" value="${esc(logForm.w)}" ${crop ? "" : "disabled"}><span class="unit">${unitW()}</span></div>
    <div id="w-hint" class="hint"></div>`}
    <button class="btn primary big" id="f-save" ${crop ? "" : "disabled"}>${crop ? "Save " + esc(crop.name) : "Pick a crop"}</button>
  </div>
  <div class="stack">
    ${pulseCard(pulse)}
    <div class="card">
      <h2>Weather · ${fmtDW(logForm.date)} <button class="btn ghost" id="wx-edit">${wx ? "Edit" : "Add"}</button></h2>
      ${wx ? `<div class="wx"><div class="t">${fmtT(wx.tmax_c)} <span>/ ${fmtT(wx.tmin_c)}</span></div><div>${fmtP(wx.precip_mm)} rain</div><div>${fmtSun(wx.sunshine_s)} sun</div>${wx.source === "manual" ? `<span class="badge">manual</span>` : ""}</div>${wx.notes ? `<p class="small" style="margin:8px 0 0">${esc(wx.notes)}</p>` : ""}`
      : `<p class="muted small" style="margin:0">No weather for this day yet${state.settings.weather_enabled ? ". It's fetched automatically, or add it now." : "."}</p>`}
    </div>
    <div class="card">
      <h2>Recent entries <a class="small" href="#harvests">All harvests →</a></h2>
      ${recent.length ? Object.keys(grouped).map(d => `<div class="daysep">${fmtDW(d)} · ${fmtW(grouped[d].reduce((a, h) => a + h.weight_g, 0))}</div>${grouped[d].map(h => entryHTML(h)).join("")}`).join("") : `<p class="empty">Nothing logged yet.</p>`}
    </div>
  </div></div>`;

  const dateIn = $("#f-date");
  dateIn.onclick = () => { try { dateIn.showPicker(); } catch (e) { } };
  dateIn.onchange = guard(async e => { logForm.date = e.target.value || todayISO(); logForm.planting_id = ""; await renderLog(); });
  document.querySelectorAll("#cropchips .chip[data-id]").forEach(b => b.onclick = () => selectLogCrop(Number(b.dataset.id)));
  $("#newcrop").onclick = () => { $("#newcropbox").classList.toggle("hidden"); $("#f-newcrop").focus(); };
  const addCrop = guard(async () => { const name = $("#f-newcrop").value.trim(); if (!name) return; const c = await jpost("/crops", { name }); await loadBase(); selectLogCrop(c.id); });
  $("#f-newcrop-ok").onclick = addCrop; $("#f-newcrop").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); addCrop(); } };
  const vsel = $("#f-variety"); if (vsel) vsel.onchange = () => { $("#f-variety-new").classList.toggle("hidden", vsel.value !== "__new"); if (vsel.value === "__new") $("#f-variety-new").focus(); logForm.variety_id = vsel.value; };
  const psel = $("#f-planting"); if (psel) psel.onchange = () => logForm.planting_id = psel.value;
  const win = $("#f-weight"); if (win) { win.oninput = () => { logForm.w = win.value; weightHint(); }; win.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); $("#f-save").click(); } }; }
  document.querySelectorAll(".keypad [data-k]").forEach(b => b.onclick = () => pressKey(b.dataset.k));
  const kb = document.querySelector('.keypad [data-k="⌫"]'); if (kb) { let t; kb.onpointerdown = () => { t = setTimeout(() => pressKey("C"), 500); }; kb.onpointerup = kb.onpointerleave = () => clearTimeout(t); }
  const notes = $("#f-notes"); if (notes) notes.oninput = () => logForm.notes = notes.value;
  const addNote = $("#f-addnote"); if (addNote) addNote.onclick = () => { logForm.noteOpen = true; drawLog(); $("#f-notes").focus(); };
  $("#f-save").onclick = guard(saveHarvest);
  $("#repeat").onclick = guard(async () => {
    const last = await api("/harvests/last"); if (!last) { toast("No previous entry"); return; }
    Object.assign(logForm, { crop_id: last.crop_id, variety_id: last.variety_id || "", planting_id: last.planting_id || "" });
    drawLog(); $("#f-weight")?.focus();
  });
  $("#wx-edit").onclick = () => weatherModal(logForm.date, wx, renderLog);
  document.querySelectorAll(".pulse-crop[data-id]").forEach(r => r.onclick = () => { selectLogCrop(Number(r.dataset.id)); window.scrollTo({ top: 0, behavior: "smooth" }); });
  wireEntries(renderLog);
  weightHint();
}
function selectLogCrop(id) {
  if (logForm.crop_id !== id) Object.assign(logForm, { crop_id: id, variety_id: "", planting_id: "" });
  drawLog(); $("#f-weight")?.focus();
}
async function saveHarvest() {
  const g = logWeightG();
  if (isNaN(g) || g <= 0) { toast("Enter a weight"); $("#f-weight")?.focus(); return; }
  const body = { date: logForm.date, crop_id: logForm.crop_id, weight_g: Math.round(g * 10) / 10, notes: ($("#f-notes")?.value || "").trim() };
  const vv = $("#f-variety")?.value;
  if (vv === "__new") { const n = $("#f-variety-new").value.trim(); if (n) body.variety_name = n; } else if (vv) body.variety_id = Number(vv);
  const pv = $("#f-planting")?.value; if (pv) body.planting_id = Number(pv);
  const h = await jpost("/harvests", body);
  Object.assign(logForm, { w: "", notes: "", noteOpen: false });
  if (body.variety_name) logForm.variety_id = h.variety_id;
  toast(`Saved ${fmtW(h.weight_g)} ${h.crop_name}`, { label: "Undo", run: async () => { await jdel("/harvests/" + h.id); toast("Removed"); await loadBase(); if (state.view === "log") renderLog(); } });
  await loadBase(); await renderLog(); $("#f-weight")?.focus();
}

/* Season-so-far card: totals vs last year to the same date, and per crop. */
function pulseCard(p) {
  const prev = p.prev_total_g > 0;
  const pct = prev && p.prev_to_date_g > 0 ? (p.season_g - p.prev_to_date_g) / p.prev_to_date_g * 100 : null;
  const crops = p.crops.filter(c => !c.archived && (c.season_g > 0 || c.prev_to_date_g > 0));
  if (!p.season_g && !prev) return "";
  const maxG = Math.max(1, ...crops.map(c => Math.max(c.season_g, c.prev_to_date_g)));
  const since = d => d == null ? "" : d === 0 ? "today" : d === 1 ? "yesterday" : d + "d ago";
  const shown = state.pulseAll ? crops : crops.slice(0, 6);
  return `<div class="card pulsecard">
    <h2>${p.season} so far ${prev ? `<span class="sub">vs ${p.prev_season} by this date</span>` : ""}</h2>
    <div class="pulse">
      <div class="lead"><div class="v">${fmtW(p.season_g)}</div>
        ${pct != null ? `<div class="d ${pct >= 0 ? "up" : "down"}">${pct >= 0 ? "▲" : "▼"} ${Math.abs(pct).toFixed(0)}% <span class="muted">(${fmtW(p.prev_to_date_g)})</span></div>` : (prev ? `<div class="d muted">${p.prev_season}: nothing yet by now</div>` : "")}
      </div>
      <div class="mini"><b>${fmtW(p.week_g)}</b><span>last 7 days</span></div>
      <div class="mini"><b>${fmtW(p.today_g)}</b><span>today${p.today_picks ? " · " + plural(p.today_picks, "pick") : ""}</span></div>
    </div>
    ${prev ? `<div class="progress" title="${fmtW(p.season_g)} of ${fmtW(p.prev_total_g)}"><i style="width:${Math.min(100, p.season_g / p.prev_total_g * 100).toFixed(1)}%"></i></div>
    <div class="small muted" style="margin-top:4px">${Math.round(p.season_g / p.prev_total_g * 100)}% of ${p.prev_season}'s full-season ${fmtW(p.prev_total_g)}</div>` : ""}
    ${crops.length ? `<div class="pulse-crops">${shown.map(c => `
      <button type="button" class="pulse-crop" data-id="${c.crop_id}" title="Log ${esc(c.name)}">
        <span class="nm"><span class="dot" style="--c:${cropColor(c.color)}"></span>${esc(c.name)}</span>
        <span class="bars">
          <i class="cur" style="--c:${cropColor(c.color)};width:${(c.season_g / maxG * 100).toFixed(1)}%"></i>
          ${prev ? `<i class="prev" style="width:${(c.prev_to_date_g / maxG * 100).toFixed(1)}%"></i>` : ""}
        </span>
        <span class="g">${fmtW(c.season_g)}</span>
        <span class="since ${c.due ? "due" : ""}">${c.due ? "check · " : ""}${since(c.days_since) || "—"}</span>
      </button>`).join("")}</div>
      ${crops.length > 6 ? `<button type="button" class="btn ghost small" id="pulse-more">${state.pulseAll ? "Show fewer" : `Show all ${crops.length}`}</button>` : ""}
      ${prev ? `<div class="legend small"><span><i style="--c:var(--leaf)"></i>${p.season}</span><span><i class="ghostbar"></i>${p.prev_season} by this date</span><span class="muted">Tap a crop to log it</span></div>` : ""}` : ""}
  </div>`;
}
document.addEventListener("click", e => { if (e.target.id === "pulse-more") { state.pulseAll = !state.pulseAll; drawLog(); } });
/* Hardware keyboard on the keypad layout (tablets with keyboards, testing on desktop). */
document.addEventListener("keydown", e => {
  if (!COARSE || state.view !== "log" || $("#modal") || !logForm.crop_id || /INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName || "")) return;
  if (/^[0-9.]$/.test(e.key)) { pressKey(e.key); e.preventDefault(); }
  else if (e.key === "Backspace") { pressKey("⌫"); e.preventDefault(); }
  else if (e.key === "Enter") { $("#f-save")?.click(); e.preventDefault(); }
});

/* Edit/delete buttons on entry rows. Delete is immediate, with Undo. */
function wireEntries(after) {
  document.querySelectorAll("[data-edit]").forEach(b => b.onclick = e => { e.stopPropagation(); harvestModal(Number(b.dataset.edit), after); });
  document.querySelectorAll("[data-del]").forEach(b => b.onclick = guard(async e => { e.stopPropagation(); await deleteHarvestWithUndo(Number(b.dataset.del), after); }));
}
async function deleteHarvestWithUndo(id, after) {
  const h = await api("/harvests/" + id);
  await jdel("/harvests/" + id);
  toast(`Deleted ${fmtW(h.weight_g)} ${h.crop_name}`, { label: "Undo", run: async () => {
    await jpost("/harvests", { date: h.date, crop_id: h.crop_id, variety_id: h.variety_id, planting_id: h.planting_id, weight_g: h.weight_g, notes: h.notes });
    toast("Restored"); await loadBase(); render();
  } });
  await loadBase(); after();
}
function plantingLabel(p) { return [p.variety_name, p.location, p.plant_count ? plural(p.plant_count, "plant") : "", p.transplant_date ? "set out " + fmtD(p.transplant_date) : (p.sow_date ? "sown " + fmtD(p.sow_date) : "")].filter(Boolean).join(" · ") || ("Planting #" + p.id); }
function entryHTML(h) {
  return `<div class="entry"><span class="dot" style="--c:${cropColor(cropById(h.crop_id))}"></span>
    <div class="n"><div>${esc(h.crop_name)}${h.variety_name ? ` <span class="muted">· ${esc(h.variety_name)}</span>` : ""}</div>${h.notes || h.planting_id ? `<small>${h.planting_id ? `<span class="badge">planting</span> ` : ""}${esc(h.notes)}</small>` : ""}</div>
    <span class="w">${fmtW(h.weight_g)}</span>
    <button class="btn ghost" data-edit="${h.id}" title="Edit">✎</button><button class="btn ghost" data-del="${h.id}" title="Delete">✕</button></div>`;
}
async function harvestModal(id, after) {
  const h = await api("/harvests/" + id);
  const ps = await api("/plantings?season=" + h.date.slice(0, 4));
  const body = `
    <label class="f">Date</label><input type="date" name="date" value="${h.date}" required>
    <label class="f">Crop</label>${cropSelect("crop", h.crop_id, { allowNew: false })}
    <label class="f">Variety</label>${varietySelect("variety", h.crop_id, h.variety_id)}
    <label class="f">Planting</label><select name="planting_id"><option value="">— none —</option>${ps.filter(p => p.crop_id === h.crop_id).map(p => `<option value="${p.id}" ${p.id === h.planting_id ? "selected" : ""}>${esc(plantingLabel(p))}</option>`).join("")}</select>
    <label class="f">Weight</label><div class="inl"><input type="number" name="weight" step="${U.metric ? "1" : "0.1"}" min="0" inputmode="decimal" value="${U.metric ? Math.round(h.weight_g * 10) / 10 : (h.weight_g / OZ).toFixed(1)}" required><span class="unit">${unitW()}</span></div>
    <label class="f">Notes</label><input type="text" name="notes" value="${esc(h.notes)}">`;
  openModal({
    title: "Edit harvest", body,
    danger: { label: "Delete", confirm: false, run: () => deleteHarvestWithUndo(id, after) },
    onSubmit: async fd => {
      const cv = resolveCV(fd, "crop", "variety");
      const patch = { date: fd.date, weight_g: Math.round(toG(fd.weight) * 10) / 10, notes: fd.notes.trim(), planting_id: fd.planting_id ? Number(fd.planting_id) : null, ...cv };
      if (patch.crop_id !== h.crop_id) patch.planting_id = null;
      await jpatch("/harvests/" + id, patch); toast("Saved"); await loadBase(); after();
    },
  });
  wireCropVariety("crop", "variety");
}

/* ===================== HARVESTS ===================== */
let hv = { season: "", crop: "", q: "" };
let hvRows = [];
async function renderHarvests() {
  if (hv.season === "" && state.seasons.length) hv.season = String(state.season);
  const q = new URLSearchParams(); if (hv.season) q.set("season", hv.season); if (hv.crop) q.set("crop_id", hv.crop);
  hvRows = await api("/harvests?" + q);
  $("#view").innerHTML = `<div class="card">
    <h2>Harvests <span class="sub" id="hv-sum"></span></h2>
    <div class="ctrl">
      <select id="hv-season"><option value="">All seasons</option>${state.seasons.map(s => `<option value="${s}" ${String(s) === hv.season ? "selected" : ""}>${s}</option>`).join("")}</select>
      <select id="hv-crop"><option value="">All crops</option>${state.crops.map(c => `<option value="${c.id}" ${String(c.id) === hv.crop ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select>
      <input type="search" id="hv-q" placeholder="Search notes, varieties…" value="${esc(hv.q)}" class="grow" style="width:auto;min-height:38px;padding:6px 10px">
    </div>
    <div id="hv-list" class="hvlist"></div>
    <div class="row small" style="margin-top:12px">
      <a class="btn ghost" href="${API}/export.csv" download>Export CSV</a>
      <label class="btn ghost">Import CSV<input type="file" id="hv-import" accept=".csv,text/csv" class="hidden"></label>
    </div></div>`;
  drawHarvestList();
  $("#hv-season").onchange = e => { hv.season = e.target.value; renderHarvests(); };
  $("#hv-crop").onchange = e => { hv.crop = e.target.value; renderHarvests(); };
  $("#hv-q").oninput = e => { hv.q = e.target.value; drawHarvestList(); };
  $("#hv-import").onchange = guard(async e => {
    const f = e.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    const res = await api("/import/csv", { method: "POST", body: fd });
    toast(`Imported ${res.added}, skipped ${res.skipped} already present${res.errors.length ? `, ${res.errors.length} errors` : ""}`);
    if (res.errors.length) console.warn(res.errors);
    await loadBase(); renderHarvests();
  });
}
function drawHarvestList() {
  const needle = hv.q.trim().toLowerCase();
  const rows = needle ? hvRows.filter(h => [h.crop_name, h.variety_name, h.notes].some(v => (v || "").toLowerCase().includes(needle))) : hvRows;
  $("#hv-sum").textContent = `${plural(rows.length, "pick")} · ${fmtW(rows.reduce((a, h) => a + h.weight_g, 0))}`;
  const byDay = {}; rows.forEach(h => (byDay[h.date] = byDay[h.date] || []).push(h));
  $("#hv-list").innerHTML = Object.keys(byDay).map(d => `<div class="daysep">${hv.season ? fmtDW(d) : fmtD(d, true)} · ${fmtW(byDay[d].reduce((a, h) => a + h.weight_g, 0))}</div>${byDay[d].map(entryHTML).join("")}`).join("")
    || `<p class="empty">No harvests match.</p>`;
  wireEntries(renderHarvests);
}

/* ===================== WEATHER ===================== */
async function renderWeather() {
  if (!state.month) state.month = todayISO().slice(0, 7);
  const [y, m] = state.month.split("-").map(Number);
  const last = new Date(y, m, 0).getDate();
  const start = `${state.month}-01`, end = `${state.month}-${String(last).padStart(2, "0")}`;
  const [days, harvests] = await Promise.all([api(`/weather?start=${start}&end=${end}`), api(`/harvests?start=${start}&end=${end}`)]);
  const byDate = Object.fromEntries(days.map(d => [d.date, d]));
  const hByDate = {}; harvests.forEach(h => hByDate[h.date] = (hByDate[h.date] || 0) + h.weight_g);
  const s = state.settings;
  const rows = [];
  for (let d = 1; d <= last; d++) {
    const iso = `${state.month}-${String(d).padStart(2, "0")}`; if (iso > todayISO()) break;
    const w = byDate[iso];
    const dash = "<span class='muted'>—</span>";
    rows.push(`<tr class="click" data-d="${iso}"><td><span class="num">${fmtDW(iso)}</span>${w?.source === "manual" ? ` <span class="badge">manual</span>` : ""}${w?.notes ? `<div class="small muted wxnote">${esc(w.notes)}</div>` : ""}</td>
      <td class="r">${w ? `${fmtT(w.tmax_c)}<span class="muted"> / ${fmtT(w.tmin_c)}</span>` : dash}</td>
      <td class="r">${w && w.precip_mm != null ? (w.precip_mm >= 0.05 ? fmtP(w.precip_mm) : "<span class='muted'>0</span>") : dash}</td>
      <td class="r hide-xs">${w ? fmtSun(w.sunshine_s) : dash}</td>
      <td class="r">${hByDate[iso] ? `<b>${fmtW(hByDate[iso])}</b>` : ""}</td></tr>`);
  }
  const tot = days.reduce((a, d) => a + (d.precip_mm || 0), 0);
  $("#view").innerHTML = `<div class="card">
    <div class="monthnav"><button class="btn ghost" id="wx-prev" aria-label="Previous month">‹</button><h2>${fmtMonth(state.month)}</h2><button class="btn ghost" id="wx-next" aria-label="Next month" ${state.month >= todayISO().slice(0, 7) ? "disabled" : ""}>›</button>
      <span class="sub">${days.length ? `${fmtP(tot)} · ${plural(days.filter(d => (d.precip_mm || 0) >= 1).length, "rain day")}` : ""}</span></div>
    <div class="row small muted" style="margin-bottom:8px">
      <span>${s.location_name ? `${esc(s.location_name)} · ` : ""}${s.weather_enabled ? (s.weather_last_fetch ? "last fetched " + new Date(s.weather_last_fetch).toLocaleString() : "not fetched yet") : "auto-fetch disabled"}${s.weather_last_error ? ` · <span style="color:var(--danger)">${esc(s.weather_last_error)}</span>` : ""}</span>
      <span class="grow"></span>
      ${s.weather_enabled ? `<button class="btn" id="wx-refresh">Refresh last 7 days</button>` : ""}
    </div>
    <table class="wxtable"><thead><tr><th>Day</th><th class="r">High / low</th><th class="r">Rain</th><th class="r hide-xs">Sun</th><th class="r">Picked</th></tr></thead><tbody>${rows.reverse().join("")}</tbody></table>
    <p class="muted small" style="margin:10px 0 0">Tap a day to correct it or add a note. Days you edit are marked <span class="badge">manual</span> and won't be overwritten by the daily fetch.</p>
  </div>`;
  $("#wx-prev").onclick = () => { state.month = shiftMonth(state.month, -1); renderWeather(); };
  $("#wx-next").onclick = () => { state.month = shiftMonth(state.month, 1); renderWeather(); };
  const rf = $("#wx-refresh"); if (rf) rf.onclick = guard(async () => { await jpost("/weather/refresh", { days: 7 }); toast("Fetching…"); });
  document.querySelectorAll("tr[data-d]").forEach(r => r.onclick = () => weatherModal(r.dataset.d, byDate[r.dataset.d], renderWeather));
}
function shiftMonth(ym, n) { const [y, m] = ym.split("-").map(Number); const d = new Date(y, m - 1 + n, 1); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0"); }
function weatherModal(iso, w, after) {
  const body = `<p class="muted small" style="margin:0 0 6px">${fmtDW(iso)}${w?.source === "manual" ? " · manual values" : (w ? " · from Open-Meteo" : "")}</p>
    <div class="inl"><div><label class="f">High (°${U.metric ? "C" : "F"})</label><input type="number" name="tmax" step="0.1" inputmode="decimal" value="${tIn(w?.tmax_c)}"></div>
    <div><label class="f">Low (°${U.metric ? "C" : "F"})</label><input type="number" name="tmin" step="0.1" inputmode="decimal" value="${tIn(w?.tmin_c)}"></div>
    <div><label class="f">Rain (${U.metric ? "mm" : "in"})</label><input type="number" name="precip" step="${U.metric ? "0.1" : "0.01"}" min="0" inputmode="decimal" value="${pIn(w?.precip_mm)}"></div></div>
    <label class="f">Notes</label><input type="text" name="notes" value="${esc(w?.notes || "")}" placeholder="frost, hail, watered, heat wave…">`;
  openModal({
    title: "Weather", body,
    extra: (w && w.source === "manual" && state.settings.weather_enabled) ? [{ label: "Reset to auto", run: async () => { await jdel("/weather/" + iso); toast("Reset"); after(); } }] : [],
    onSubmit: async fd => {
      const patch = { notes: fd.notes.trim() };
      const tmax = tOut(fd.tmax), tmin = tOut(fd.tmin), precip = pOut(fd.precip);
      const chg = (v, old) => v != null && (old == null || Math.abs(v - old) > 0.051);
      if (chg(tmax, w?.tmax_c)) patch.tmax_c = Math.round(tmax * 10) / 10;
      if (chg(tmin, w?.tmin_c)) patch.tmin_c = Math.round(tmin * 10) / 10;
      if (chg(precip, w?.precip_mm)) patch.precip_mm = Math.round(precip * 100) / 100;
      await jput("/weather/" + iso, patch); toast("Saved"); after();
    },
  });
}

/* ===================== PLANTINGS ===================== */
let plSeason = "";
async function renderPlantings() {
  if (plSeason === "") plSeason = String(state.season);
  const all = await api("/plantings");
  const seasons = [...new Set([...state.seasons, ...all.map(p => p.season), new Date().getFullYear()])].sort();
  const rows = all.filter(p => !plSeason || String(p.season) === plSeason);
  $("#view").innerHTML = `<div class="card">
    <h2>Plantings <button class="btn primary" id="pl-add">+ Add planting</button></h2>
    <div class="ctrl"><select id="pl-season"><option value="">All seasons</option>${seasons.map(s => `<option value="${s}" ${String(s) === plSeason ? "selected" : ""}>${s}</option>`).join("")}</select></div>
    <div class="scrollx" style="margin-top:10px"><table><thead><tr><th>Crop</th><th>Sown</th><th>Set out</th><th class="r">Plants</th><th>Where</th><th class="r">Yield</th><th class="r">Per plant</th><th class="r">First pick</th><th>Notes</th></tr></thead><tbody>
      ${rows.map(p => `<tr class="click" data-id="${p.id}">
        <td><span class="cropname"><span class="dot" style="--c:${cropColor(cropById(p.crop_id))}"></span>${esc(p.crop_name)}${p.variety_name ? ` <span class="muted">· ${esc(p.variety_name)}</span>` : ""}</span></td>
        <td class="num">${fmtD(p.sow_date)}</td><td class="num">${fmtD(p.transplant_date)}</td><td class="r">${p.plant_count ?? "—"}</td><td>${esc(p.location)}</td>
        <td class="r"><b>${p.harvests ? fmtW(p.total_g) : "—"}</b>${p.harvests ? `<span class="muted small"> · ${p.harvests}</span>` : ""}</td>
        <td class="r">${p.g_per_plant != null && p.harvests ? fmtW(p.g_per_plant) : "—"}</td>
        <td class="r">${p.first_harvest ? `${fmtD(p.first_harvest)}${p.days_to_first != null ? `<span class="muted small"> · ${p.days_to_first}d</span>` : ""}` : "—"}</td>
        <td class="muted small wrap">${esc(p.notes)}</td></tr>`).join("") || `<tr><td colspan="9" class="empty">No plantings${plSeason ? " in " + plSeason : ""}. Add one to track days-to-harvest and yield per plant.</td></tr>`}
    </tbody></table></div>
    <p class="muted small" style="margin:10px 0 0">Link harvests to a planting from the Log form (the Planting field appears once a crop has plantings that season). "First pick" counts days from set-out (or sowing).</p>
  </div>`;
  $("#pl-season").onchange = e => { plSeason = e.target.value; renderPlantings(); };
  $("#pl-add").onclick = () => plantingModal(null, renderPlantings);
  document.querySelectorAll("tr[data-id]").forEach(r => r.onclick = () => plantingModal(all.find(p => p.id === Number(r.dataset.id)), renderPlantings));
}
function plantingModal(p, after) {
  const cropId = p ? p.crop_id : (state.crops.find(c => !c.archived)?.id ?? -1);
  const body = `
    <label class="f">Crop</label>${cropSelect("crop", cropId)}
    <label class="f">Variety</label>${varietySelect("variety", cropId, p?.variety_id)}
    <div class="inl"><div><label class="f">Sown</label><input type="date" name="sow_date" value="${p?.sow_date || ""}"></div>
    <div><label class="f">Set out / transplanted</label><input type="date" name="transplant_date" value="${p?.transplant_date || ""}"></div></div>
    <div class="inl"><div><label class="f">Plant count</label><input type="number" name="plant_count" min="1" step="1" inputmode="numeric" value="${p?.plant_count ?? ""}"></div>
    <div><label class="f">Season</label><input type="number" name="season" min="2000" max="2100" step="1" inputmode="numeric" value="${p?.season ?? new Date().getFullYear()}"></div></div>
    <label class="f">Location</label><input type="text" name="location" value="${esc(p?.location || "")}" placeholder="Bed 2, big pot, along the fence…">
    <label class="f">Notes</label><textarea name="notes">${esc(p?.notes || "")}</textarea>`;
  openModal({
    title: p ? "Edit planting" : "Add planting", body,
    danger: p ? { label: "Delete", confirm: "Delete this planting? Its harvests are kept but unlinked.", run: async () => { await jdel("/plantings/" + p.id); toast("Deleted"); after(); } } : null,
    onSubmit: async fd => {
      const cv = resolveCV(fd, "crop", "variety");
      const b = { ...cv, sow_date: fd.sow_date || null, transplant_date: fd.transplant_date || null, plant_count: fd.plant_count ? Number(fd.plant_count) : null, season: Number(fd.season), location: fd.location.trim(), notes: fd.notes.trim() };
      if (p) await jpatch("/plantings/" + p.id, b); else await jpost("/plantings", b);
      toast("Saved"); await loadBase(); after();
    },
  });
  wireCropVariety("crop", "variety");
}

/* ===================== ANALYZE ===================== */
async function renderAnalyze() {
  if (!state.seasons.length) { $("#view").innerHTML = `<div class="card"><p class="empty">Log a few harvests and the analysis will appear here.</p></div>`; return; }
  const season = state.season;
  const [ov, ss, cum, gdd] = await Promise.all([api("/stats/overview"), api("/stats/season/" + season), api("/stats/cumulative" + (state.analyzeCrop ? "?crop_id=" + state.analyzeCrop : "")), api("/stats/gdd")]);
  const sm = ss.summary, wx = ss.weather;
  // While a season is in progress, compare with last season up to the same date.
  const pv = sm.prev;
  const delta = (cur, prev) => { if (!pv || !prev) return ""; const p = (cur - prev) / prev * 100; return `<div class="d ${p >= 0 ? "up" : "down"}">${p >= 0 ? "+" : ""}${p.toFixed(0)}% vs ${pv.season}${pv.partial ? " by this date" : ""}</div>`; };
  const tile = (l, v, d = "") => `<div class="tile"><div class="l">${l}</div><div class="v">${v}</div>${d ? (d.startsWith("<div") ? d : `<div class="d">${d}</div>`) : ""}</div>`;

  $("#view").innerHTML = `
  <div class="ctrl" style="margin-top:14px">
    <select id="an-season">${state.seasons.map(s => `<option value="${s}" ${s === season ? "selected" : ""}>${s} season</option>`).join("")}</select>
    <span class="muted small">Cumulative chart:</span>
    <select id="an-crop"><option value="">All crops</option>${state.crops.map(c => `<option value="${c.id}" ${String(c.id) === String(state.analyzeCrop) ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select>
  </div>
  <div class="tiles">
    ${tile("Total harvested", fmtW(sm.total_g), delta(sm.total_g, pv && pv.to_date_g))}
    ${tile("Harvests", sm.harvests, `${sm.crops} crops · ${sm.days_with_harvest} days`)}
    ${tile("Season span", sm.first_date ? `${fmtD(sm.first_date)} – ${fmtD(sm.last_date)}` : "—", sm.first_date ? plural(Math.round((pd(sm.last_date) - pd(sm.first_date)) / 864e5) + 1, "day") : "")}
    ${tile("Top crop", sm.top_crop ? esc(sm.top_crop.name) : "—", sm.top_crop ? fmtW(sm.top_crop.total_g) : "")}
  </div>
  <div class="card">
    <h2>Cumulative yield by season <span class="sub">${state.analyzeCrop ? esc(cropById(state.analyzeCrop)?.name) : "all crops"}</span></h2>
    <div class="chart" id="ch-cum"></div>
  </div>
  <div class="card">
    <h2>Weekly harvest by crop <span class="sub">${season}</span></h2>
    <div class="chart" id="ch-week"></div>
  </div>
  <div class="card">
    <h2>Year over year <span class="sub">by crop</span></h2>
    <div class="scrollx"><table class="yoy"><thead><tr><th>Crop</th>${ov.seasons.map(s => `<th class="r">${s}</th>`).join("")}<th class="r">All</th></tr></thead><tbody>
      ${ov.crops.map(c => `<tr><td><span class="cropname"><span class="dot" style="--c:${cropColor(c.color)}"></span>${esc(c.name)}</span></td>
        ${ov.seasons.map((s, i) => { const v = c.by_season[String(s)]; const pv = i > 0 ? c.by_season[String(ov.seasons[i - 1])] : null; if (!v) return `<td class="r muted">—</td>`; let dl = ""; if (pv && pv.total_g) { const p = (v.total_g - pv.total_g) / pv.total_g * 100; dl = `<span class="delta ${p >= 0 ? "up" : "down"}">${p >= 0 ? "+" : ""}${p.toFixed(0)}%</span>`; } return `<td class="r"><b>${fmtW(v.total_g)}</b><span class="delta">${v.harvests}× · ${fmtD(v.first)}–${fmtD(v.last)}</span>${dl}</td>`; }).join("")}
        <td class="r"><b>${fmtW(c.total_g)}</b></td></tr>`).join("")}
      <tr><td><b>Total</b></td>${ov.seasons.map(s => `<td class="r"><b>${fmtW(ov.season_totals[String(s)]?.total_g || 0)}</b></td>`).join("")}<td class="r"><b>${fmtW(Object.values(ov.season_totals).reduce((a, t) => a + t.total_g, 0))}</b></td></tr>
    </tbody></table></div>
  </div>
  <div class="card">
    <h2>Crops this season <span class="sub">${season}</span></h2>
    <div class="scrollx"><table><thead><tr><th>Crop</th><th class="r">Total</th><th class="r">Share</th><th class="r">Picks</th><th class="r">Biggest</th><th>First</th><th>Last</th></tr></thead><tbody>
      ${ss.by_crop.map(c => `<tr><td><span class="cropname"><span class="dot" style="--c:${cropColor(c.color)}"></span>${esc(c.name)}</span></td><td class="r"><b>${fmtW(c.total_g)}</b></td><td class="r">${(c.share * 100).toFixed(0)}%</td><td class="r">${c.harvests}</td><td class="r">${fmtW(c.biggest_g)}</td><td class="num">${fmtD(c.first)}</td><td class="num">${fmtD(c.last)}</td></tr>`).join("") || `<tr><td colspan="7" class="empty">No harvests in ${season}.</td></tr>`}
    </tbody></table></div>
  </div>
  <h2 style="margin:22px 0 0;font-size:17px">Weather · ${season}</h2>
  <div class="tiles" style="margin-top:8px">
    ${tile("Growing degree days", wx.days ? wx.gdd.toLocaleString() : "—", wx.days ? `base 10 °C · ${fmtD(wx.first_date)}–${fmtD(wx.last_date)}` : "no weather data")}
    ${tile("Rain", wx.days ? fmtP(wx.precip_mm) : "—", wx.days ? `${wx.rain_days} rain days` : "")}
    ${tile("Avg high / low", wx.days ? `${fmtT(wx.tmax_avg)} / ${fmtT(wx.tmin_avg)}` : "—", wx.hottest ? `hottest ${fmtT(wx.hottest.tmax_c)} on ${fmtD(wx.hottest.date)}` : "")}
    ${tile("Frost", wx.days ? (wx.frost_days + (wx.frost_days === 1 ? " night" : " nights")) : "—", wx.days ? [wx.last_spring_frost ? "last spring " + fmtD(wx.last_spring_frost) : "", wx.first_fall_frost ? "first fall " + fmtD(wx.first_fall_frost) : ""].filter(Boolean).join(" · ") || "none recorded" : "")}
  </div>
  <div class="card">
    <h2>Growing degree days by season <span class="sub">cumulative, base 10 °C</span></h2>
    <div class="chart" id="ch-gdd"></div>
  </div>
  <div class="card">
    <h2>Monthly weather <span class="sub">${season}</span></h2>
    <div class="scrollx"><table><thead><tr><th>Month</th><th class="r">Avg high</th><th class="r">Avg low</th><th class="r">Rain</th><th class="r">Rain days</th><th class="r">GDD</th><th class="r">Sun</th><th class="r">Harvest</th></tr></thead><tbody>
      ${wx.monthly.map(m => { const hg = ss.weekly.filter(w => w.week_start.slice(0, 7) === m.month).reduce((a, w) => a + Object.values(w.parts).reduce((x, y) => x + y, 0), 0); return `<tr><td>${fmtMonth(m.month).replace(/ \d+$/, "")}${m.days < 28 ? `<span class="muted small"> · ${m.days}d</span>` : ""}</td><td class="r">${fmtT(m.tmax_avg)}</td><td class="r">${fmtT(m.tmin_avg)}</td><td class="r">${fmtP(m.precip_mm)}</td><td class="r">${m.rain_days}</td><td class="r">${m.gdd}</td><td class="r">${m.sun_h} h</td><td class="r">${hg ? fmtW(hg) : ""}</td></tr>`; }).join("") || `<tr><td colspan="8" class="empty">No weather data for ${season} yet.</td></tr>`}
    </tbody></table></div>
    <p class="muted small" style="margin:10px 0 0">Monthly harvest here is grouped by the week's Monday, so a week straddling two months counts toward the month it starts in.</p>
  </div>`;

  $("#an-season").onchange = e => { state.season = Number(e.target.value); state.seasonPinned = true; renderAnalyze(); };
  $("#an-crop").onchange = e => { state.analyzeCrop = e.target.value; renderAnalyze(); };

  // Cumulative yield: one line per season, x = day of year.
  lineChart($("#ch-cum"), {
    series: cum.seasons.map(s => ({ name: String(s.season), color: seasonColor(s.season), points: s.points.map(p => ({ x: p.doy, y: p.cum_g, date: p.date })) })),
    yFmt: fmtWAxis, yTip: fmtW, xFmt: doyLabel, emptyText: "No harvests yet.",
  });
  // Weekly stacked columns by crop for the selected season.
  const cropOrder = ss.by_crop.map(c => c.crop_id);
  columnChart($("#ch-week"), {
    buckets: ss.weekly.map(w => ({ label: fmtD(w.week_start), tipLabel: "Week of " + fmtD(w.week_start, true), parts: cropOrder.filter(id => w.parts[String(id)]).map(id => ({ key: id, name: cropById(id)?.name || "?", color: cropColor(cropById(id)), val: w.parts[String(id)] })) })),
    keys: cropOrder.map(id => ({ key: id, name: cropById(id)?.name || "?", color: cropColor(cropById(id)) })),
    yFmt: fmtWAxis, yTip: fmtW, emptyText: `No harvests in ${season}.`,
  });
  // GDD curves.
  lineChart($("#ch-gdd"), {
    series: gdd.seasons.map(s => ({ name: String(s.season), color: seasonColor(s.season), points: s.points.map(p => ({ x: p.doy, y: p.cum_gdd, date: p.date })) })),
    yFmt: v => Math.round(v).toLocaleString(), yTip: v => Math.round(v).toLocaleString() + " GDD", xFmt: doyLabel, emptyText: "No weather data yet — set a location in Settings.",
  });
}

/* ---------- charts (inline SVG, no libraries) ---------- */
function niceTicks(max, n = 4) {
  if (!(max > 0)) return [0, 1];
  const raw = max / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw);
  const ticks = []; for (let v = 0; v <= max + step * 0.999; v += step) ticks.push(+v.toFixed(6));
  return ticks;
}
function chartTipEl(el) { let t = el.querySelector(".tip"); if (!t) { t = document.createElement("div"); t.className = "tip"; el.appendChild(t); } return t; }
function placeTip(el, tip, px, py) {
  const W = el.clientWidth; tip.style.display = "block";
  const tw = tip.offsetWidth; let x = px + 14; if (x + tw > W - 4) x = px - tw - 14; if (x < 0) x = 4;
  tip.style.left = x + "px"; tip.style.top = Math.max(0, py - 10) + "px";
}
function lineChart(el, { series, yFmt, yTip, xFmt, emptyText }) {
  series = series.filter(s => s.points.length);
  if (!series.length) { el.innerHTML = `<p class="empty">${esc(emptyText || "No data")}</p>`; return; }
  const W = Math.max(320, el.clientWidth || 640), H = 260, ml = 48, mr = series.length <= 4 ? 52 : 16, mt = 12, mb = 28;
  const xs = series.flatMap(s => s.points.map(p => p.x)), ys = series.flatMap(s => s.points.map(p => p.y));
  let x0 = Math.min(...xs), x1 = Math.max(...xs); if (x1 - x0 < 30) { x0 = Math.max(1, x0 - 15); x1 = x1 + 15; } x0 = Math.max(1, x0 - 3); x1 = Math.min(366, x1 + 3);
  const yt = niceTicks(Math.max(...ys)), y1 = yt[yt.length - 1];
  const X = v => ml + (v - x0) / (x1 - x0) * (W - ml - mr), Y = v => mt + (1 - v / y1) * (H - mt - mb);
  const xticks = MONTH_DOY.map((d, i) => ({ v: d, l: MONTH_ABBR[i] })).filter(t => t.v >= x0 && t.v <= x1);
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="line chart">`;
  svg += `<g class="grid">${yt.map(v => `<line x1="${ml}" x2="${W - mr}" y1="${Y(v)}" y2="${Y(v)}"/>`).join("")}</g>`;
  svg += `<g class="axis"><line x1="${ml}" x2="${W - mr}" y1="${Y(0)}" y2="${Y(0)}"/>${yt.map(v => `<text x="${ml - 6}" y="${Y(v) + 4}" text-anchor="end">${esc(yFmt(v))}</text>`).join("")}${xticks.map(t => `<text x="${X(t.v)}" y="${H - 8}" text-anchor="middle">${t.l}</text>`).join("")}</g>`;
  const labels = [];
  series.forEach((s, i) => {
    const pts = s.points.slice().sort((a, b) => a.x - b.x);
    const d = pts.map((p, j) => (j ? "L" : "M") + X(p.x).toFixed(1) + " " + Y(p.y).toFixed(1)).join(" ");
    svg += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    const last = pts[pts.length - 1];
    svg += `<circle cx="${X(last.x)}" cy="${Y(last.y)}" r="4" fill="${s.color}" stroke="var(--card)" stroke-width="2"/>`;
    if (series.length <= 4) labels.push({ x: X(last.x) + 8, y: Y(last.y) + 4, t: s.name });
  });
  // End labels: skip any that would collide with an already-placed one.
  labels.sort((a, b) => a.y - b.y).reduce((prev, l) => { if (prev == null || l.y - prev >= 14) { svg += `<text class="endlbl" x="${l.x}" y="${l.y}">${esc(l.t)}</text>`; return l.y; } return prev; }, null);
  svg += `<line id="xh" x1="0" x2="0" y1="${mt}" y2="${Y(0)}" stroke="var(--axis)" stroke-width="1" style="display:none"/>`;
  svg += `<g id="hdots">${series.map(s => `<circle r="5" fill="${s.color}" stroke="var(--card)" stroke-width="2" style="display:none"/>`).join("")}</g>`;
  svg += `<rect x="${ml}" y="${mt}" width="${W - ml - mr}" height="${H - mt - mb}" fill="transparent" id="hit"/></svg>`;
  el.innerHTML = svg + (series.length > 1 ? `<div class="legend">${series.map(s => `<span><i class="line" style="--c:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div>` : "");
  const tip = chartTipEl(el), svgEl = el.querySelector("svg"), xh = el.querySelector("#xh"), dots = [...el.querySelectorAll("#hdots circle")];
  const allX = [...new Set(xs)].sort((a, b) => a - b);
  const move = e => {
    const r = svgEl.getBoundingClientRect(); const cx = (e.touches ? e.touches[0].clientX : e.clientX) - r.left; const sx = cx * W / r.width;
    const xv = x0 + (sx - ml) / (W - ml - mr) * (x1 - x0);
    let best = allX[0]; for (const v of allX) if (Math.abs(v - xv) < Math.abs(best - xv)) best = v;
    xh.setAttribute("x1", X(best)); xh.setAttribute("x2", X(best)); xh.style.display = "";
    let rows = "", anyDate = "";
    series.forEach((s, i) => {
      // value at-or-before this x (cumulative series hold their value between points)
      const pts = s.points; let p = null; if (best <= pts[pts.length - 1].x) for (const q of pts) if (q.x <= best) p = q; else break;
      if (p) { dots[i].setAttribute("cx", X(best)); dots[i].setAttribute("cy", Y(p.y)); dots[i].style.display = ""; rows += `<div class="r"><i style="--c:${s.color}"></i><b>${esc((yTip || yFmt)(p.y))}</b><span>${esc(s.name)}</span></div>`; }
      else dots[i].style.display = "none";
    });
    tip.innerHTML = `<div class="h">${esc(xFmt(best))}</div>${rows}`;
    placeTip(el, tip, X(best) * r.width / W, (e.touches ? e.touches[0].clientY : e.clientY) - r.top);
  };
  const leave = () => { tip.style.display = "none"; xh.style.display = "none"; dots.forEach(d => d.style.display = "none"); };
  const hit = el.querySelector("#hit"); hit.addEventListener("mousemove", move); hit.addEventListener("touchstart", move, { passive: true }); hit.addEventListener("touchmove", move, { passive: true }); hit.addEventListener("mouseleave", leave); hit.addEventListener("touchend", leave);
}
function columnChart(el, { buckets, keys, yFmt, yTip, emptyText }) {
  if (!buckets.length || !buckets.some(b => b.parts.length)) { el.innerHTML = `<p class="empty">${esc(emptyText || "No data")}</p>`; return; }
  const W = Math.max(320, el.clientWidth || 640), H = 240, ml = 48, mr = 12, mt = 12, mb = 28;
  const totals = buckets.map(b => b.parts.reduce((a, p) => a + p.val, 0));
  const yt = niceTicks(Math.max(...totals)), y1 = yt[yt.length - 1];
  const Y = v => mt + (1 - v / y1) * (H - mt - mb);
  const n = buckets.length, slot = (W - ml - mr) / n, bw = Math.min(24, slot * 0.7), gap = 2;
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="column chart">`;
  svg += `<g class="grid">${yt.map(v => `<line x1="${ml}" x2="${W - mr}" y1="${Y(v)}" y2="${Y(v)}"/>`).join("")}</g>`;
  const every = Math.ceil(n / Math.floor((W - ml - mr) / 56));
  svg += `<g class="axis"><line x1="${ml}" x2="${W - mr}" y1="${Y(0)}" y2="${Y(0)}"/>${yt.map(v => `<text x="${ml - 6}" y="${Y(v) + 4}" text-anchor="end">${esc(yFmt(v))}</text>`).join("")}${buckets.map((b, i) => i % every === 0 ? `<text x="${ml + slot * (i + .5)}" y="${H - 8}" text-anchor="middle">${esc(b.label)}</text>` : "").join("")}</g>`;
  buckets.forEach((b, i) => {
    const x = ml + slot * (i + .5) - bw / 2; let acc = 0;
    b.parts.forEach((p, j) => {
      const top = Y(acc + p.val), bot = Y(acc) - (j ? gap : 0); acc += p.val;
      const h = Math.max(0, bot - top); const isTop = j === b.parts.length - 1;
      if (h <= 0) return;
      const r = isTop ? Math.min(4, h) : 0;
      svg += `<path d="M${x} ${bot} V${top + r} a${r} ${r} 0 0 1 ${r} -${r} H${x + bw - r} a${r} ${r} 0 0 1 ${r} ${r} V${bot} Z" fill="${p.color}"/>`;
    });
    svg += `<rect data-i="${i}" x="${ml + slot * i}" y="${mt}" width="${slot}" height="${H - mt - mb}" fill="transparent"/>`;
  });
  svg += `</svg>`;
  el.innerHTML = svg + (keys.length > 1 ? `<div class="legend">${keys.map(k => `<span><i style="--c:${k.color}"></i>${esc(k.name)}</span>`).join("")}</div>` : "");
  const tip = chartTipEl(el), svgEl = el.querySelector("svg");
  const show = (e, i) => {
    const b = buckets[i]; const r = svgEl.getBoundingClientRect();
    tip.innerHTML = `<div class="h">${esc(b.tipLabel || b.label)} · <b>${esc((yTip || yFmt)(totals[i]))}</b></div>${b.parts.slice().reverse().map(p => `<div class="r"><i style="--c:${p.color}"></i><b>${esc((yTip || yFmt)(p.val))}</b><span>${esc(p.name)}</span></div>`).join("")}`;
    placeTip(el, tip, (ml + slot * (i + .5)) * r.width / W, (e.touches ? e.touches[0].clientY : e.clientY) - r.top);
  };
  el.querySelectorAll("rect[data-i]").forEach(rc => { const i = Number(rc.dataset.i); rc.addEventListener("mousemove", e => show(e, i)); rc.addEventListener("touchstart", e => show(e, i), { passive: true }); rc.addEventListener("mouseleave", () => tip.style.display = "none"); });
  svgEl.addEventListener("mouseleave", () => tip.style.display = "none");
}

/* ===================== SETTINGS ===================== */
async function renderSettings() {
  const s = state.settings;
  const cropRows = state.crops.map(c => `
    <div class="crop-row" data-crop="${c.id}">
      <div class="swatches">${[1, 2, 3, 4, 5, 6, 7, 8, 0].map(k => `<button class="swatch" data-color="${k}" aria-pressed="${c.color === k}" style="--c:var(--s${k})" title="${k ? "Colour " + k : "Grey"}"></button>`).join("")}</div>
      <input type="text" value="${esc(c.name)}" data-rename ${c.archived ? "style='opacity:.55'" : ""}>
      <div class="row"><button class="btn ghost" data-archive title="${c.archived ? "Unarchive (show in quick-pick)" : "Archive (hide from quick-pick, keep history)"}">${c.archived ? "Unarchive" : "Archive"}</button><button class="btn ghost danger" data-delete title="Delete crop and all its harvests">✕</button></div>
      <div class="varlist">${state.varieties.filter(v => v.crop_id === c.id).map(v => `<span class="chip" data-var="${v.id}">${esc(v.name)} <button class="btn ghost" data-var-rename="${v.id}" title="Rename">✎</button><button class="btn ghost" data-var-del="${v.id}" title="Delete">✕</button></span>`).join("")}<button class="chip add" data-var-add="${c.id}">+ variety</button></div>
    </div>`).join("");
  $("#view").innerHTML = `
  <div class="two">
  <div class="card">
    <h2>Location &amp; weather</h2>
    <label class="f">Find a place</label>
    <input type="search" id="geo-q" placeholder="Town or city…" value="">
    <div class="geo hidden" id="geo-res"></div>
    <label class="f">Location name</label><input type="text" id="s-name" value="${esc(s.location_name)}">
    <div class="inl"><div><label class="f">Latitude</label><input type="number" id="s-lat" step="0.0001" value="${s.lat ?? ""}"></div><div><label class="f">Longitude</label><input type="number" id="s-lon" step="0.0001" value="${s.lon ?? ""}"></div></div>
    <button class="btn primary" id="s-save" style="margin-top:12px">Save location</button>
    <p class="muted small">Saving a new location re-runs the weather backfill for it. Timezone: ${esc(s.timezone)}.</p>
    <hr style="border:none;border-top:1px solid var(--rule);margin:14px 0">
    <p class="small" style="margin:0 0 8px"><b>Weather fetch:</b> ${s.weather_enabled ? "enabled (Open-Meteo, daily at 06:05)" : "disabled via GARDEN_WEATHER=0"}<br>
      <span class="muted">Last fetch: ${s.weather_last_fetch ? new Date(s.weather_last_fetch).toLocaleString() : "never"} · backfill ${s.backfill_done ? "done" : "pending"}</span>
      ${s.weather_last_error ? `<br><span style="color:var(--danger)">${esc(s.weather_last_error)}</span>` : ""}</p>
    <label class="f">Backfill from</label>
    <div class="inl"><input type="date" id="s-bf" value="${s.backfill_start}"><button class="btn" id="s-backfill" style="flex:0 0 auto" ${s.weather_enabled ? "" : "disabled"}>Run backfill</button></div>
    <p class="muted small">Fetches every day from that date to today (manual days are left alone). Run it with an earlier date if you want full-year frost and degree-day stats.</p>
  </div>
  <div class="card">
    <h2>Data</h2>
    <div class="row"><a class="btn" href="${API}/export.csv" download>Export harvests CSV</a><label class="btn">Import CSV<input type="file" id="s-import" accept=".csv,text/csv" class="hidden"></label></div>
    <p class="muted small">Import accepts the Notion export format (Date, Crop, Weight (g)) plus optional Variety and Notes columns. Duplicate rows are skipped.</p>
    <p class="muted small" style="margin-bottom:0">Database: <code>data/garden.db</code> on the server — see deploy/backup.sh for nightly copies.</p>
  </div></div>
  <div class="card">
    <h2>Crops &amp; varieties</h2>
    ${cropRows || `<p class="empty">No crops yet.</p>`}
    <p class="muted small" style="margin:10px 0 0">Colours are used everywhere a crop appears. Eight distinct colours are available; extra crops get grey in charts.</p>
  </div>`;

  let geoT; $("#geo-q").oninput = e => { clearTimeout(geoT); const q = e.target.value.trim(); if (q.length < 2) { $("#geo-res").classList.add("hidden"); return; } geoT = setTimeout(guard(async () => {
    const res = await api("/geocode?q=" + encodeURIComponent(q)); const box = $("#geo-res");
    box.innerHTML = res.map((r, i) => `<button type="button" data-i="${i}">${esc(r.name)} <span class="muted small">${r.lat.toFixed(3)}, ${r.lon.toFixed(3)}</span></button>`).join("") || `<button type="button" disabled>No matches</button>`;
    box.classList.remove("hidden");
    box.querySelectorAll("button[data-i]").forEach(b => b.onclick = () => { const r = res[Number(b.dataset.i)]; $("#s-name").value = r.name; $("#s-lat").value = r.lat; $("#s-lon").value = r.lon; box.classList.add("hidden"); });
  }), 350); };
  $("#s-save").onclick = guard(async () => {
    const lat = parseFloat($("#s-lat").value), lon = parseFloat($("#s-lon").value);
    if (isNaN(lat) || isNaN(lon)) { toast("Enter latitude and longitude"); return; }
    await jpatch("/settings", { lat, lon, location_name: $("#s-name").value.trim() }); toast("Location saved — fetching weather"); await loadBase(); renderSettings();
  });
  $("#s-backfill").onclick = guard(async () => { await jpost("/weather/backfill", { start: $("#s-bf").value }); toast("Backfill started"); });
  $("#s-import").onchange = guard(async e => { const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append("file", f); const res = await api("/import/csv", { method: "POST", body: fd }); toast(`Imported ${res.added}, skipped ${res.skipped}`); await loadBase(); renderSettings(); });
  document.querySelectorAll(".crop-row").forEach(row => {
    const id = Number(row.dataset.crop);
    row.querySelectorAll("[data-color]").forEach(b => b.onclick = guard(async () => { await jpatch("/crops/" + id, { color: Number(b.dataset.color) }); await loadBase(); renderSettings(); }));
    const inp = row.querySelector("[data-rename]"); inp.onchange = guard(async () => { const name = inp.value.trim(); if (!name) return; await jpatch("/crops/" + id, { name }); toast("Renamed"); await loadBase(); });
    row.querySelector("[data-archive]").onclick = guard(async () => { const c = cropById(id); await jpatch("/crops/" + id, { archived: !c.archived }); await loadBase(); renderSettings(); });
    row.querySelector("[data-delete]").onclick = guard(async () => { const c = cropById(id); if (!confirm(`Delete ${c.name} and its ${c.harvests} harvest(s)? This cannot be undone.`)) return; await jdel("/crops/" + id); toast("Deleted"); await loadBase(); renderSettings(); });
    row.querySelectorAll("[data-var-add]").forEach(b => b.onclick = guard(async () => { const name = prompt("New variety name"); if (!name?.trim()) return; await jpost("/varieties", { crop_id: id, name: name.trim() }); await loadBase(); renderSettings(); }));
    row.querySelectorAll("[data-var-rename]").forEach(b => b.onclick = guard(async () => { const v = state.varieties.find(v => v.id === Number(b.dataset.varRename)); const name = prompt("Rename variety", v.name); if (!name?.trim() || name === v.name) return; await jpatch("/varieties/" + v.id, { name: name.trim() }); await loadBase(); renderSettings(); }));
    row.querySelectorAll("[data-var-del]").forEach(b => b.onclick = guard(async () => { const v = state.varieties.find(v => v.id === Number(b.dataset.varDel)); if (!confirm(`Delete variety "${v.name}"? Harvests keep their weights but lose the variety.`)) return; await jdel("/varieties/" + v.id); await loadBase(); renderSettings(); }));
  });
}

/* ===================== live updates & boot ===================== */
function connectEvents() {
  try {
    const es = new EventSource(API + "/events"); let t;
    es.onmessage = ev => { clearTimeout(t); t = setTimeout(async () => { if ($("#modal")) return; await loadBase(); render(); }, 400); };
    es.onerror = () => { es.close(); setTimeout(connectEvents, 5000); };
  } catch (e) { }
}
(async function boot() {
  $("#u-metric").onclick = () => setUnits(true); $("#u-imperial").onclick = () => setUnits(false);
  $("#u-metric").setAttribute("aria-pressed", U.metric); $("#u-imperial").setAttribute("aria-pressed", !U.metric);
  const h = location.hash.replace("#", ""); if (RENDER[h]) state.view = h;
  window.addEventListener("hashchange", () => { const v = location.hash.replace("#", ""); if (RENDER[v] && v !== state.view) { state.view = v; render(); } });
  try { await loadBase(); } catch (e) { $("#view").innerHTML = `<div class="card"><p class="muted">Can't reach the server: ${esc(e.message)}</p></div>`; return; }
  await render();
  connectEvents();
  window.addEventListener("resize", () => { if (state.view === "analyze") { clearTimeout(window._rz); window._rz = setTimeout(render, 200); } });
})();
