import * as api from "../api.js";
import { CAT_COLOR, CAT_LABEL, CAT_RANK, debounce } from "../utils.js";

let _chart = null;
let _data  = null;   // season progression data
let _selected = new Set();
let _season = null;

const el = (id) => document.getElementById(id);

async function _fetchSeason(season) {
  el("prog-loading").style.display = "block";
  try {
    _data   = await api.getProgression(season);
    _season = season;
    _selected.clear();
    _updateDropdown();
    _autoSelect();
  } catch(e) {
    el("prog-loading").textContent = `Error: ${e.message}`;
  } finally {
    el("prog-loading").style.display = "none";
  }
}

function _filtered() {
  if (!_data) return [];
  const cat     = el("prog-cat")?.value || "";
  const gender  = el("prog-gender")?.value || "";
  const minG    = parseInt(el("prog-min-games")?.value) || 1;
  const search  = (el("prog-search")?.value || "").toLowerCase();

  return Object.values(_data).filter(d => {
    if (cat    && d.category !== cat) return false;
    if (gender && d.gender   !== gender) return false;
    if (d.games < minG) return false;
    if (search && !`${d.ref_a} ${d.ref_b}`.toLowerCase().includes(search)) return false;
    return true;
  });
}

function _updateDropdown() {
  const dd = el("prog-dropdown");
  if (!dd) return;
  const items = _filtered();
  const header = document.createElement("div");
  header.style.cssText = "padding:.4rem .5rem;border-bottom:2px solid #334155;display:flex;justify-content:space-between;align-items:center;background:#0f172a;position:sticky;top:0;z-index:1";
  header.innerHTML = `<span style="color:#94a3b8;font-size:.75rem">${items.length} pareja${items.length!==1?"s":""}</span>
    <button style="padding:.15rem .5rem;background:#0ea5e9;color:#0f172a;border:none;border-radius:.25rem;cursor:pointer;font-size:.75rem;font-weight:600">Sel. todos</button>`;
  header.querySelector("button").onclick = (e) => {
    e.stopPropagation();
    items.forEach(d => _selected.add(`${d.ref_a}|||${d.ref_b}`));
    _updateDropdown();
    _renderSelected();
  };
  dd.innerHTML = "";
  dd.appendChild(header);

  items.forEach(d => {
    const key = `${d.ref_a}|||${d.ref_b}`;
    const sel = _selected.has(key);
    const color = CAT_COLOR[d.category] || "#64748b";
    const lbl   = CAT_LABEL[d.category] || "?";
    const gLbl  = d.gender === "F" ? "♀" : d.gender === "M" ? "♂" : "?";
    const div = document.createElement("div");
    div.style.cssText = `padding:.5rem;cursor:pointer;border-bottom:1px solid #1e293b;background:${sel?"#132040":"transparent"}`;
    div.innerHTML = `<span style="color:${color};font-weight:600;min-width:40px">${lbl}</span>
      <span style="color:#94a3b8;margin:0 .5rem">${gLbl}</span>
      <span>${d.ref_a} — ${d.ref_b}</span>
      <span style="color:#64748b;font-size:.75rem;margin-left:auto">(${d.games})</span>
      <span style="color:${sel?"#0ea5e9":"#475569"};margin-left:.5rem">${sel?"✓":"○"}</span>`;
    div.onclick = (e) => {
      e.stopPropagation();
      sel ? _selected.delete(key) : _selected.add(key);
      _updateDropdown();
      _renderSelected();
    };
    dd.appendChild(div);
  });
}

function _renderSelected() {
  const cont = el("prog-selected");
  if (!cont) return;
  if (_selected.size === 0) {
    cont.innerHTML = '<span style="color:#94a3b8;font-size:.8rem">Ninguna seleccionada</span>';
    return;
  }
  cont.innerHTML = "";
  [..._selected].sort().forEach(key => {
    const [a, b] = key.split("|||");
    const tag = document.createElement("div");
    tag.className = "prog-tag";
    tag.title = "Clic para eliminar";
    tag.innerHTML = `${a} — ${b} <span style="opacity:.7">×</span>`;
    tag.onclick = () => { _selected.delete(key); _renderSelected(); _updateDropdown(); };
    cont.appendChild(tag);
  });
}

function _autoSelect() {
  if (!_data) return;
  Object.values(_data).filter(d => d.category === "elite").forEach(d => {
    _selected.add(`${d.ref_a}|||${d.ref_b}`);
  });
  _renderSelected();
  _updateDropdown();
  if (_selected.size > 0) drawChart();
}

