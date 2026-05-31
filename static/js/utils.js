export const CAT_COLOR = { elite:"#7c3aed", honor:"#0ea5e9", primera:"#10b981", "?":"#64748b" };
export const CAT_LABEL = { elite:"Élite", honor:"Honor", primera:"1ª Div", "?":"—" };
export const CAT_RANK  = { elite:0, honor:1, primera:2, "?":3 };

export function seasonLabel(s) {
  return `${s.slice(0,2)}/${s.slice(2)}`;
}

export function formatDate(d) {
  if (!d) return "—";
  const [y, m, day] = d.split("-");
  return `${day}/${m}/${y}`;
}

export function genderFromCategoria(name) {
  const n = (name || "").toUpperCase();
  if (n.includes("FEMENIN")) return "F";
  if (n.includes("MASCULIN")) return "M";
  return "";
}

export function bestCat(catA, catB) {
  const a = catA || "?", b = catB || "?";
  return (CAT_RANK[a] ?? 9) <= (CAT_RANK[b] ?? 9) ? a : b;
}

export function pctBar(n, total) {
  if (!total) return "—";
  const p = Math.round(n / total * 100);
  const color = p >= 95 ? "#22c55e" : p >= 70 ? "#f59e0b" : "#ef4444";
  return `<div class="bar-wrap" title="${n}/${total}"><div class="bar" style="width:${p}%;background:${color}"></div><span>${p}%</span></div>`;
}

export function debounce(fn, ms = 300) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

export function spinner() {
  return `<tr class="loading-row"><td colspan="20"><div class="spinner"></div></td></tr>`;
}

export function renderPagination(total, page, perPage, onPage) {
  const pages = Math.ceil(total / perPage) || 1;
  if (pages <= 1) return "";
  const show = (p) => p >= 1 && p <= pages;
  const btns = [];
  const add = (p, label, active = false, disabled = false) => {
    btns.push(`<button ${disabled ? "disabled" : ""} ${active ? 'class="active-page"' : ""} data-p="${p}">${label}</button>`);
  };
  add(page - 1, "‹", false, page <= 1);
  const near = new Set([1, pages, page - 1, page, page + 1].filter(show));
  let prev = 0;
  [...near].sort((a,b)=>a-b).forEach(p => {
    if (p - prev > 1) btns.push(`<span class="page-info">…</span>`);
    add(p, p, p === page);
    prev = p;
  });
  add(page + 1, "›", false, page >= pages);
  const div = document.createElement("div");
  div.className = "pagination";
  div.innerHTML = btns.join("") + `<span class="page-info">Pág. ${page}/${pages} · ${total} total</span>`;
  div.querySelectorAll("button[data-p]").forEach(b => {
    b.addEventListener("click", () => onPage(+b.dataset.p));
  });
  return div;
}
