import * as api from "../api.js";
import { formatDate, pctBar } from "../utils.js";

const el = () => document.getElementById("tab-stats");

function _fmtNum(n) { return (n ?? 0).toLocaleString("es-ES"); }

function _renderPanel(data) {
  const { overall: o, by_category, by_competition } = data;
  const total = o.total_matches || 1;

  const cards = [
    ["Partidos totales",     _fmtNum(o.total_matches)],
    ["Con pareja asignada",  _fmtNum(o.with_refs), `${Math.round(o.with_refs/total*100)}% del total`],
    ["Finalizados",          _fmtNum(o.finalizado)],
    ["Pendientes",           _fmtNum(o.pendiente)],
    ["Primer partido",       formatDate(o.min_date)],
    ["Último partido",       formatDate(o.max_date)],
  ].map(([lbl, val, sub=""]) =>
    `<div class="card"><div class="card-label">${lbl}</div><div class="card-value" style="font-size:${typeof val==="string"&&val.length>6?"1.3rem":"2rem"}">${val}</div>${sub?`<div class="card-sub">${sub}</div>`:""}</div>`
  ).join("");

  const catRows = by_category.map(r => `
    <tr><td>${r.categoria_name}</td>
    <td class="num">${_fmtNum(r.matches)}</td>
    <td class="num">${_fmtNum(r.finalizado)}</td>
    <td class="num">${_fmtNum(r.pendiente)}</td>
    <td>${pctBar(r.with_refs, r.matches)}</td>
    <td class="num">${formatDate(r.min_date)}</td>
    <td class="num">${formatDate(r.max_date)}</td></tr>`
  ).join("");

  let compRows = "";
  let prevCat = "", prevComp = "";
  by_competition.forEach(r => {
    const catTd  = r.categoria_name !== prevCat  ? `<td class="cat-cell"  rowspan="${by_competition.filter(x=>x.categoria_name===r.categoria_name).length}">${r.categoria_name}</td>` : "";
    const compTd = r.competicion_name !== prevComp ? `<td class="comp-cell" rowspan="${by_competition.filter(x=>x.competicion_name===r.competicion_name&&x.categoria_name===r.categoria_name).length}">${r.competicion_name}</td>` : "";
    const first  = catTd || compTd;
    compRows += `<tr class="${first?"first-torneo":"extra-torneo"}">${catTd}${compTd}
      <td class="torneo-cell">${r.torneo_name}</td>
      <td class="num">${_fmtNum(r.matches)}</td>
      <td class="num">${_fmtNum(r.finalizado)}</td>
      <td class="num">${_fmtNum(r.pendiente)}</td>
      <td>${pctBar(r.with_refs, r.matches)}</td>
      <td class="num">${formatDate(r.min_date)}</td>
      <td class="num">${formatDate(r.max_date)}</td></tr>`;
    prevCat  = r.categoria_name;
    prevComp = r.competicion_name;
  });

  return `
<div class="cards">${cards}</div>
<h2>Por categoría</h2>
<div class="section"><table>
  <thead><tr><th>Categoría</th><th style="text-align:right">Partidos</th><th style="text-align:right">Finaliz.</th><th style="text-align:right">Pendien.</th><th>Pareja asignada</th><th style="text-align:right">Inicio</th><th style="text-align:right">Fin</th></tr></thead>
  <tbody>${catRows}</tbody>
</table></div>
<h2>Por competición</h2>
<div class="section"><table>
  <thead><tr><th>Categoría</th><th>Competición</th><th>Fase / Grupo</th><th style="text-align:right">Partidos</th><th style="text-align:right">Finaliz.</th><th style="text-align:right">Pendien.</th><th>Pareja asignada</th><th style="text-align:right">Inicio</th><th style="text-align:right">Fin</th></tr></thead>
  <tbody>${compRows}</tbody>
</table></div>`;
}

let _dirty = false;
let _loaded = false;

export function markDirty() { _dirty = true; }

export async function load(season) {
  const panel = el();
  if (!panel) return;
  panel.innerHTML = `<div class="loading-row"><td><div class="spinner"></div></div></div>`;
  try {
    const data = await api.getStats(season);
    panel.innerHTML = _renderPanel(data);
    _dirty = false;
    _loaded = true;
  } catch(e) {
    panel.innerHTML = `<p style="color:#ef4444">Error cargando estadísticas: ${e.message}</p>`;
  }
}

export function init() {}
