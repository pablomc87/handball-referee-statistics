const BASE = "/api";

async function _get(path, params = {}) {
  const url = new URL(BASE + path, location.origin);
  Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .forEach(([k, v]) => url.searchParams.set(k, v));
  const r = await fetch(url);
  if (!r.ok) throw new Error(`API ${r.status}: ${path}`);
  return r.json();
}

export const getSeasons      = ()       => _get("/seasons");
export const getStats        = (season) => _get("/stats", { season });
export const getCouples      = (p)      => _get("/couples", p);
export const getCoupleGames  = (a, b)   => _get("/couples/games", { ref_a: a, ref_b: b });
export const getGames        = (p)      => _get("/games", p);
export const getCompetitions = (season) => _get("/competitions", { season });
export const getReferees     = (p)      => _get("/referees", p);
export const getMovements    = (t)      => _get("/movements", { transition: t });
export const getTransitions  = ()       => _get("/movements/transitions");
export const getProgression  = (season) => _get(`/progression/${season}`);
