"""All DB query and computation functions for the API layer."""
import sqlite3
from collections import defaultdict
from typing import Any

import config
from api.utils import gender_from_categoria, CAT_RANK, season_label, ALLOWED_COUPLE_SORT

# ── Helpers ───────────────────────────────────────────────────────────────────

_GOOD_DATE = "m.date IS NOT NULL AND m.date != '' AND m.date NOT LIKE '%RETIR%'"

# Base CTE for all couple-ranking queries.
# Canonical pair key: ref_a < ref_b alphabetically (order-independent dedup).
# All aggregate stats (games, scores, dates) are computed over the rows that
# survive {inner_where}, so callers can scope them to a season or gender by
# injecting filters there rather than post-filtering on derived columns.
_COUPLE_CTE = """
WITH base AS (
    SELECT
        -- Canonical alphabetical order so (A,B) and (B,A) collapse to the same row
        CASE WHEN r.referee_1 < r.referee_2 THEN r.referee_1 ELSE r.referee_2 END AS ref_a,
        CASE WHEN r.referee_1 < r.referee_2 THEN r.referee_2 ELSE r.referee_1 END AS ref_b,
        COUNT(*)                             AS games,
        ROUND(SUM(ns.nomination_score), 3)  AS total_score,
        ROUND(AVG(ns.nomination_score), 3)  AS avg_score,
        ROUND(MAX(ns.nomination_score), 3)  AS best_score,
        ROUND(AVG(ns.competition_mod), 3)   AS avg_comp_mod,
        ROUND(AVG(ns.match_quality), 3)     AS avg_quality,
        ROUND(AVG(ns.score_factor), 3)      AS avg_score_factor,
        MIN(m.date)                          AS first_game,
        MAX(m.date)                          AS last_game,
        -- Each referee's best catalog category (lowest rank = best: elite<honor<primera)
        CASE MIN(CASE rc_a.category WHEN 'elite' THEN 1 WHEN 'honor' THEN 2 WHEN 'primera' THEN 3 ELSE 4 END)
            WHEN 1 THEN 'elite' WHEN 2 THEN 'honor' WHEN 3 THEN 'primera' ELSE '?' END AS cat_a,
        CASE MIN(CASE rc_b.category WHEN 'elite' THEN 1 WHEN 'honor' THEN 2 WHEN 'primera' THEN 3 ELSE 4 END)
            WHEN 1 THEN 'elite' WHEN 2 THEN 'honor' WHEN 3 THEN 'primera' ELSE '?' END AS cat_b,
        -- best_cat: better of the two referees' best categories (SQLite has no LEAST, use CASE)
        CASE WHEN
            MIN(CASE rc_a.category WHEN 'elite' THEN 1 WHEN 'honor' THEN 2 WHEN 'primera' THEN 3 ELSE 4 END)
            <=
            MIN(CASE rc_b.category WHEN 'elite' THEN 1 WHEN 'honor' THEN 2 WHEN 'primera' THEN 3 ELSE 4 END)
        THEN CASE MIN(CASE rc_a.category WHEN 'elite' THEN 1 WHEN 'honor' THEN 2 WHEN 'primera' THEN 3 ELSE 4 END)
                 WHEN 1 THEN 'elite' WHEN 2 THEN 'honor' WHEN 3 THEN 'primera' ELSE '?' END
        ELSE CASE MIN(CASE rc_b.category WHEN 'elite' THEN 1 WHEN 'honor' THEN 2 WHEN 'primera' THEN 3 ELSE 4 END)
                 WHEN 1 THEN 'elite' WHEN 2 THEN 'honor' WHEN 3 THEN 'primera' ELSE '?' END
        END AS best_cat
    FROM referees r
    JOIN matches m   ON m.match_id  = r.match_id
    JOIN torneos t   ON t.torneo_id = m.torneo_id
    -- Use referee_1's nomination row as the per-match score (both refs share the same score)
    JOIN nomination_scores ns
        ON ns.match_id = r.match_id AND ns.referee_name = r.referee_1
    -- referee_2's row is only needed to resolve their catalog category
    LEFT JOIN nomination_scores ns2
        ON ns2.match_id = r.match_id AND ns2.referee_name = r.referee_2
    LEFT JOIN referees_catalog rc_a ON rc_a.id = ns.catalog_id
    LEFT JOIN referees_catalog rc_b ON rc_b.id = ns2.catalog_id
    WHERE r.referee_1 != '' AND r.referee_2 != ''
      AND r.referee_1 IS NOT NULL AND r.referee_2 IS NOT NULL
      {inner_where}
    GROUP BY ref_a, ref_b
)
"""


