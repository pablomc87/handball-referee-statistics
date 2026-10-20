import * as api from "../api.js";
import { CAT_COLOR, CAT_LABEL, seasonLabel, debounce } from "../utils.js";

let _data = null;
let _type = "all";

const el = (id) => document.getElementById(id);

function _renderRows(data) {
  return data.map(ident => {
    const cat   = ident.category || "?";
    const color = CAT_COLOR[cat] || "#64748b";
    const label = CAT_LABEL[cat] || "?";
    const badge = `<span class="badge" style="background:${color}">${label}</span>`;
    const gColor = ident.gender === "M" ? "#38bdf8" : ident.gender === "F" ? "#f472b6" : "#475569";
    const gLabel = ident.gender === "M" ? "♂" : ident.gender === "F" ? "♀" : "?";
    const genderBadge = `<span style="color:${gColor}">${gLabel}</span>`;

    const seasonBadges = ident.season_ids.map(s => {
      const sc  = ident.seasons[s]?.category || "?";
      const scl = CAT_COLOR[sc] || "#64748b";
      const sll = CAT_LABEL[sc] || "?";
      return `<span class="badge" style="background:${scl};font-size:.68rem" title="${sll}">${seasonLabel(s)}</span>`;
    }).join(" ");

    const variants = ident.has_variants
      ? Object.entries(ident.variants).sort(([a],[b])=>b.localeCompare(a)).map(
          ([s, name]) => `<span style="color:#94a3b8">${name}</span> <span style="color:#475569">(${seasonLabel(s)})</span>`
        ).join("; ")
      : '<span style="color:#334155">—</span>';

    return `<tr data-has-variants="${ident.has_variants?1:0}" data-name="${ident.canonical.toLowerCase()}">
      <td style="font-weight:500">${ident.canonical}</td>
      <td>${badge}</td>
      <td>${genderBadge}</td>
      <td style="white-space:nowrap">${seasonBadges}</td>
      <td style="font-size:.8rem">${variants}</td>
    </tr>`;
  }).join("");
}

function _applyFilters() {
  if (!_data) return;
  const q = (el("refs-search")?.value || "").toLowerCase();
  const filtered = _data.filter(r => {
    if (_type === "variants" && !r.has_variants) return false;
    if (q && !r.canonical.toLowerCase().includes(q)) return false;
    return true;
  });
  const tbody = el("refs-body");
  if (tbody) tbody.innerHTML = _renderRows(filtered);
  const lbl = el("refs-count-label");
  if (lbl) lbl.textContent = `${filtered.length} árbitro${filtered.length!==1?"s":""}`;
}

export async function load() {
  if (_data) return;   // static — no season dependency
  const tbody = el("refs-body");
  if (tbody) tbody.innerHTML = `<tr class="loading-row"><td colspan="5"><div class="spinner"></div></td></tr>`;
  try {
    _data = await api.getReferees({});
    _applyFilters();
  } catch(e) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="5" style="color:#ef4444">${e.message}</td></tr>`;
  }
}

export function init() {
  const panel = el("tab-refs");
  if (!panel) return;

  panel.innerHTML = `
<div style="display:flex;align-items:center;gap:.75rem;margin-bottom:.75rem;flex-wrap:wrap">
  <input id="refs-search" type="text" placeholder="Buscar árbitro…">
  <button class="season-btn active" id="rf-all"      onclick="window._refsType('all',this)">Todos</button>
  <button class="season-btn"        id="rf-variants" onclick="window._refsType('variants',this)">Con variantes</button>
  <span id="refs-count-label" style="color:#64748b;font-size:.8rem;margin-left:auto"></span>
</div>
<p style="color:#64748b;font-size:.78rem;margin-bottom:.75rem">
  Nombre canónico tomado del PDF más reciente. Las variantes son nombres con ortografía diferente en otras temporadas.
</p>
<div class="section">
<table id="refs-table">
  <thead><tr>
    <th>Árbitro</th><th>Cat.</th><th>Gén.</th><th>Temporadas</th><th>Variantes de nombre</th>
  </tr></thead>
  <tbody id="refs-body"></tbody>
</table>
</div>`;

  const dbl = debounce(_applyFilters);
  el("refs-search")?.addEventListener("input", dbl);

  window._refsType = (type, btn) => {
    _type = type;
    panel.querySelectorAll("#rf-all,#rf-variants").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    _applyFilters();
  };
}
