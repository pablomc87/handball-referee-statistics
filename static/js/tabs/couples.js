import * as api from "../api.js";
import { CAT_COLOR, CAT_LABEL, CAT_RANK, formatDate, debounce, spinner, renderPagination, bestCat } from "../utils.js";

let _state = { season:"all", cats:new Set(), gender:"all", min_games:1, name:"", sort_by:"avg_score", sort_dir:"desc", page:1, per_page:50 };

const el = (id) => document.getElementById(id);

function titleCase(s) {
  return (s || "").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

// ── Per-couple game cache (for tooltip + modal) ────────────────────────────
const _gamesCache = new Map();

async function _fetchGames(refA, refB) {
  const key = `${refA}|||${refB}`;
  if (_gamesCache.has(key)) return _gamesCache.get(key);
  const games = await api.getCoupleGames(refA, refB);
  _gamesCache.set(key, games);
  return games;
}

// ── Tooltip ────────────────────────────────────────────────────────────────
let _tipTimer = null;

function _reposTip(e) {
  const tip = el("c-tip");
  if (!tip || tip.style.display === "none") return;
  const x = e.clientX + 18, y = e.clientY + 18;
  tip.style.left = (x + tip.offsetWidth  > window.innerWidth  - 8 ? e.clientX - tip.offsetWidth  - 10 : x) + "px";
  tip.style.top  = (y + tip.offsetHeight > window.innerHeight - 8 ? e.clientY - tip.offsetHeight - 10 : y) + "px";
}

function _showTip(refA, refB, e) {
  clearTimeout(_tipTimer);
  _tipTimer = setTimeout(async () => {
    const tip = el("c-tip");
    if (!tip) return;
    const names = `${titleCase(refA)} / ${titleCase(refB)}`;
    tip.innerHTML = `<div class="tip-hdr">${names}</div><div class="spinner" style="margin:.5rem auto;display:block"></div>`;
    tip.style.display = "block";
    _reposTip(e);
    try {
      const games = await _fetchGames(refA, refB);
      if (tip.style.display === "none") return;  // mouse left while loading
      let html = `<div class="tip-hdr">${names}</div><table>`;
      games.slice(0, 7).forEach(g => {
        const score = g.score_home != null ? `${g.score_home}–${g.score_away}` : "Pend.";
        const phase = (g.torneo_name || "").replace(/^[^-]+-\s*/, "").substring(0, 34);
        html += `<tr>
          <td>${g.date || ""}</td>
          <td style="color:#94a3b8;max-width:150px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">${phase}</td>
          <td>${g.home_team || ""} – ${g.away_team || ""}</td>
          <td><b>${score}</b></td>
          <td style="color:#22c55e">${(g.nomination_score || 0).toFixed(3)}</td>
        </tr>`;
      });
      if (games.length > 7) html += `<tr><td colspan="5" style="color:#475569">…y ${games.length - 7} más</td></tr>`;
      html += "</table>";
      tip.innerHTML = html;
      _reposTip(e);
    } catch { /* ignore tooltip fetch errors */ }
  }, 280);
}

function _hideTip() {
  clearTimeout(_tipTimer);
  const tip = el("c-tip");
  if (tip) tip.style.display = "none";
}

// ── Modal ──────────────────────────────────────────────────────────────────
async function showModal(refA, refB) {
  _hideTip();
  const bg    = el("c-modal-bg");
  const modal = el("c-modal");
  const names = `${titleCase(refA)} / ${titleCase(refB)}`;
  modal.innerHTML = `
    <button class="close-btn" onclick="document.getElementById('c-modal-bg').style.display='none'">×</button>
    <h3>${names}</h3>
    <div class="spinner" style="margin:2rem auto;display:block"></div>`;
  bg.style.display = "block";

  try {
    const games = await _fetchGames(refA, refB);
    const thead = `<tr>
      <th style="width:7%">Fecha</th><th style="width:15%">Competición</th>
      <th style="width:14%">Fase</th><th style="width:24%">Partido</th>
      <th style="width:8%;text-align:right">Result.</th>
      <th style="width:10%;text-align:right">Clasif.</th>
      <th style="width:8%;text-align:right">Score</th>
    </tr>`;
    const rows = games.map(g => {
      const score = g.score_home != null ? `${g.score_home}–${g.score_away}` : "—";
      const ranks = (g.rank_home && g.n_teams > 1) ? `${g.rank_home}º/${g.rank_away}º` : "—";
      return `<tr>
        <td data-sort="${g.date}">${formatDate(g.date)}</td>
        <td class="dim ell" title="${g.competicion_name || ""}">${g.competicion_name || "—"}</td>
        <td class="dim ell" style="font-size:.76rem" title="${g.torneo_name || ""}">${g.torneo_name || "—"}</td>
        <td class="ell" title="${g.home_team} – ${g.away_team}">${g.home_team} – ${g.away_team}</td>
        <td class="num"><b>${score}</b></td>
        <td class="num dim">${ranks}</td>
        <td class="num bold">${(g.nomination_score || 0).toFixed(3)}</td>
      </tr>`;
    }).join("");
    modal.innerHTML = `
      <button class="close-btn" onclick="document.getElementById('c-modal-bg').style.display='none'">×</button>
      <h3>${names}</h3>
      <p class="m-sub">${games.length} partido${games.length !== 1 ? "s" : ""} juntos</p>
      <table id="modal-games-table"><thead>${thead}</thead><tbody>${rows}</tbody></table>`;
  } catch (e) {
    modal.querySelector(".spinner")?.remove();
    modal.innerHTML += `<p style="color:#ef4444">${e.message}</p>`;
  }
}

// ── Row renderer ───────────────────────────────────────────────────────────
function _row(r, rank) {
  const bc    = bestCat(r.cat_a, r.cat_b);
  const color = CAT_COLOR[bc] || "#64748b";
  const label = CAT_LABEL[bc] || "?";
  // Store original-case names for API lookup; display as Title Case
  return `<tr
    data-ref-a="${r.ref_a}"
    data-ref-b="${r.ref_b}"
    style="cursor:pointer">
    <td class="num rank">#${rank}</td>
    <td><span class="badge" style="background:${color}">${label}</span></td>
    <td class="couple-names">
      <div>${titleCase(r.ref_a)}</div>
      <div>${titleCase(r.ref_b)}</div>
    </td>
    <td class="num">${r.games}</td>
    <td class="num dim">${formatDate(r.first_game)}</td>
    <td class="num dim">${formatDate(r.last_game)}</td>
    <td class="num bold">${(r.total_score || 0).toFixed(3)}</td>
    <td class="num">${(r.avg_score || 0).toFixed(3)}</td>
    <td class="num">${(r.best_score || 0).toFixed(3)}</td>
  </tr>`;
}

// ── Load ───────────────────────────────────────────────────────────────────
async function _load() {
  const tbody = el("couples-body");
  if (!tbody) return;
  tbody.innerHTML = spinner();

  const { season, cats, gender, min_games, name, sort_by, sort_dir, page, per_page } = _state;
  try {
    const data = await api.getCouples({
      season:    season === "all" ? undefined : season,
      cat:       cats.size ? [...cats] : undefined,
      gender:    gender === "all" ? undefined : gender,
      min_games,
      name:      name || undefined,
      sort_by, sort_dir, page, per_page,
    });

    const offset = (page - 1) * per_page;
    tbody.innerHTML = data.items.map((r, i) => _row(r, offset + i + 1)).join("");

    tbody.querySelectorAll("tr").forEach(tr => {
      const refA = tr.dataset.refA;
      const refB = tr.dataset.refB;
      tr.addEventListener("click",      ()  => showModal(refA, refB));
      tr.addEventListener("mouseenter", (e) => _showTip(refA, refB, e));
      tr.addEventListener("mousemove",  (e) => _reposTip(e));
      tr.addEventListener("mouseleave", ()  => _hideTip());
    });

    const lbl = el("couple-count-label");
    if (lbl) lbl.textContent = `${data.total} pareja${data.total !== 1 ? "s" : ""}`;

    const pgEl = el("couples-pagination");
    if (pgEl) {
      pgEl.innerHTML = "";
      const pg = renderPagination(data.total, page, per_page, (p) => { _state.page = p; _load(); });
      if (pg) pgEl.appendChild(pg);
    }
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="9" style="color:#ef4444;text-align:center">Error: ${e.message}</td></tr>`;
  }
}

const _dbl = debounce(() => { _state.page = 1; _load(); });

export function load(season) {
  _state.season = season;
  _state.page   = 1;
  _gamesCache.clear();
  _load();
}

export function init() {
  const panel = el("tab-couples");
  if (!panel) return;

  panel.innerHTML = `
<div style="display:flex;align-items:center;justify-content:space-between;gap:.75rem;flex-wrap:wrap;margin-bottom:.75rem">
  <span class="count-label" id="couple-count-label"></span>
  <div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">
    <span style="color:#64748b;font-size:.82rem">Categoría:</span>
    <button class="season-btn" id="cc-elite"  onclick="window._couplesCat('elite',this)">Élite</button>
    <button class="season-btn" id="cc-honor"  onclick="window._couplesCat('honor',this)">Honor</button>
    <button class="season-btn" id="cc-primera" onclick="window._couplesCat('primera',this)">1ª Div.</button>
  </div>
  <div style="display:flex;gap:.5rem">
    <button class="season-btn active" id="cg-all" onclick="window._couplesGender('all',this)">Todos</button>
    <button class="season-btn" id="cg-m" onclick="window._couplesGender('M',this)">Masculino</button>
    <button class="season-btn" id="cg-f" onclick="window._couplesGender('F',this)">Femenino</button>
  </div>
  <button onclick="window._couplesClear()" class="clear-all-btn">✕ Limpiar filtros</button>
</div>
<div class="section">
<table id="couples-table">
  <thead>
    <tr>
      <th style="width:2.5rem">Pos.</th>
      <th>Cat.</th>
      <th>Pareja</th>
      <th class="sortable" style="text-align:right" data-col="games">Partidos</th>
      <th style="text-align:right">1er partido</th>
      <th style="text-align:right">Último</th>
      <th class="sortable" style="text-align:right" data-col="total_score">Total</th>
      <th class="sortable sort-desc" style="text-align:right" data-col="avg_score">Media</th>
      <th class="sortable" style="text-align:right" data-col="best_score">Mejor</th>
    </tr>
    <tr class="filter-row">
      <td></td><td></td>
      <td><input id="fc-name" type="text" placeholder="buscar…"></td>
      <td><input id="fc-mingames" type="number" placeholder="≥" min="1"></td>
      <td></td><td></td>
      <td></td>
      <td><input id="fc-avg" type="number" placeholder="≥" step=".001"></td>
      <td></td>
    </tr>
  </thead>
  <tbody id="couples-body"></tbody>
</table>
</div>
<div id="couples-pagination"></div>`;

  // Sort on column header click
  panel.querySelectorAll("th[data-col]").forEach(th => {
    th.addEventListener("click", () => {
      const col = th.dataset.col;
      _state.sort_dir = _state.sort_by === col
        ? (_state.sort_dir === "desc" ? "asc" : "desc")
        : "desc";
      _state.sort_by  = col;
      panel.querySelectorAll("th.sort-asc,th.sort-desc").forEach(h => h.classList.remove("sort-asc","sort-desc"));
      th.classList.add(_state.sort_dir === "asc" ? "sort-asc" : "sort-desc");
      _state.page = 1;
      _load();
    });
  });

  const dbl = debounce(() => { _state.page = 1; _load(); });
  el("fc-name")?.addEventListener("input", () => { _state.name = el("fc-name").value.trim(); dbl(); });
  el("fc-avg")?.addEventListener("input",  () => { dbl(); });
  el("fc-mingames")?.addEventListener("input", () => { _state.min_games = parseInt(el("fc-mingames").value) || 1; dbl(); });

  window._couplesCat = (cat, btn) => {
    if (_state.cats.has(cat)) _state.cats.delete(cat);
    else _state.cats.add(cat);
    btn.classList.toggle("active", _state.cats.has(cat));
    _state.page = 1;
    _load();
  };
  window._couplesGender = (g, btn) => {
    _state.gender = g;
    panel.querySelectorAll("#cg-all,#cg-m,#cg-f").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    _state.page = 1;
    _load();
  };
  window._couplesClear = () => {
    _state = { ..._state, cats: new Set(), gender:"all", min_games:1, name:"", page:1 };
    el("fc-name").value = "";
    el("fc-mingames").value = "";
    panel.querySelectorAll("#cc-elite,#cc-honor,#cc-primera").forEach(b => b.classList.remove("active"));
    panel.querySelectorAll("#cg-all,#cg-m,#cg-f").forEach(b => b.classList.remove("active"));
    el("cg-all")?.classList.add("active");
    _load();
  };

  el("c-modal-bg")?.addEventListener("click", e => {
    if (e.target === el("c-modal-bg")) el("c-modal-bg").style.display = "none";
  });
}
