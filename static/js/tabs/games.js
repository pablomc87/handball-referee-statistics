import * as api from "../api.js";
import { formatDate, debounce, spinner, renderPagination, genderFromCategoria } from "../utils.js";

let _state = { season:"all", date_from:"", date_to:"", competition:"", phase:"", home:"", away:"", ref:"", gender:"all", page:1, per_page:50 };
let _dirty = true;
let _comps = {};  // competicion_name → [torneo_name, ...]

const el = (id) => document.getElementById(id);

async function _loadComps(season) {
  const list = await api.getCompetitions(season === "all" ? undefined : season);
  _comps = {};
  list.forEach(({ competicion_name, torneo_name }) => {
    (_comps[competicion_name] ??= []).push(torneo_name);
  });
  const sel = el("games-comp-filter");
  if (!sel) return;
  const cur = sel.value;
  sel.innerHTML = `<option value="">Todas</option>` +
    Object.keys(_comps).sort().map(c => `<option value="${c.toLowerCase()}">${c}</option>`).join("");
  if (cur) sel.value = cur;
  _onCompChange();
}

function _onCompChange() {
  const sel = el("games-comp-filter");
  const pSel = el("games-phase-filter");
  if (!sel || !pSel) return;
  const comp = sel.value;
  const matches = Object.keys(_comps).find(c => c.toLowerCase() === comp);
  pSel.innerHTML = `<option value="">Todas</option>` +
    (matches ? _comps[matches].map(t => `<option value="${t.toLowerCase()}">${t}</option>`).join("") : "");
  _state.competition = comp;
  _state.phase = "";
}

function _row(g, i) {
  const score = g.score_home != null ? `${g.score_home}–${g.score_away}` : "Pend.";
  return `<tr>
    <td class="num rank">#${i}</td>
    <td class="num dim" data-sort="${g.date}">${formatDate(g.date)}</td>
    <td class="ell" title="${g.competicion_name}">${g.competicion_name || "—"}</td>
    <td class="ell dim" style="font-size:.77rem" title="${g.torneo_name}">${g.torneo_name || "—"}</td>
    <td class="ell" title="${g.home_team}">${g.home_team || "—"}</td>
    <td class="ell" title="${g.away_team}">${g.away_team || "—"}</td>
    <td class="num">${score}</td>
    <td class="ell" title="${g.referee_1}">${g.referee_1 ? g.referee_1.replace(/\b(\w)/g,(_,c)=>c.toUpperCase()) : "—"}</td>
    <td class="ell" title="${g.referee_2}">${g.referee_2 ? g.referee_2.replace(/\b(\w)/g,(_,c)=>c.toUpperCase()) : "—"}</td>
    <td class="num dim">${(g.competition_mod||0).toFixed(2)}</td>
    <td class="num dim">${(g.match_quality||0).toFixed(3)}</td>
    <td class="num dim">${(g.score_factor||0).toFixed(3)}</td>
    <td class="num bold">${(g.nomination_score||0).toFixed(3)}</td>
  </tr>`;
}

async function _load() {
  const tbody = el("games-body");
  if (!tbody) return;
  tbody.innerHTML = spinner();

  const { season, date_from, date_to, competition, phase, home, away, ref, gender, page, per_page } = _state;
  try {
    const data = await api.getGames({
      season: season === "all" ? undefined : season,
      date_from: date_from || undefined, date_to: date_to || undefined,
      competition: competition || undefined, phase: phase || undefined,
      home: home || undefined, away: away || undefined,
      ref: ref || undefined,
      gender: gender === "all" ? undefined : gender,
      page, per_page,
    });

    const offset = (page - 1) * per_page;
    tbody.innerHTML = data.items.map((g, i) => _row(g, offset + i + 1)).join("");

    el("games-count-label").textContent = `${data.total} partido${data.total!==1?"s":""}`;

    const pgEl = el("games-pagination");
    pgEl.innerHTML = "";
    const pg = renderPagination(data.total, page, per_page, (p) => { _state.page = p; _load(); });
    if (pg) pgEl.appendChild(pg);

    _dirty = false;
  } catch(e) {
    tbody.innerHTML = `<tr><td colspan="13" style="color:#ef4444;text-align:center">Error: ${e.message}</td></tr>`;
  }
}

const _dbl = debounce(() => { _state.page = 1; _load(); });

