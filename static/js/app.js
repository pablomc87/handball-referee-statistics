import * as api   from "./api.js";
import * as state  from "./state.js";
import { seasonLabel } from "./utils.js";
import * as stats  from "./tabs/stats.js";
import * as couples from "./tabs/couples.js";
import * as games  from "./tabs/games.js";
import * as prog   from "./tabs/progression.js";
import * as moves  from "./tabs/movements.js";
import * as refs   from "./tabs/refs.js";

const el = (id) => document.getElementById(id);

function tabFromPath(pathname) {
  const name = pathname.replace(/^\//, "") || "stats";
  return name in TABS ? name : "stats";
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
const TABS = {
  stats:       { mod: stats,   seasonSensitive: true  },
  couples:     { mod: couples, seasonSensitive: true  },
  progression: { mod: prog,    seasonSensitive: true  },
  games:       { mod: games,   seasonSensitive: true  },
  moves:       { mod: moves,   seasonSensitive: true  },
  refs:        { mod: refs,    seasonSensitive: false },
};

let _activeTab = "stats";
const _dirty   = new Set(Object.keys(TABS));

function showTab(name, btn, { pushState = true } = {}) {
  if (!TABS[name]) name = "stats";
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  const panel = el(`tab-${name}`);
  if (panel) panel.classList.add("active");
  const tabBtn = btn || document.querySelector(`.tab-btn[data-tab="${name}"]`);
  if (tabBtn) tabBtn.classList.add("active");
  _activeTab = name;

  if (pushState) {
    const path = name === "stats" ? "/" : `/${name}`;
    if (location.pathname !== path) history.pushState({ tab: name }, "", path);
  }

  const tab = TABS[name];
  if (!tab) return;

  if (_dirty.has(name)) {
    _dirty.delete(name);
    if (tab.seasonSensitive) {
      tab.mod.load(state.getSeason());
    } else {
      tab.mod.load();
    }
  }
}

window.showTab = showTab;

document.querySelectorAll(".tab-btn[data-tab]").forEach(btn => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab, btn));
});

window.addEventListener("popstate", (e) => {
  const name = e.state?.tab || tabFromPath(location.pathname);
  showTab(name, null, { pushState: false });
});

// ── Season ────────────────────────────────────────────────────────────────────
function setSeason(s, btn) {
  state.setSeason(s);

  document.querySelectorAll(".season-btn.global-season").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");

  el("season-label").textContent = s === "all" ? "Todas las temporadas" : `Temporada ${seasonLabel(s)}`;

  // Mark all season-sensitive tabs dirty, reload the active one immediately
  Object.entries(TABS).forEach(([name, tab]) => {
    if (tab.seasonSensitive) _dirty.add(name);
  });

  const tab = TABS[_activeTab];
  if (tab?.seasonSensitive) {
    _dirty.delete(_activeTab);
    tab.mod.load(s);
  }
}

window.setSeason = setSeason;

// ── Bootstrap ─────────────────────────────────────────────────────────────────
async function main() {
  const seasons = await api.getSeasons();

  // Render season buttons
  const container = el("season-buttons");
  if (container) {
    seasons.forEach((s, i) => {
      const btn = document.createElement("button");
      btn.className = `season-btn global-season${i === 0 ? " active" : ""}`;
      btn.textContent = seasonLabel(s);
      btn.onclick = () => setSeason(s, btn);
      container.appendChild(btn);
    });
    const all = document.createElement("button");
    all.className = "season-btn global-season";
    all.textContent = "Todas";
    all.onclick = () => setSeason("all", all);
    container.appendChild(all);
  }

  // Init all tab DOM structures
  Object.values(TABS).forEach(tab => tab.mod.init());

  // Set initial season and load first tab
  const defaultSeason = seasons[0] || "all";
  state.setSeason(defaultSeason);
  el("season-label").textContent = `Temporada ${seasonLabel(defaultSeason)}`;

  // Activate tab from URL, defaulting to stats
  const initialTab = tabFromPath(location.pathname);
  showTab(initialTab, null, { pushState: false });
}

main().catch(console.error);