export function drawChart() {
  if (!_data || _selected.size === 0) return;
  const colors = ["#0ea5e9","#f59e0b","#10b981","#ef4444","#8b5cf6","#ec4899","#06b6d4","#eab308",
                  "#f97316","#a3e635","#22d3ee","#e879f9","#fb7185","#4ade80","#facc15","#60a5fa"];

  const selected = [..._selected].map(k => k.split("|||"));
  const allDates = new Set();
  selected.forEach(([a, b]) => {
    const d = _data[`${a}|||${b}`];
    if (d) d.progression.forEach(p => allDates.add(p.date));
  });
  const labels = [...allDates].sort();

  const datasets = selected.map(([refA, refB], idx) => {
    const key  = `${refA}|||${refB}`;
    const d    = _data[key];
    if (!d) return null;
    const pMap = Object.fromEntries(d.progression.map(p => [p.date, p]));
    let carry  = null;
    const vals = labels.map(date => {
      if (pMap[date]) carry = pMap[date];
      return carry ? carry.rank : null;
    });
    const lastRealIdx = d.last_game_date ? labels.indexOf(d.last_game_date) : -1;
    return {
      label: refA.split(" ").map(w=>w[0]).join(".") + " – " + refB.split(" ").map(w=>w[0]).join("."),
      _fullName: `${refA} — ${refB}`,
      data: vals,
      borderColor: colors[idx % colors.length],
      borderWidth: 2, tension: .3, fill: false, spanGaps: true,
      pointRadius: 0, pointHoverRadius: 0, pointHitRadius: 20,
      segment: { borderDash: ctx => (lastRealIdx >= 0 && ctx.p0DataIndex >= lastRealIdx) ? [5,5] : undefined },
    };
  }).filter(Boolean);

  if (_chart) _chart.destroy();
  const ctx = el("progressionChart")?.getContext("2d");
  if (!ctx) return;

  _chart = new Chart(ctx, {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode:"nearest", intersect:false },
      plugins: {
        legend: { labels: { color:"#e2e8f0", font:{ size:11 }, boxWidth:14 }, display:true, position:"right" },
        tooltip: {
          callbacks: {
            title: items => datasets[items[0]?.datasetIndex]?._fullName || "",
            label: ctx => `${ctx.label}  →  #${ctx.parsed.y}`,
          },
          titleFont: { size:13, weight:"bold" }, bodyFont: { size:12 }, padding:10,
        },
      },
      scales: {
        x: { ticks:{ color:"#94a3b8", maxRotation:45 }, grid:{ color:"#1e293b" } },
        y: { reverse:true, min:0, ticks:{ color:"#94a3b8", stepSize:1, precision:0, callback: v => v >= 1 ? v : "" }, grid:{ color:"#1e293b" },
             title:{ display:true, text:"Ranking (menor es mejor)", color:"#94a3b8" } },
      },
    },
  });
}

export async function load(season) {
  if (season !== _season) await _fetchSeason(season);
}

export function init() {
  const panel = el("tab-progression");
  if (!panel) return;

  panel.innerHTML = `
<div class="prog-controls">
  <div><label class="form-label">Categoría:</label>
    <select id="prog-cat" class="form-ctrl" onchange="window._progRefresh()">
      <option value="">Todas</option><option value="elite">Élite</option>
      <option value="honor">Honor</option><option value="primera">1ª División</option>
    </select></div>
  <div><label class="form-label">Género:</label>
    <select id="prog-gender" class="form-ctrl" onchange="window._progRefresh()">
      <option value="">Todos</option><option value="M">Masculino</option><option value="F">Femenino</option>
    </select></div>
  <div><label class="form-label">Mín. partidos:</label>
    <input type="number" id="prog-min-games" value="1" min="1" class="form-ctrl" onchange="window._progRefresh()"></div>
</div>
<div style="margin-bottom:1rem;position:relative">
  <label class="form-label">Buscar y elegir parejas:</label>
  <input type="text" id="prog-search" class="form-ctrl" placeholder="Escribe un nombre para filtrar…"
    onfocus="document.getElementById('prog-dropdown').style.display='block'; window._progSearchInput()"
    oninput="window._progSearchInput()">
  <div id="prog-dropdown"></div>
</div>
<div style="margin-bottom:1rem">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.3rem">
    <label class="form-label" style="margin:0">Parejas seleccionadas:</label>
    <button onclick="window._progClear()" style="padding:.2rem .6rem;background:#1e293b;border:1px solid #334155;color:#94a3b8;border-radius:.3rem;cursor:pointer;font-size:.75rem">✕ Limpiar</button>
  </div>
  <div id="prog-selected" class="prog-selected-wrap"><span style="color:#94a3b8;font-size:.8rem">Ninguna seleccionada</span></div>
</div>
<p id="prog-loading" style="color:#94a3b8;display:none">Calculando…</p>
<button onclick="window._progDraw()" style="padding:.5rem 1rem;background:#0ea5e9;color:#fff;border:none;border-radius:.4rem;cursor:pointer;margin-bottom:1rem">Mostrar</button>
<div id="prog-chart-wrap"><canvas id="progressionChart"></canvas></div>`;

  const dbl = debounce(() => _updateDropdown());
  window._progRefresh    = () => { _selected.clear(); _updateDropdown(); _renderSelected(); };
  window._progSearchInput = () => { document.getElementById("prog-dropdown").style.display="block"; dbl(); };
  window._progClear      = () => { _selected.clear(); _renderSelected(); _updateDropdown(); };
  window._progDraw       = drawChart;

  document.addEventListener("click", e => {
    const dd = el("prog-dropdown");
    const sr = el("prog-search");
    if (dd && sr && !dd.contains(e.target) && !sr.contains(e.target)) dd.style.display = "none";
  });
}