def _row(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict:
    return dict(conn.execute(sql, params).fetchone())


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ── Seasons ───────────────────────────────────────────────────────────────────

def get_seasons(conn: sqlite3.Connection) -> list[str]:
    # Return only seasons that have torneos in the DB, ordered by config.CATALOG_SEASONS
    # so the UI always presents them newest-first regardless of insertion order.
    rows = conn.execute("SELECT DISTINCT season_id FROM torneos").fetchall()
    have = {r[0] for r in rows}
    return [s for s in config.CATALOG_SEASONS if s in have]


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats(conn: sqlite3.Connection, season: str | None) -> dict:
    """Return three summary views (overall, per-category, per-competition) for the stats tab."""
    sf = f"AND t.season_id='{season}'" if season and season != "all" else ""

    # Single-row summary: totals and date range for the whole season
    overall = _row(conn, f"""
        SELECT
            COUNT(*) AS total_matches,
            SUM(CASE WHEN r.referee_1 != '' AND r.referee_2 != '' THEN 1 ELSE 0 END) AS with_refs,
            SUM(CASE WHEN m.status='Finalizado' THEN 1 ELSE 0 END) AS finalizado,
            SUM(CASE WHEN m.status='Pendiente'  THEN 1 ELSE 0 END) AS pendiente,
            MIN(CASE WHEN {_GOOD_DATE} THEN m.date END) AS min_date,
            MAX(CASE WHEN {_GOOD_DATE} THEN m.date END) AS max_date
        FROM matches m
        JOIN torneos t ON t.torneo_id = m.torneo_id
        LEFT JOIN referees r ON r.match_id = m.match_id
        WHERE 1=1 {sf}
    """)

    # One row per categoria_name (e.g. División de Honor Masculina), sorted by volume
    by_category = _rows(conn, f"""
        SELECT t.categoria_name,
            COUNT(*) AS matches,
            SUM(CASE WHEN r.referee_1 IS NOT NULL AND r.referee_1 != ''
                          AND r.referee_2 IS NOT NULL AND r.referee_2 != ''
                     THEN 1 ELSE 0 END) AS with_refs,
            SUM(CASE WHEN m.status='Finalizado' THEN 1 ELSE 0 END) AS finalizado,
            SUM(CASE WHEN m.status='Pendiente'  THEN 1 ELSE 0 END) AS pendiente,
            MIN(CASE WHEN {_GOOD_DATE} THEN m.date END) AS min_date,
            MAX(CASE WHEN {_GOOD_DATE} THEN m.date END) AS max_date
        FROM matches m
        JOIN torneos t ON t.torneo_id = m.torneo_id
        LEFT JOIN referees r ON r.match_id = m.match_id
        WHERE 1=1 {sf}
        GROUP BY t.categoria_name ORDER BY matches DESC
    """)

    # One row per (categoria, competicion, torneo) triplet — most granular breakdown
    by_competition = _rows(conn, f"""
        SELECT t.categoria_name, t.competicion_name, t.torneo_name,
            COUNT(*) AS matches,
            SUM(CASE WHEN r.referee_1 IS NOT NULL AND r.referee_1 != ''
                          AND r.referee_2 IS NOT NULL AND r.referee_2 != ''
                     THEN 1 ELSE 0 END) AS with_refs,
            SUM(CASE WHEN m.status='Finalizado' THEN 1 ELSE 0 END) AS finalizado,
            SUM(CASE WHEN m.status='Pendiente'  THEN 1 ELSE 0 END) AS pendiente,
            MIN(CASE WHEN {_GOOD_DATE} THEN m.date END) AS min_date,
            MAX(CASE WHEN {_GOOD_DATE} THEN m.date END) AS max_date
        FROM matches m
        JOIN torneos t ON t.torneo_id = m.torneo_id
        LEFT JOIN referees r ON r.match_id = m.match_id
        WHERE 1=1 {sf}
        GROUP BY t.categoria_name, t.competicion_name, t.torneo_name
        ORDER BY t.categoria_name, t.competicion_name, t.torneo_name
    """)

    return {"overall": overall, "by_category": by_category, "by_competition": by_competition}


# ── Couples ───────────────────────────────────────────────────────────────────

def get_couples(
    conn: sqlite3.Connection,
    season: str,
    cats: list[str],
    gender: str | None,
    min_games: int,
    name: str | None,
    sort_by: str,
    sort_dir: str,
    page: int,
    per_page: int,
) -> dict:
    """
    Paginated couple ranking.
    Season and gender filters are pushed into the CTE's inner WHERE so every
    stat (games, avg_score, dates…) reflects only the matching games.
    Category and name filters are applied in the outer SELECT against the
    aggregated result, since they don't affect which games count.
    """
    inner_where_parts = []
    inner_params: list[Any] = []

    if season and season != "all":
        inner_where_parts.append("t.season_id = ?")
        inner_params.append(season)

    # Gender filter goes inside the CTE so every stat (games, scores, dates)
    # reflects only games of the selected gender.
    if gender == "F":
        inner_where_parts.append("t.categoria_name LIKE '%FEMENIN%'")
    elif gender == "M":
        inner_where_parts.append("(t.categoria_name NOT LIKE '%FEMENIN%' AND t.categoria_name LIKE '%MASCULIN%')")

    inner_where = ("AND " + " AND ".join(inner_where_parts)) if inner_where_parts else ""
    cte = _COUPLE_CTE.format(inner_where=inner_where)

    outer_parts = ["games >= ?"]
    outer_params: list[Any] = [min_games]

    if cats:
        placeholders = ",".join("?" * len(cats))
        outer_parts.append(f"best_cat IN ({placeholders})")
        outer_params.extend(cats)
    if name:
        outer_parts.append("(LOWER(ref_a) LIKE ? OR LOWER(ref_b) LIKE ?)")
        pat = f"%{name.lower()}%"
        outer_params.extend([pat, pat])

    outer_where = " AND ".join(outer_parts)

    sort_col = sort_by if sort_by in ALLOWED_COUPLE_SORT else "avg_score"
    sort_sql  = "DESC" if sort_dir.lower() != "asc" else "ASC"

    all_params = tuple(inner_params + outer_params)
    count = conn.execute(
        cte + f"SELECT COUNT(*) FROM base WHERE {outer_where}", all_params
    ).fetchone()[0]

    items = _rows(conn,
        cte + f"""
        SELECT * FROM base WHERE {outer_where}
        ORDER BY {sort_col} {sort_sql}
        LIMIT ? OFFSET ?
        """,
        all_params + (per_page, (page - 1) * per_page),
    )

    return {"total": count, "page": page, "per_page": per_page, "items": items}


def get_couple_games(conn: sqlite3.Connection, ref_a: str, ref_b: str) -> list[dict]:
    """All games for a referee pair, newest first. Used for the couple detail modal."""
    # The referees table stores pairs in insertion order, not canonical alphabetical order,
    # so we must match both (A, B) and (B, A) to avoid missing games.
    return _rows(conn, """
        SELECT m.match_id, m.date, t.season_id, m.home_team, m.away_team,
            m.score_home, m.score_away,
            t.categoria_name, t.competicion_name, t.torneo_name,
            CASE WHEN t.categoria_name LIKE '%FEMENIN%' THEN 'F'
                 WHEN t.categoria_name LIKE '%MASCULIN%' THEN 'M'
                 ELSE '' END AS gender,
            ns.competition_mod, ns.match_quality, ns.score_factor, ns.nomination_score,
            ns.rank_home, ns.rank_away, ns.n_teams
        FROM referees r
        JOIN matches m   ON m.match_id  = r.match_id
        JOIN torneos t   ON t.torneo_id = m.torneo_id
        JOIN nomination_scores ns ON ns.match_id = r.match_id AND ns.referee_name = r.referee_1
        WHERE (UPPER(r.referee_1) = UPPER(?) AND UPPER(r.referee_2) = UPPER(?))
           OR (UPPER(r.referee_1) = UPPER(?) AND UPPER(r.referee_2) = UPPER(?))
        ORDER BY m.date DESC, m.match_id DESC
    """, (ref_a, ref_b, ref_b, ref_a))


# ── Games ─────────────────────────────────────────────────────────────────────

def get_games(
    conn: sqlite3.Connection,
    season: str | None,
    date_from: str | None,
    date_to: str | None,
    competition: str | None,
    phase: str | None,
    home: str | None,
    away: str | None,
    ref: str | None,
    gender: str | None,
    page: int,
    per_page: int,
) -> dict:
    """
    Paginated game list with optional filters.
    All text filters use LIKE with wildcards so partial matches work.
    Gender is handled by adding a LIKE condition on categoria_name directly
    instead of a subquery, since all categoria values are consistently named.
    """
    parts = [_GOOD_DATE]
    params: list[Any] = []

    if season and season != "all":
        parts.append("t.season_id = ?")
        params.append(season)
    if date_from:
        parts.append("m.date >= ?")
        params.append(date_from)
    if date_to:
        parts.append("m.date <= ?")
        params.append(date_to)
    if competition:
        parts.append("LOWER(t.competicion_name) LIKE ?")
        params.append(f"%{competition.lower()}%")
    if phase:
        parts.append("LOWER(t.torneo_name) LIKE ?")
        params.append(f"%{phase.lower()}%")
    if home:
        parts.append("LOWER(m.home_team) LIKE ?")
        params.append(f"%{home.lower()}%")
    if away:
        parts.append("LOWER(m.away_team) LIKE ?")
        params.append(f"%{away.lower()}%")
    if ref:
        parts.append("(LOWER(r.referee_1) LIKE ? OR LOWER(r.referee_2) LIKE ?)")
        pat = f"%{ref.lower()}%"
        params.extend([pat, pat])

    base_sql = f"""
        FROM matches m
        JOIN torneos t ON t.torneo_id = m.torneo_id
        LEFT JOIN referees r ON r.match_id = m.match_id
        LEFT JOIN nomination_scores ns
            ON ns.match_id = m.match_id AND ns.referee_name = r.referee_1
        WHERE {' AND '.join(parts)}
    """

    if gender:
        filt = "t.categoria_name LIKE '%FEMENIN%'" if gender == "F" else "(t.categoria_name NOT LIKE '%FEMENIN%' AND t.categoria_name LIKE '%MASCULIN%')"
        parts.append(filt)
        base_sql = f"""
            FROM matches m
            JOIN torneos t ON t.torneo_id = m.torneo_id
            LEFT JOIN referees r ON r.match_id = m.match_id
            LEFT JOIN nomination_scores ns
                ON ns.match_id = m.match_id AND ns.referee_name = r.referee_1
            WHERE {' AND '.join(parts)}
        """

    select_cols = """
        m.match_id, m.date, t.season_id, m.home_team, m.away_team,
        m.score_home, m.score_away, m.status,
        t.categoria_name, t.competicion_name, t.torneo_name,
        CASE WHEN t.categoria_name LIKE '%FEMENIN%' THEN 'F'
             WHEN t.categoria_name LIKE '%MASCULIN%' THEN 'M'
             ELSE '' END AS gender,
        COALESCE(r.referee_1, '')           AS referee_1,
        COALESCE(r.referee_2, '')           AS referee_2,
        COALESCE(ns.competition_mod, 0)     AS competition_mod,
        COALESCE(ns.match_quality, 0)       AS match_quality,
        COALESCE(ns.score_factor, 0)        AS score_factor,
        COALESCE(ns.nomination_score, 0)    AS nomination_score
    """

    count = conn.execute(f"SELECT COUNT(*) {base_sql}", params).fetchone()[0]
    items = _rows(conn, f"""
        SELECT {select_cols}
        {base_sql}
        ORDER BY m.date DESC, m.match_id DESC
        LIMIT ? OFFSET ?
    """, params + [per_page, (page - 1) * per_page])

    return {"total": count, "page": page, "per_page": per_page, "items": items}


def get_competitions(conn: sqlite3.Connection, season: str | None) -> list[dict]:
    """Return distinct (competicion_name, torneo_name) pairs to populate the games filter dropdowns."""
    sf = "AND season_id = ?" if season and season != "all" else ""
    params = (season,) if sf else ()
    return _rows(conn, f"""
        SELECT DISTINCT competicion_name, torneo_name FROM torneos
        WHERE 1=1 {sf} ORDER BY competicion_name, torneo_name
    """, params)


# ── Referees ──────────────────────────────────────────────────────────────────

def _nm_cross(s: str) -> str:
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", s)
    flat = nfkd.encode("ascii", "ignore").decode("ascii").replace("-", " ")
    return " ".join(sorted(flat.lower().split()))


def _canonical_name(raw: str) -> str:
    import unicodedata
    raw = raw.strip()
    if "," in raw:
        surnames, given = raw.split(",", 1)
        raw = f"{given.strip()} {surnames.strip()}"
    return unicodedata.normalize("NFC", raw).title()


def build_referee_identities(conn: sqlite3.Connection) -> list[dict]:
    """
    Build a cross-season identity list: one entry per logical referee, merging
    name variants across seasons via fuzzy matching (RapidFuzz token_sort_ratio).
    Manual aliases in config.MANUAL_CROSS_ALIASES take priority over fuzzy matching.
    The most recent season's raw_name and category are used as the canonical values.
    """
    from rapidfuzz import process, fuzz

    aliases = {_nm_cross(k): _nm_cross(v) for k, v in config.MANUAL_CROSS_ALIASES.items()}

    def _alias(ts: str) -> str:
        return aliases.get(ts, ts)

    all_entries = _rows(conn, "SELECT season_id, normalized, category, raw_name, gender, gender_confidence FROM referees_catalog")
    by_season: dict = defaultdict(dict)
    for r in all_entries:
        by_season[r["season_id"]][r["normalized"]] = {
            "category": r["category"], "raw_name": r["raw_name"],
            "gender": r["gender"] or "", "gender_confidence": r["gender_confidence"] or 0.0,
        }

    available = sorted(by_season.keys(), reverse=True)
    identities: dict = {}

    for season_id in available:
        for norm, entry in by_season[season_id].items():
            ts = _alias(_nm_cross(norm))
            if ts in identities:
                identities[ts]["seasons"][season_id] = entry
                continue
            hit = None
            if identities:
                cands = list(identities.keys())
                h = process.extractOne(ts, cands, scorer=fuzz.token_sort_ratio, score_cutoff=85)
                if not h:
                    h2 = process.extractOne(ts, cands, scorer=fuzz.token_set_ratio, score_cutoff=90)
                    if h2 and fuzz.token_sort_ratio(ts, h2[0]) >= 75:
                        h = h2
                if h:
                    hit = h[0]
            if hit:
                identities[hit]["seasons"][season_id] = entry
            else:
                identities[ts] = {
                    "canonical": _canonical_name(entry["raw_name"]),
                    "category":  entry["category"],
                    "canonical_ts": ts,
                    "seasons":   {season_id: entry},
                }

    result = []
    for ts, ident in identities.items():
        seasons = ident["seasons"]
        for s in available:
            if s in seasons:
                ident["canonical"] = _canonical_name(seasons[s]["raw_name"])
                ident["category"]  = seasons[s]["category"]
                break
        variants = {s: v["raw_name"] for s, v in seasons.items() if v["raw_name"] != ident["canonical"]}
        ident["variants"]     = variants
        ident["has_variants"] = bool(variants)
        ident["season_ids"]   = sorted(seasons.keys(), reverse=True)
        # Gender: use the detection with the highest confidence across all seasons
        best_g, best_conf = "", 0.0
        for entry in seasons.values():
            g, c = entry.get("gender", ""), entry.get("gender_confidence", 0.0)
            if g and c > best_conf:
                best_g, best_conf = g, c
        ident["gender"] = best_g
        ident["gender_confidence"] = round(best_conf, 2)
        result.append(ident)

    return sorted(result, key=lambda r: r["canonical"].lower())


# ── Movements ─────────────────────────────────────────────────────────────────

def _cross_match(new_entries: dict, old_entries: dict) -> tuple:
    from rapidfuzz import process, fuzz

    aliases = {_nm_cross(k): _nm_cross(v) for k, v in config.MANUAL_CROSS_ALIASES.items()}

    def _alias(ts: str) -> str:
        return aliases.get(ts, ts)

    old_ts = {_alias(_nm_cross(n)): n for n in old_entries}
    pairs, matched_old, only_new = [], set(), []

    for norm_new in new_entries:
        query = _alias(_nm_cross(norm_new))
        if query in old_ts:
            norm_old = old_ts[query]
            pairs.append((norm_new, norm_old))
            matched_old.add(norm_old)
            continue
        candidates = list(old_ts.keys())
        hit = process.extractOne(query, candidates, scorer=fuzz.token_sort_ratio, score_cutoff=85)
        if not hit:
            h2 = process.extractOne(query, candidates, scorer=fuzz.token_set_ratio, score_cutoff=90)
            if h2 and fuzz.token_sort_ratio(query, h2[0]) >= 75:
                hit = h2
        if hit:
            norm_old = old_ts[hit[0]]
            if norm_old not in matched_old:
                pairs.append((norm_new, norm_old))
                matched_old.add(norm_old)
            else:
                only_new.append(norm_new)
        else:
            only_new.append(norm_new)

    only_old = [n for n in old_entries if n not in matched_old]
    return pairs, only_new, only_old


_CAT_TO_LEVEL = {"elite": 3, "honor": 2, "primera": 1}


def build_referee_movements(conn: sqlite3.Connection, identities: list[dict] | None = None) -> dict:
    """
    Compute promotion/demotion/arrival/departure events between consecutive seasons.
    For each adjacent season pair (old → new), cross-matches referees by fuzzy name,
    then classifies each as: 'up' (promoted), 'down' (demoted), 'new' (first season),
    or 'gone' (no longer in catalog). Nomination stats from the old season are
    included to show what performance preceded each movement.
    """
    import name_matcher as nm_mod

    all_entries = _rows(conn, "SELECT season_id, normalized, category, raw_name FROM referees_catalog")
    by_season: dict = defaultdict(dict)
    for r in all_entries:
        by_season[r["season_id"]][r["normalized"]] = {"category": r["category"], "raw_name": r["raw_name"]}

    # Build canonical name lookup so movement names match the árbitros tab exactly.
    if identities is None:
        identities = build_referee_identities(conn)
    _aliases_map = {_nm_cross(k): _nm_cross(v) for k, v in config.MANUAL_CROSS_ALIASES.items()}
    _canonical_map = {ident["canonical_ts"]: ident["canonical"] for ident in identities}

    def _resolve_name(norm: str, raw: str) -> str:
        ts = _aliases_map.get(_nm_cross(norm), _nm_cross(norm))
        return _canonical_map.get(ts) or _canonical_name(raw)

    available = sorted(by_season.keys(), reverse=True)

    # Pre-aggregate nomination stats per (referee, season) so they can be
    # attached to each movement row without extra per-row queries.
    nom_rows = _rows(conn, """
        SELECT ns.referee_name, t.season_id,
               COUNT(*) AS noms, ROUND(SUM(ns.nomination_score),3) AS score
        FROM nomination_scores ns
        JOIN matches m ON m.match_id=ns.match_id
        JOIN torneos t ON t.torneo_id=m.torneo_id
        GROUP BY ns.referee_name, t.season_id
    """)
    nom_stats: dict = defaultdict(lambda: defaultdict(lambda: {"noms": 0, "score": 0.0}))
    for r in nom_rows:
        s = nom_stats[r["referee_name"]][r["season_id"]]
        s["noms"]  += r["noms"]
        s["score"] += r["score"]
    seasons_with_data: set = {r["season_id"] for r in nom_rows}

    name_maps: dict = {}
    for sid in seasons_with_data:
        if sid in by_season:
            name_maps[sid] = nm_mod.build_name_map(season_id=sid)

    cat_ranks: dict = {}
    for sid, nm in name_maps.items():
        ranked = _rows(conn, f"""
            SELECT ns.referee_name, ROUND(AVG(ns.nomination_score),3) AS ts
            FROM nomination_scores ns
            JOIN matches m ON m.match_id=ns.match_id
            JOIN torneos t ON t.torneo_id=m.torneo_id
            WHERE t.season_id='{sid}'
            GROUP BY ns.referee_name ORDER BY ts DESC
        """)
        grouped: dict = defaultdict(list)
        for r in ranked:
            entry = nm.get(r["referee_name"])
            cat = entry["category"] if entry else "?"
            grouped[cat].append(r["referee_name"])
        season_ranks = {}
        for cat, names in grouped.items():
            for i, name in enumerate(names):
                season_ranks[name] = (i + 1, len(names), cat)
        cat_ranks[sid] = season_ranks

    def _scraper_stats(norm: str, sid: str):
        nm = name_maps.get(sid, {})
        for scraper_name, entry in nm.items():
            if entry and entry.get("normalized") == norm:
                return cat_ranks.get(sid, {}).get(scraper_name), nom_stats[scraper_name][sid]
        return None, {"noms": 0, "score": 0.0}

    def _rank_str(ri):
        return f"{ri[0]}/{ri[1]}" if ri else "—"

    result: dict = {}
    for i in range(len(available) - 1):
        s_new = available[i]
        s_old = available[i + 1]
        key = f"{s_old}-{s_new}"

        cat_new = by_season[s_new]
        cat_old = by_season[s_old]
        pairs, only_new, only_old = _cross_match(cat_new, cat_old)

        rows: list[dict] = []

        for norm_n, norm_o in pairs:
            cn, co = cat_new[norm_n]["category"], cat_old[norm_o]["category"]
            if cn == co:
                continue
            ln, lo = _CAT_TO_LEVEL.get(cn, 0), _CAT_TO_LEVEL.get(co, 0)
            if not ln or not lo:
                continue
            ri_o, nom_o = _scraper_stats(norm_o, s_old)
            _, nom_n    = _scraper_stats(norm_n, s_new)
            rows.append({
                "move_type": "up" if ln > lo else "down",
                "name": _resolve_name(norm_n, cat_new[norm_n]["raw_name"]),
                "cat_old": co, "cat_new": cn, "lvl_old": lo, "lvl_new": ln,
                "noms_old":  nom_o["noms"]  if s_old in seasons_with_data else None,
                "score_old": round(nom_o["score"], 3) if s_old in seasons_with_data else None,
                "noms_new":  nom_n["noms"]  if s_new in seasons_with_data else None,
                "score_new": round(nom_n["score"], 3) if s_new in seasons_with_data else None,
                "rank_str":  _rank_str(ri_o),  # rank in old season — what earned the move
            })

        for norm_n in only_new:
            cn = cat_new[norm_n]["category"]
            ln = _CAT_TO_LEVEL.get(cn, 0)
            ri_n, nom_n = _scraper_stats(norm_n, s_new)
            rows.append({
                "move_type": "new", "name": _resolve_name(norm_n, cat_new[norm_n]["raw_name"]),
                "cat_old": None, "cat_new": cn, "lvl_old": 0, "lvl_new": ln,
                "noms_old": None, "score_old": None,
                "noms_new":  nom_n["noms"]  if s_new in seasons_with_data else None,
                "score_new": round(nom_n["score"], 3) if s_new in seasons_with_data else None,
                "rank_str":  _rank_str(ri_n),
            })

        for norm_o in only_old:
            co = cat_old[norm_o]["category"]
            lo = _CAT_TO_LEVEL.get(co, 0)
            ri_o, nom_o = _scraper_stats(norm_o, s_old)
            rows.append({
                "move_type": "gone", "name": _resolve_name(norm_o, cat_old[norm_o]["raw_name"]),
                "cat_old": co, "cat_new": None, "lvl_old": lo, "lvl_new": 0,
                "noms_old":  nom_o["noms"]  if s_old in seasons_with_data else None,
                "score_old": round(nom_o["score"], 3) if s_old in seasons_with_data else None,
                "noms_new": None, "score_new": None,
                "rank_str":  _rank_str(ri_o) if s_old in seasons_with_data else "—",
            })

        type_order = {"up": 0, "down": 1, "new": 2, "gone": 3}
        rows.sort(key=lambda r: (type_order[r["move_type"]], -(r["lvl_new"] or r["lvl_old"]),
                                 -(r["score_new"] or r["score_old"] or 0)))
        result[key] = rows

    return result


# ── Progression ───────────────────────────────────────────────────────────────

def build_progression(conn: sqlite3.Connection, season_id: str, gender: str | None = None) -> dict:
    """
    Build per-couple cumulative-average-score progression for a season.
    Couples are grouped by category; within each group the ranking is re-computed
    after every game date so the chart shows rank movement over time.
    If gender is given ('M' or 'F'), only games of that gender are counted and
    only couples with at least one such game appear — same approach as get_couples().
    Only emits a data point when a couple plays or their rank changes, to keep
    the payload small. The final point is always the season-end date/rank.
    """
    import name_matcher

    name_map = name_matcher.build_name_map(season_id=season_id)

    gender_filter = ""
    if gender == "F":
        gender_filter = "AND t.categoria_name LIKE '%FEMENIN%'"
    elif gender == "M":
        gender_filter = "AND t.categoria_name NOT LIKE '%FEMENIN%' AND t.categoria_name LIKE '%MASCULIN%'"

    rows = _rows(conn, f"""
        SELECT
            CASE WHEN r.referee_1 < r.referee_2 THEN r.referee_1 ELSE r.referee_2 END AS ref_a,
            CASE WHEN r.referee_1 < r.referee_2 THEN r.referee_2 ELSE r.referee_1 END AS ref_b,
            r.referee_1, r.referee_2,
            m.date, t.categoria_name, ns.nomination_score
        FROM referees r
        JOIN matches m   ON m.match_id  = r.match_id
        JOIN torneos t   ON t.torneo_id = m.torneo_id
        JOIN nomination_scores ns ON ns.match_id = r.match_id AND ns.referee_name = r.referee_1
        WHERE r.referee_1 != '' AND r.referee_2 != ''
          AND r.referee_1 IS NOT NULL AND r.referee_2 IS NOT NULL
          AND t.season_id = '{season_id}'
          {gender_filter}
        ORDER BY m.date ASC
    """)

    couple_games: dict = defaultdict(list)
    couple_cats:  dict = {}

    for row in rows:
        ck = (row["ref_a"], row["ref_b"])
        couple_games[ck].append({"date": row["date"], "score": row["nomination_score"] or 0})
        if ck not in couple_cats:
            e1 = name_map.get(row["referee_1"])
            e2 = name_map.get(row["referee_2"])
            if e1 and e2:
                cat = e1["category"] if CAT_RANK.get(e1["category"], 9) <= CAT_RANK.get(e2["category"], 9) else e2["category"]
            elif e1:
                cat = e1["category"]
            elif e2:
                cat = e2["category"]
            else:
                cat = None
            couple_cats[ck] = cat

    def _valid_date(d: str) -> bool:
        return bool(d and len(d) == 10 and d[4] == "-")

    # Group by category only — gender filtering was already done in the SQL query
    groups: dict = defaultdict(list)
    for c in couple_games:
        cat = couple_cats.get(c)
        if cat:
            groups[cat].append(c)

    result: dict = {}

    for cat, category_couples in groups.items():
        all_dates = sorted({g["date"] for c in category_couples for g in couple_games[c] if _valid_date(g["date"])})
        if not all_dates:
            continue

        cum_at: dict = {}
        for c in category_couples:
            by_date: dict = {}
            total = n = 0.0
            for g in couple_games[c]:
                d = g["date"]
                if not _valid_date(d):
                    continue
                total += g["score"]
                n += 1
                by_date[d] = (round(total, 6), n)
            last = None
            carry: dict = {}
            for d in all_dates:
                if d in by_date:
                    last = by_date[d]
                carry[d] = last
            cum_at[c] = carry

        end_date = all_dates[-1]

        for ck in category_couples:
            played = {g["date"] for g in couple_games[ck] if _valid_date(g["date"])}
            progression = []
            prev_rank = None

            for d in all_dates:
                my = cum_at[ck][d]
                if my is None:
                    continue
                my_total, my_n = my
                my_avg = my_total / my_n
                ranking = []
                for c in category_couples:
                    cd = cum_at[c][d]
                    if cd is None:
                        continue
                    ct, cn_ = cd
                    ranking.append((ct / cn_, ct, c))
                ranking.sort(key=lambda x: (-x[0], -x[1], x[2]))
                rank = next((idx + 1 for idx, (_, _, c) in enumerate(ranking) if c == ck), 1)
                if rank != prev_rank or d in played:
                    progression.append({"date": d, "rank": rank, "avg": round(my_avg, 4)})
                    prev_rank = rank

            if not progression:
                continue

            se_ranking = []
            for c in category_couples:
                cd = cum_at[c][end_date]
                if cd is None:
                    continue
                ct, cn_ = cd
                se_ranking.append((ct / cn_, ct, c))
            se_ranking.sort(key=lambda x: (-x[0], -x[1], x[2]))
            season_end_rank = next((idx + 1 for idx, (_, _, c) in enumerate(se_ranking) if c == ck), None)

            if progression[-1]["date"] != end_date:
                my_end = cum_at[ck][end_date]
                end_avg = round(my_end[0] / my_end[1], 4) if my_end else 0
                progression.append({"date": end_date, "rank": season_end_rank, "avg": end_avg})

            last_game_date = max((g["date"] for g in couple_games[ck] if _valid_date(g["date"])), default=end_date)

            couple_key = f"{ck[0]}|||{ck[1]}"
            result[couple_key] = {
                "ref_a":    ck[0], "ref_b": ck[1],
                "category": cat,
                "games":    len(played),
                "progression":    progression,
                "season_end":     end_date,
                "season_end_rank": season_end_rank,
                "last_game_date": last_game_date,
            }

    return result