export function markDirty() { _dirty = true; }

export async function load(season) {
  _state.season = season;
  _state.page = 1;
  await _loadComps(season);
  _load();
}

export function init() {
  const panel = el("tab-games");
  if (!panel) return;

  panel.innerHTML = `
<div style="display:flex;align-items:center;justify-content:space-between;gap:.75rem;flex-wrap:wrap;margin-bottom:.75rem">
  <span class="count-label" id="games-count-label"></span>
  <div style="display:flex;gap:.5rem">
    <button class="season-btn active" id="gg-all" onclick="window._gamesGender('all',this)">Todos</button>
    <button class="season-btn" id="gg-m" onclick="window._gamesGender('M',this)">Masculino</button>
    <button class="season-btn" id="gg-f" onclick="window._gamesGender('F',this)">Femenino</button>
  </div>
  <button onclick="window._gamesClear()" class="clear-all-btn">✕ Limpiar filtros</button>
</div>
<div class="section">
<table id="games-table">
  <thead>
    <tr>
      <th style="width:2.5rem">#</th>
      <th style="text-align:right;width:85px">Fecha</th>
      <th style="width:16%">Competición</th>
      <th style="width:14%">Fase</th>
      <th style="width:13%">Local</th>
      <th style="width:13%">Visitante</th>
      <th style="text-align:right;width:65px">Result.</th>
      <th style="width:12%">Árbitro 1</th>
      <th style="width:12%">Árbitro 2</th>
      <th style="text-align:right;width:55px">Mod.</th>
      <th style="text-align:right;width:60px">Calidad</th>
      <th style="text-align:right;width:60px">Factor</th>
      <th style="text-align:right;width:60px">Score</th>
    </tr>
    <tr class="filter-row">
      <td></td>
      <td><div class="date-pair">
        <input type="date" id="gdate-from" title="Desde">
        <input type="date" id="gdate-to" title="Hasta">
      </div></td>
      <td><select id="games-comp-filter" onchange="window._gamesOnComp()">
        <option value="">Todas</option>
      </select></td>
      <td><select id="games-phase-filter" onchange="window._gamesOnPhase()">
        <option value="">Todas</option>
      </select></td>
      <td><input type="text" id="gf-home" placeholder="buscar…"></td>
      <td><input type="text" id="gf-away" placeholder="buscar…"></td>
      <td></td>
      <td><input type="text" id="gf-ref" placeholder="buscar…"></td>
      <td></td><td></td><td></td><td></td><td></td>
    </tr>
  </thead>
  <tbody id="games-body"></tbody>
</table>
</div>
<div id="games-pagination"></div>`;

  const dbl = debounce(() => { _state.page = 1; _load(); });

  ["gdate-from","gdate-to"].forEach(id => el(id)?.addEventListener("change", () => {
    _state.date_from = el("gdate-from")?.value || "";
    _state.date_to   = el("gdate-to")?.value   || "";
    _state.page = 1; _load();
  }));

  ["gf-home","gf-away","gf-ref"].forEach(id => el(id)?.addEventListener("input", () => {
    _state.home = el("gf-home")?.value.trim() || "";
    _state.away = el("gf-away")?.value.trim() || "";
    _state.ref  = el("gf-ref")?.value.trim()  || "";
    dbl();
  }));

  window._gamesGender = (g, btn) => {
    _state.gender = g;
    panel.querySelectorAll("#gg-all,#gg-m,#gg-f").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    _state.page = 1; _load();
  };
  window._gamesOnComp = () => {
    _onCompChange();
    _state.page = 1; _load();
  };
  window._gamesOnPhase = () => {
    _state.phase = el("games-phase-filter")?.value || "";
    _state.page = 1; _load();
  };
  window._gamesClear = () => {
    _state = { ..._state, date_from:"", date_to:"", competition:"", phase:"", home:"", away:"", ref:"", gender:"all", page:1 };
    ["gdate-from","gdate-to","gf-home","gf-away","gf-ref"].forEach(id => { const e = el(id); if(e) e.value=""; });
    el("games-comp-filter").value="";
    el("games-phase-filter").innerHTML='<option value="">Todas</option>';
    panel.querySelectorAll("#gg-all,#gg-m,#gg-f").forEach(b => b.classList.remove("active"));
    el("gg-all").classList.add("active");
    _load();
  };
}
