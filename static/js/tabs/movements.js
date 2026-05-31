import * as api from "../api.js";
import { CAT_COLOR, CAT_LABEL, seasonLabel } from "../utils.js";

let _transitions  = [];   // ordered list from API e.g. ["1920-2021", ..., "2425-2526"]
let _currentTrans = null;
let _currentType  = "all";
let _currentCat   = "";

const el = (id) => document.getElementById(id);

const _ICONS   = { up:"↑", down:"↓", new:"★", gone:"✗" };
const _CLASSES = { up:"move-up", down:"move-down", new:"move-new", gone:"move-gone" };
const _LEVEL_LABELS = { 3:"Élite", 2:"D.H.", 1:"Primera", 0:"—" };
const _LEVEL_COLORS = { 3:"#7c3aed", 2:"#0ea5e9", 1:"#10b981", 0:"#64748b" };

function _badge(lvl) {
  return `<span class="badge" style="background:${_LEVEL_COLORS[lvl] || "#64748b"}">${_LEVEL_LABELS[lvl] || "—"}</span>`;
}

function _fmt(v)  { return v != null ? v.toFixed(3) : "—"; }
function _fmti(v) { return v != null ? String(v)    : "—"; }

// Map season id (e.g. "2526") to the transition that ends with it ("2425-2526").
// Falls back to the most recent transition if no match (e.g. for "all").
function _seasonToTransition(season) {
  if (season && season !== "all") {
    const match = _transitions.find(k => k.endsWith(`-${season}`));
    if (match) return match;
  }
  return _transitions[_transitions.length - 1] || null;
}

function _updateHeaders(trans) {
  if (!trans) return;
  const [so, sn] = trans.split("-");
  const set = (id, txt) => { const e = el(id); if (e) e.textContent = txt; };
  set("moves-th-old",       `${so.slice(0,2)}/${so.slice(2)}`);
  set("moves-th-new",       `${sn.slice(0,2)}/${sn.slice(2)}`);
  set("moves-th-noms-old",  `Noms ${so.slice(0,2)}/${so.slice(2)}`);
  set("moves-th-score-old", `Score ${so.slice(0,2)}/${so.slice(2)}`);
  set("moves-th-noms-new",  `Noms ${sn.slice(0,2)}/${sn.slice(2)}`);
  set("moves-th-score-new", `Score ${sn.slice(0,2)}/${sn.slice(2)}`);
}

function _applyFilters() {
  let visible = 0;
  document.querySelectorAll("#moves-body tr[data-type]").forEach(row => {
    const matchType = _currentType === "all" || row.dataset.type === _currentType;
    const matchCat  = !_currentCat  || row.dataset.cat  === _currentCat;
    row.style.display = (matchType && matchCat) ? "" : "none";
    if (matchType && matchCat) visible++;
  });
  const lbl = el("moves-count-label");
  if (lbl) lbl.textContent = `${visible} árbitro${visible !== 1 ? "s" : ""}`;
}

async function _renderTransition(trans) {
  const tbody = el("moves-body");
  if (!tbody || !trans) return;
  tbody.innerHTML = `<tr class="loading-row"><td colspan="10"><div class="spinner"></div></td></tr>`;
  _updateHeaders(trans);
  try {
    const data = await api.getMovements(trans);
    const rows = data[trans] || [];
    tbody.innerHTML = rows.map(r => {
      const b_old = r.cat_old ? _badge(r.lvl_old) : '<span style="color:#475569">—</span>';
      const b_new = r.cat_new ? _badge(r.lvl_new) : '<span style="color:#475569">—</span>';
      return `<tr data-type="${r.move_type}" data-cat="${r.cat_new || r.cat_old || ""}">
        <td><span class="${_CLASSES[r.move_type]}">${_ICONS[r.move_type]}</span></td>
        <td>${r.name}</td>
        <td>${b_old}</td><td style="color:#475569;text-align:center">→</td><td>${b_new}</td>
        <td class="num dim">${_fmti(r.noms_old)}</td>
        <td class="num dim">${_fmt(r.score_old)}</td>
        <td class="num">${_fmti(r.noms_new)}</td>
        <td class="num bold">${_fmt(r.score_new)}</td>
        <td class="num">${r.rank_str}</td>
      </tr>`;
    }).join("");
    _applyFilters();
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="10" style="color:#ef4444">${e.message}</td></tr>`;
  }
}

export async function load(season) {
  if (_transitions.length === 0) {
    _transitions = await api.getTransitions();
  }
  const trans = _seasonToTransition(season);
  _currentTrans = trans;
  _renderTransition(trans);
}

export function init() {
  const panel = el("tab-moves");
  if (!panel) return;

  panel.innerHTML = `
<div style="margin-bottom:.75rem">
  <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap">
    <span style="color:#64748b;font-size:.82rem">Ver:</span>
    <button class="season-btn active" id="mf-all"  onclick="window._movesType('all',this)">Todos</button>
    <button class="season-btn" id="mf-up"   onclick="window._movesType('up',this)"><span class="move-up">↑</span> Ascensos</button>
    <button class="season-btn" id="mf-down" onclick="window._movesType('down',this)"><span class="move-down">↓</span> Descensos</button>
    <button class="season-btn" id="mf-new"  onclick="window._movesType('new',this)"><span class="move-new">★</span> Nuevos</button>
    <button class="season-btn" id="mf-gone" onclick="window._movesType('gone',this)"><span class="move-gone">✗</span> Desaparecen</button>
    <span id="moves-count-label" style="color:#64748b;font-size:.8rem;margin-left:auto"></span>
  </div>
  <div style="display:flex;align-items:center;gap:.5rem;margin-top:.5rem">
    <span style="color:#64748b;font-size:.82rem">Categoría:</span>
    <select id="moves-cat-filter" class="form-ctrl" style="width:auto" onchange="window._movesCat()">
      <option value="">Todas</option>
      <option value="elite">Élite</option>
      <option value="honor">Honor</option>
      <option value="primera">1ª División</option>
    </select>
  </div>
</div>
<div class="section">
<table id="moves-table">
  <thead><tr>
    <th style="width:2rem"></th>
    <th>Árbitro</th>
    <th id="moves-th-old"></th>
    <th style="width:1.5rem"></th>
    <th id="moves-th-new"></th>
    <th style="text-align:right" id="moves-th-noms-old"></th>
    <th style="text-align:right" id="moves-th-score-old"></th>
    <th style="text-align:right" id="moves-th-noms-new"></th>
    <th style="text-align:right" id="moves-th-score-new"></th>
    <th style="text-align:right" title="Posición/total en su categoría durante la temporada anterior (la que motivó el cambio)">Ranking ant.</th>
  </tr></thead>
  <tbody id="moves-body"></tbody>
</table>
</div>`;

  window._movesType = (type, btn) => {
    _currentType = type;
    panel.querySelectorAll(".season-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    _applyFilters();
  };
  window._movesCat = () => {
    _currentCat = el("moves-cat-filter")?.value || "";
    _applyFilters();
  };
}
