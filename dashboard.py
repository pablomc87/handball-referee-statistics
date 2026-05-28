"""Generate output/dashboard.html from handball.db."""

import json
import sqlite3
from itertools import groupby
from pathlib import Path

import config
import db


def _conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _query(sql, params=()):
    with _conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def build_couple_rankings():
    rows = _query("""
        SELECT
            CASE WHEN r.referee_1 < r.referee_2
                 THEN r.referee_1 ELSE r.referee_2 END AS ref_a,
            CASE WHEN r.referee_1 < r.referee_2
                 THEN r.referee_2 ELSE r.referee_1 END AS ref_b,
            COUNT(*)                              AS games,
            ROUND(SUM(ns1.nomination_score), 3)  AS total_score,
            ROUND(AVG(ns1.nomination_score), 3)  AS avg_score,
            ROUND(MAX(ns1.nomination_score), 3)  AS best_score,
            ROUND(AVG(ns1.competition_mod), 3)   AS avg_comp_mod,
            ROUND(AVG(ns1.match_quality),  3)    AS avg_quality,
            ROUND(AVG(ns1.score_factor),   3)    AS avg_score_factor,
            MIN(m.date)                           AS first_game,
            MAX(m.date)                           AS last_game,
            COALESCE(rc_a.category, '?')          AS cat_a,
            COALESCE(rc_b.category, '?')          AS cat_b,
            MIN(tr.categoria_name)                AS categoria_name
        FROM referees r
        JOIN matches m ON m.match_id = r.match_id
        JOIN torneos tr ON tr.torneo_id = m.torneo_id
        JOIN nomination_scores ns1
            ON ns1.match_id = r.match_id AND ns1.referee_name = r.referee_1
        LEFT JOIN nomination_scores ns2
            ON ns2.match_id = r.match_id AND ns2.referee_name = r.referee_2
        LEFT JOIN referees_catalog rc_a ON rc_a.id = ns1.catalog_id
        LEFT JOIN referees_catalog rc_b ON rc_b.id = ns2.catalog_id
        WHERE r.referee_1 != '' AND r.referee_2 != ''
          AND r.referee_1 IS NOT NULL AND r.referee_2 IS NOT NULL
        GROUP BY ref_a, ref_b
        ORDER BY avg_score DESC
    """)
    # Add gender extracted from categoria_name
    for row in rows:
        row["gender"] = _gender_from_categoria(row.get("categoria_name", ""))
    return rows


def build_couple_progression_by_season():
    """
    For each season, compute couple ranking progression.
    Returns {season_id: {(ref_a, ref_b): {category, gender, games, progression: [{date, rank}, ...]}}}
    """
    from collections import defaultdict

    result = {}

    import name_matcher

    for season_id in [config.SEASON_ID, config.PREV_SEASON_ID]:
        # Build name→catalog map for THIS season's PDFs specifically
        name_map = name_matcher.build_name_map(season_id=season_id)

        rows = _query(f"""
            SELECT
                CASE WHEN r.referee_1 < r.referee_2 THEN r.referee_1 ELSE r.referee_2 END AS ref_a,
                CASE WHEN r.referee_1 < r.referee_2 THEN r.referee_2 ELSE r.referee_1 END AS ref_b,
                r.referee_1, r.referee_2,
                m.date, t.categoria_name,
                ns.nomination_score
            FROM referees r
            JOIN matches m ON m.match_id = r.match_id
            JOIN torneos t ON t.torneo_id = m.torneo_id
            JOIN nomination_scores ns ON ns.match_id = r.match_id AND ns.referee_name = r.referee_1
            WHERE r.referee_1 != '' AND r.referee_2 != ''
              AND r.referee_1 IS NOT NULL AND r.referee_2 IS NOT NULL
              AND t.season_id = '{season_id}'
            ORDER BY m.date ASC
        """)

        from collections import defaultdict as _dd
        couple_games: dict = _dd(list)
        couple_cats = {}   # PDF catalog category per couple; None = not in PDF
        couple_genders = {}

        for row in rows:
            couple_key = (row['ref_a'], row['ref_b'])
            couple_games[couple_key].append({
                'date': row['date'],
                'score': row['nomination_score'] or 0,
            })
            if couple_key not in couple_cats:
                entry = name_map.get(row['referee_1']) or name_map.get(row['referee_2'])
                couple_cats[couple_key] = entry['category'] if entry else None
                couple_genders[couple_key] = _gender_from_categoria(row['categoria_name'])

        def _valid_date(d):
            return d and len(d) == 10 and d[4] == '-'

        # Group by PDF category + gender (authoritative from plantillas)
        groups: dict = _dd(list)
        for c in couple_games:
            cat = couple_cats.get(c)
            if cat:
                groups[(cat, couple_genders.get(c, ''))].append(c)

        season_result = {}

        for (cat, gen), category_couples in groups.items():
            all_group_dates = sorted({
                g['date'] for c in category_couples for g in couple_games[c]
                if _valid_date(g['date'])
            })
            if not all_group_dates:
                continue

            cum_at: dict = {}
            for c in category_couples:
                by_date: dict = {}
                total, n = 0.0, 0
                for g in couple_games[c]:
                    d = g['date']
                    if not _valid_date(d):
                        continue
                    total += g['score']
                    n += 1
                    by_date[d] = (round(total, 6), n)
                last = None
                carry: dict = {}
                for d in all_group_dates:
                    if d in by_date:
                        last = by_date[d]
                    carry[d] = last
                cum_at[c] = carry

            group_end_date = all_group_dates[-1]

            for couple_key in category_couples:
                played_dates = {
                    g['date'] for g in couple_games[couple_key] if _valid_date(g['date'])
                }
                n_games = len(played_dates)
                progression = []
                prev_rank = None

                for d in all_group_dates:
                    my = cum_at[couple_key][d]
                    if my is None:
                        continue
                    my_total, my_n = my
                    my_avg = my_total / my_n
                    ranking = []
                    for c in category_couples:
                        cd = cum_at[c][d]
                        if cd is None:
                            continue
                        c_total, c_n = cd
                        ranking.append((c_total / c_n, c_total, c))
                    ranking.sort(key=lambda x: (-x[0], -x[1], x[2]))
                    rank = next(
                        (idx + 1 for idx, (_, _, c) in enumerate(ranking) if c == couple_key), 1
                    )
                    if rank != prev_rank or d in played_dates:
                        progression.append({'date': d, 'rank': rank, 'avg': round(my_avg, 4)})
                        prev_rank = rank

                if not progression:
                    continue

                se_ranking = []
                for c in category_couples:
                    cd = cum_at[c][group_end_date]
                    if cd is None:
                        continue
                    c_total, c_n = cd
                    se_ranking.append((c_total / c_n, c_total, c))
                se_ranking.sort(key=lambda x: (-x[0], -x[1], x[2]))
                season_end_rank = next(
                    (idx + 1 for idx, (_, _, c) in enumerate(se_ranking) if c == couple_key), None
                )

                if progression[-1]['date'] != group_end_date:
                    my_end = cum_at[couple_key][group_end_date]
                    end_avg = round(my_end[0] / my_end[1], 4) if my_end else 0
                    progression.append({'date': group_end_date, 'rank': season_end_rank, 'avg': end_avg})

                last_game_date = max(
                    (g['date'] for g in couple_games[couple_key] if _valid_date(g['date'])),
                    default=group_end_date
                )

                season_result[couple_key] = {
                    'category': cat,
                    'gender': gen,
                    'games': n_games,
                    'progression': progression,
                    'season_end': group_end_date,
                    'season_end_rank': season_end_rank,
                    'last_game_date': last_game_date,
                }

        result[season_id] = season_result

    return result


def build_all_couple_games():
    from collections import defaultdict
    rows = _query("""
        SELECT
            CASE WHEN r.referee_1 < r.referee_2 THEN r.referee_1 ELSE r.referee_2 END AS ref_a,
            CASE WHEN r.referee_1 < r.referee_2 THEN r.referee_2 ELSE r.referee_1 END AS ref_b,
            m.match_id, m.date, t.season_id, m.home_team, m.away_team,
            m.score_home, m.score_away,
            t.categoria_name, t.competicion_name, t.torneo_name,
            ns.competition_mod, ns.match_quality, ns.score_factor,
            ns.nomination_score, ns.rank_home, ns.rank_away, ns.n_teams
        FROM referees r
        JOIN matches m ON m.match_id = r.match_id
        JOIN torneos t ON t.torneo_id = m.torneo_id
        JOIN nomination_scores ns ON ns.match_id = r.match_id
            AND ns.referee_name = r.referee_1
        WHERE r.referee_1 != '' AND r.referee_2 != ''
          AND r.referee_1 IS NOT NULL AND r.referee_2 IS NOT NULL
    """)

    result = defaultdict(list)
    for row in rows:
        gender = _gender_from_categoria(row.get('categoria_name', ''))
        result[(row['ref_a'], row['ref_b'])].append({
            "id":  row['match_id'],
            "dt":  row['date'] or '',
            "s":   row['season_id'] or '',
            "g":   gender,
            "comp": row['competicion_name'] or '',
            "phase": row['torneo_name'] or '',
            "h":   row['home_team'] or '',
            "a":   row['away_team'] or '',
            "sh":  row['score_home'],
            "sa":  row['score_away'],
            "rh":  row['rank_home'],
            "ra":  row['rank_away'],
            "n":   row['n_teams'],
            "cm":  row['competition_mod'] or 0,
            "mq":  row['match_quality'] or 0,
            "sf":  row['score_factor'] or 0,
            "ns":  row['nomination_score'] or 0,
        })

    # most recent first
    return {k: sorted(v, key=lambda g: g['dt'], reverse=True) for k, v in result.items()}


_GOOD_DATE = "m.date IS NOT NULL AND m.date != '' AND m.date NOT LIKE '%RETIR%'"


def build_stats(season_id: str | None = None):
    sf = f"AND t.season_id='{season_id}'" if season_id else ""

    overall = _query(f"""
        SELECT
            COUNT(*) AS total_matches,
            SUM(CASE WHEN r.referee_1 != '' AND r.referee_2 != '' THEN 1 ELSE 0 END) AS with_refs,
            SUM(CASE WHEN m.status='Finalizado' THEN 1 ELSE 0 END) AS finalizado,
            SUM(CASE WHEN m.status='Pendiente'  THEN 1 ELSE 0 END) AS pendiente,
            MIN(CASE WHEN {_GOOD_DATE} THEN m.date END) AS min_date,
            MAX(CASE WHEN {_GOOD_DATE} THEN m.date END) AS max_date
        FROM matches m
        JOIN torneos t ON t.torneo_id=m.torneo_id
        LEFT JOIN referees r ON r.match_id=m.match_id
        WHERE 1=1 {sf}
    """)[0]

    by_competition = _query(f"""
        SELECT t.categoria_name, t.competicion_name, t.torneo_name,
            COUNT(*) AS matches,
            SUM(CASE WHEN r.referee_1 IS NOT NULL AND r.referee_1 != ''
                         AND r.referee_2 IS NOT NULL AND r.referee_2 != '' THEN 1 ELSE 0 END) AS with_refs,
            SUM(CASE WHEN m.status='Finalizado' THEN 1 ELSE 0 END) AS finalizado,
            SUM(CASE WHEN m.status='Pendiente'  THEN 1 ELSE 0 END) AS pendiente,
            MIN(CASE WHEN {_GOOD_DATE} THEN m.date END) AS min_date,
            MAX(CASE WHEN {_GOOD_DATE} THEN m.date END) AS max_date
        FROM matches m
        JOIN torneos t ON t.torneo_id=m.torneo_id
        LEFT JOIN referees r ON r.match_id=m.match_id
        WHERE 1=1 {sf}
        GROUP BY t.categoria_name, t.competicion_name, t.torneo_name
        ORDER BY t.categoria_name, t.competicion_name, t.torneo_name
    """)

    by_category = _query(f"""
        SELECT t.categoria_name, COUNT(*) AS matches,
            SUM(CASE WHEN r.referee_1 IS NOT NULL AND r.referee_1 != ''
                         AND r.referee_2 IS NOT NULL AND r.referee_2 != '' THEN 1 ELSE 0 END) AS with_refs,
            SUM(CASE WHEN m.status='Finalizado' THEN 1 ELSE 0 END) AS finalizado,
            SUM(CASE WHEN m.status='Pendiente'  THEN 1 ELSE 0 END) AS pendiente,
            MIN(CASE WHEN {_GOOD_DATE} THEN m.date END) AS min_date,
            MAX(CASE WHEN {_GOOD_DATE} THEN m.date END) AS max_date
        FROM matches m
        JOIN torneos t ON t.torneo_id=m.torneo_id
        LEFT JOIN referees r ON r.match_id=m.match_id
        WHERE 1=1 {sf}
        GROUP BY t.categoria_name ORDER BY matches DESC
    """)

    return overall, by_category, by_competition


def _ref_level(cat: str) -> int:
    c = cat.upper()
    if "PLATA" in c:
        return 2  # División de Honor Plata (2nd tier)
    if "PRIMERA" in c or "ORO" in c:
        return 1  # Primera División / D.H. Oro (3rd tier)
    return 3       # Top: ASOBAL / Liga Guerreras Iberdrola


_LEVEL_LABEL = {3: "Élite", 2: "D.H. Plata", 1: "Primera/Oro"}
_LEVEL_COLOR = {3: "#7c3aed", 2: "#0ea5e9", 1: "#10b981"}


_CAT_TO_LEVEL = {"elite": 3, "honor": 2, "primera": 1}
_LEVEL_TO_CAT = {3: "elite", 2: "honor", 1: "primera"}


def _season_label(s: str) -> str:
    return f"{s[:2]}/{s[2:]}"


def _canonical_name(raw: str) -> str:
    """
    Normalise a PDF name to 'Given Surname1 Surname2' with title case.
    Handles:
      'Colmenero Guillén, Luis'     → 'Luis Colmenero Guillén'
      'JOSE DAVID SANCHEZ MARTINEZ' → 'Jose David Sanchez Martinez'
    NFC normalisation is applied before .title() so combining accents
    (e.g. NFD 'e'+'́') don't cause the following letter to be capitalised.
    """
    import unicodedata
    raw = raw.strip()
    if ',' in raw:
        surnames, given = raw.split(',', 1)
        raw = f"{given.strip()} {surnames.strip()}"
    return unicodedata.normalize('NFC', raw).title()


def _gender_from_categoria(categoria_name: str) -> str:
    """Extract 'M' or 'F' from categoria_name."""
    if "FEMENIN" in (categoria_name or "").upper():
        return "F"
    elif "MASCULIN" in (categoria_name or "").upper():
        return "M"
    return ""


def _category_from_categoria_name(categoria_name: str) -> str:
    """Extract short category (elite/honor/primera) from full categoria_name."""
    name = (categoria_name or "").upper()
    if "ELITE" in name:
        return "elite"
    elif "ORO" in name or ("HONOR" in name and "PLATA" not in name and "PRIMERA" not in name):
        return "honor"
    elif "PLATA" in name or "PRIMERA" in name:
        return "primera"
    return "?"


def _nm_cross(s: str) -> str:
    """Token-sort + hyphen-flattening normalization for cross-season catalog matching."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", s)
    flat = nfkd.encode("ascii", "ignore").decode("ascii").replace("-", " ")
    return " ".join(sorted(flat.lower().split()))


def _cross_match(new_entries: dict, old_entries: dict,
                 sort_threshold: int = 85, set_threshold: int = 90):
    """
    Match catalog entries between two seasons.
    First tries exact token-sort match; falls back to fuzzy using
    token_sort_ratio >= sort_threshold OR token_set_ratio >= set_threshold
    (the set metric catches same-person entries where one PDF has an extra
    middle name that drops the sort score below threshold).
    Manual aliases from config.MANUAL_CROSS_ALIASES are applied first.
    """
    from rapidfuzz import process, fuzz

    aliases = {_nm_cross(k): _nm_cross(v)
               for k, v in config.MANUAL_CROSS_ALIASES.items()}

    def _apply_alias(ts: str) -> str:
        return aliases.get(ts, ts)

    old_ts = {_apply_alias(_nm_cross(n)): n for n in old_entries}

    pairs, matched_old, only_new = [], set(), []
    for norm_new in new_entries:
        query = _apply_alias(_nm_cross(norm_new))

        if query in old_ts:
            norm_old = old_ts[query]
            pairs.append((norm_new, norm_old))
            matched_old.add(norm_old)
            continue

        # fuzzy: accept if sort_ratio >= sort_threshold
        # OR if set_ratio >= set_threshold (extra middle name case)
        candidates = list(old_ts.keys())
        hit_sort = process.extractOne(query, candidates,
                                      scorer=fuzz.token_sort_ratio,
                                      score_cutoff=sort_threshold)
        if not hit_sort:
            hit_set = process.extractOne(query, candidates,
                                         scorer=fuzz.token_set_ratio,
                                         score_cutoff=set_threshold)
            # secondary guard: sort_ratio must still be ≥ 75 to avoid
            # false positives when two people share a double surname
            if hit_set and fuzz.token_sort_ratio(query, hit_set[0]) >= 75:
                hit_sort = hit_set

        if hit_sort:
            norm_old = old_ts[hit_sort[0]]
            if norm_old not in matched_old:
                pairs.append((norm_new, norm_old))
                matched_old.add(norm_old)
            else:
                only_new.append(norm_new)
        else:
            only_new.append(norm_new)

    only_old = [n for n in old_entries if n not in matched_old]
    return pairs, only_new, only_old


def build_referee_identities() -> list[dict]:
    """
    Cluster all catalog entries across seasons into one canonical identity per person.
    Process newest → oldest so the most recent PDF's name becomes the canonical.
    Returns list of identity dicts, sorted alphabetically by canonical name.
    """
    from collections import defaultdict
    from rapidfuzz import process, fuzz

    all_entries = _query(
        "SELECT season_id, normalized, category, raw_name FROM referees_catalog"
    )
    by_season: dict = defaultdict(dict)
    for r in all_entries:
        by_season[r["season_id"]][r["normalized"]] = {
            "category": r["category"],
            "raw_name": r["raw_name"],
        }
    available = [s for s in config.CATALOG_SEASONS if s in by_season]

    aliases = {_nm_cross(k): _nm_cross(v)
               for k, v in config.MANUAL_CROSS_ALIASES.items()}

    def _alias(ts: str) -> str:
        return aliases.get(ts, ts)

    # identities keyed by canonical token-sort normalized form
    identities: dict = {}

    for season_id in available:          # newest first
        for norm, entry in by_season[season_id].items():
            ts = _alias(_nm_cross(norm))

            if ts in identities:
                identities[ts]["seasons"][season_id] = entry
                continue

            # fuzzy search in existing identities
            hit = None
            if identities:
                cands = list(identities.keys())
                h_sort = process.extractOne(ts, cands,
                                            scorer=fuzz.token_sort_ratio,
                                            score_cutoff=85)
                if not h_sort:
                    h_set = process.extractOne(ts, cands,
                                               scorer=fuzz.token_set_ratio,
                                               score_cutoff=90)
                    if h_set and fuzz.token_sort_ratio(ts, h_set[0]) >= 75:
                        h_sort = h_set
                if h_sort:
                    hit = h_sort[0]

            if hit:
                identities[hit]["seasons"][season_id] = entry
            else:
                # New identity — canonical = this season's name (newest available)
                identities[ts] = {
                    "canonical":    _canonical_name(entry["raw_name"]),
                    "category":     entry["category"],
                    "canonical_ts": ts,
                    "seasons":      {season_id: entry},
                }

    # Build result list
    result = []
    for ts, ident in identities.items():
        seasons = ident["seasons"]
        # Ensure canonical is from the newest available season, formatted consistently
        for s in available:
            if s in seasons:
                ident["canonical"] = _canonical_name(seasons[s]["raw_name"])
                ident["category"]  = seasons[s]["category"]
                break
        # Seasons with a DIFFERENT name than canonical
        variants = {
            s: v["raw_name"]
            for s, v in seasons.items()
            if v["raw_name"] != ident["canonical"]
        }
        ident["variants"]    = variants
        ident["has_variants"] = bool(variants)
        ident["season_ids"]  = sorted(seasons.keys(), reverse=True)
        result.append(ident)

    return sorted(result, key=lambda r: r["canonical"].lower())


def build_referee_movements() -> dict:
    """
    For every consecutive season pair where both catalogs are loaded,
    compute: level changes (up/down), new appearances, disappearances.
    Returns {transition_key: [row_dict, ...]} e.g. {"2425-2526": [...]}
    """
    from collections import defaultdict

    # Load all catalog entries grouped by season
    all_entries = _query("SELECT season_id, normalized, category, raw_name FROM referees_catalog")
    by_season: dict = defaultdict(dict)  # season_id → {normalized: {category, raw_name}}
    for r in all_entries:
        by_season[r["season_id"]][r["normalized"]] = {
            "category": r["category"],
            "raw_name": r["raw_name"],
        }

    available = [s for s in config.CATALOG_SEASONS if s in by_season]

    # Nomination stats per (scraper_name, season_id)
    nom_rows = _query("""
        SELECT ns.referee_name, t.season_id,
               COUNT(*) AS noms,
               ROUND(SUM(ns.nomination_score),3) AS score
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

    # Name maps (scraper name → catalog normalized key) for seasons with game data
    import name_matcher as nm_mod
    name_maps: dict = {}
    for sid in seasons_with_data:
        if sid in by_season:
            name_maps[sid] = nm_mod.build_name_map(season_id=sid)

    # Per-season category rankings (only for seasons with game data)
    cat_ranks: dict = {}  # season_id → {scraper_name: (rank, total, cat)}
    for sid, nm in name_maps.items():
        ranked = _query(f"""
            SELECT ns.referee_name, ROUND(SUM(ns.nomination_score),3) AS ts
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

    def _scraper_cat(scraper_name: str, sid: str) -> str | None:
        """Look up catalog category for a scraper name in a given season."""
        nm = name_maps.get(sid, {})
        entry = nm.get(scraper_name)
        return entry["category"] if entry else None

    # Build movements for each consecutive pair
    result: dict = {}
    for i in range(len(available) - 1):
        s_new = available[i]
        s_old = available[i + 1]
        key = f"{s_old}-{s_new}"

        cat_new_season = by_season[s_new]
        cat_old_season = by_season[s_old]

        pairs, only_new, only_old = _cross_match(cat_new_season, cat_old_season)

        rows: list[dict] = []

        def _scraper_stats(norm: str, sid: str):
            """Return (rank_info, nom_dict) for a catalog normalized key in a given season."""
            nm = name_maps.get(sid, {})
            for scraper_name, entry in nm.items():
                if entry and entry.get("normalized") == norm:
                    return cat_ranks.get(sid, {}).get(scraper_name), nom_stats[scraper_name][sid]
            return None, {"noms": 0, "score": 0.0}

        def _rank_str(ri):
            return f"{ri[0]}/{ri[1]}" if ri else "—"

        # Level changes and stable pairs
        for norm_n, norm_o in pairs:
            cat_n = cat_new_season[norm_n]["category"]
            cat_o = cat_old_season[norm_o]["category"]
            if cat_n == cat_o:
                continue
            lvl_o = _CAT_TO_LEVEL.get(cat_o, 0)
            lvl_n = _CAT_TO_LEVEL.get(cat_n, 0)
            if not lvl_o or not lvl_n:
                continue
            ri_n, nom_n = _scraper_stats(norm_n, s_new)
            _, nom_o    = _scraper_stats(norm_o, s_old)
            rows.append({
                "move_type":  "up" if lvl_n > lvl_o else "down",
                "name":       cat_new_season[norm_n]["raw_name"],
                "cat_old":    cat_o, "cat_new": cat_n,
                "lvl_old":    lvl_o, "lvl_new": lvl_n,
                "noms_old":   nom_o["noms"]   if s_old in seasons_with_data else None,
                "score_old":  round(nom_o["score"], 3) if s_old in seasons_with_data else None,
                "noms_new":   nom_n["noms"]   if s_new in seasons_with_data else None,
                "score_new":  round(nom_n["score"], 3) if s_new in seasons_with_data else None,
                "rank_str":   _rank_str(ri_n),
            })

        # New appearances
        for norm_n in only_new:
            cat_n = cat_new_season[norm_n]["category"]
            lvl_n = _CAT_TO_LEVEL.get(cat_n, 0)
            ri_n, nom_n = _scraper_stats(norm_n, s_new)
            rows.append({
                "move_type":  "new",
                "name":       cat_new_season[norm_n]["raw_name"],
                "cat_old":    None, "cat_new": cat_n,
                "lvl_old":    0,    "lvl_new": lvl_n,
                "noms_old":   None, "score_old": None,
                "noms_new":   nom_n["noms"]   if s_new in seasons_with_data else None,
                "score_new":  round(nom_n["score"], 3) if s_new in seasons_with_data else None,
                "rank_str":   _rank_str(ri_n),
            })

        # Disappearances
        for norm_o in only_old:
            cat_o = cat_old_season[norm_o]["category"]
            lvl_o = _CAT_TO_LEVEL.get(cat_o, 0)
            ri_o, nom_o = _scraper_stats(norm_o, s_old)
            rows.append({
                "move_type":  "gone",
                "name":       cat_old_season[norm_o]["raw_name"],
                "cat_old":    cat_o, "cat_new": None,
                "lvl_old":    lvl_o, "lvl_new": 0,
                "noms_old":   nom_o["noms"]   if s_old in seasons_with_data else None,
                "score_old":  round(nom_o["score"], 3) if s_old in seasons_with_data else None,
                "noms_new":   None, "score_new": None,
                "rank_str":   _rank_str(ri_o) if s_old in seasons_with_data else "—",
            })

        # Sort: changes first (by level desc), then new, then gone; within each by score
        def _sort_key(r):
            type_order = {"up": 0, "down": 1, "new": 2, "gone": 3}
            score = r["score_new"] or r["score_old"] or 0
            return (type_order[r["move_type"]], -(r["lvl_new"] or r["lvl_old"]), -score)

        rows.sort(key=_sort_key)
        result[key] = rows

    return result


def build_games_filters():
    """Build unique competitions and their phases for dropdown filters."""
    comps = _query("""
        SELECT DISTINCT competicion_name, torneo_name FROM torneos
        WHERE season_id = '2526'
        ORDER BY competicion_name, torneo_name
    """)

    comp_dict = {}
    for row in comps:
        comp = row['competicion_name']
        phase = row['torneo_name']
        if comp not in comp_dict:
            comp_dict[comp] = []
        comp_dict[comp].append(phase)

    return comp_dict


def build_all_games():
    return _query(f"""
        SELECT m.match_id, m.date, t.season_id, m.home_team, m.away_team,
            m.score_home, m.score_away, m.status,
            t.categoria_name, t.competicion_name, t.torneo_name,
            COALESCE(r.referee_1, '') AS referee_1,
            COALESCE(r.referee_2, '') AS referee_2,
            COALESCE(ns.competition_mod, 0) AS competition_mod,
            COALESCE(ns.match_quality, 0)   AS match_quality,
            COALESCE(ns.score_factor, 0)    AS score_factor,
            COALESCE(ns.nomination_score, 0) AS nomination_score
        FROM matches m
        JOIN torneos t ON t.torneo_id = m.torneo_id
        LEFT JOIN referees r ON r.match_id = m.match_id
        LEFT JOIN nomination_scores ns ON ns.match_id = m.match_id
            AND ns.referee_name = r.referee_1
        WHERE {_GOOD_DATE}
        ORDER BY m.date DESC, m.match_id DESC
    """)


def pct_bar(n, total):
    if total == 0:
        return "—"
    p = round(n / total * 100)
    color = "#22c55e" if p >= 95 else "#f59e0b" if p >= 70 else "#ef4444"
    return (
        f'<div class="bar-wrap" title="{n}/{total}">'
        f'<div class="bar" style="width:{p}%;background:{color}"></div>'
        f'<span>{p}%</span></div>'
    )


def fmt_date(d):
    if not d:
        return "—"
    y, m, day = d.split("-")
    return f"{day}/{m}/{y}"


def _ea(s):
    return (s or '').replace('&', '&amp;').replace('"', '&quot;')


CAT_COLOR = {"elite": "#7c3aed", "honor": "#0ea5e9", "primera": "#10b981", "?": "#64748b"}
CAT_LABEL = {"elite": "Élite", "honor": "Honor", "primera": "1ª Div", "?": "—"}
_CAT_RANK  = {"elite": 0, "honor": 1, "primera": 2, "?": 3}


def render_couple_rows(couples):
    rows = ""
    for i, r in enumerate(couples, 1):
        ca, cb = r.get("cat_a") or "?", r.get("cat_b") or "?"
        best_cat = ca if _CAT_RANK.get(ca, 9) <= _CAT_RANK.get(cb, 9) else cb
        color = CAT_COLOR.get(best_cat, "#64748b")
        label = CAT_LABEL.get(best_cat, "?")
        first = fmt_date(r["first_game"]) if r.get("first_game") else "—"
        last  = fmt_date(r["last_game"])  if r.get("last_game")  else "—"
        key   = f"{r['ref_a'].lower()}|||{r['ref_b'].lower()}"
        # Gender from couple games: query for one game with these referees and extract from categoria_name
        gender = r.get("gender", "")
        rows += f"""
        <tr data-ref-a="{r['ref_a'].lower()}" data-ref-b="{r['ref_b'].lower()}"
            data-games="{r['games']}" data-cat="{best_cat}" data-gender="{gender}"
            data-total="{r['total_score']}" data-avg="{r['avg_score']}"
            data-best="{r['best_score']}" data-cmod="{r['avg_comp_mod']}"
            data-quality="{r['avg_quality']}" data-sf="{r['avg_score_factor']}"
            data-first="{r['first_game'] or ''}" data-last="{r['last_game'] or ''}"
            data-key="{key}"
            onclick="showModal(this)" onmouseenter="showTooltip(this,event)"
            onmousemove="reposTooltip(event)" onmouseleave="hideTooltip()">
          <td class="num rank">#{i}</td>
          <td><span class="badge" style="background:{color}">{label}</span></td>
          <td class="couple-names">
            <div>{r['ref_a'].title()}</div>
            <div>{r['ref_b'].title()}</div>
          </td>
          <td class="num">{r['games']}</td>
          <td class="num dim">{first}</td>
          <td class="num dim">{last}</td>
          <td class="num bold">{r['total_score']:.3f}</td>
          <td class="num">{r['avg_score']:.3f}</td>
          <td class="num">{r['best_score']:.3f}</td>
          <td class="num dim">{r['avg_comp_mod']:.2f}</td>
          <td class="num dim">{r['avg_quality']:.3f}</td>
          <td class="num dim">{r['avg_score_factor']:.3f}</td>
        </tr>"""
    return rows


def render_game_rows(games):
    rows = ""
    for i, g in enumerate(games, 1):
        score = f"{g['score_home']}–{g['score_away']}" if g['score_home'] is not None else "Pend."
        gender = _gender_from_categoria(g.get('categoria_name', ''))
        rows += f"""
        <tr data-date="{g['date'] or ''}" data-season="{g['season_id'] or ''}"
            data-gender="{gender}"
            data-comp="{_ea((g['competicion_name'] or '').lower())}"
            data-phase="{_ea((g['torneo_name'] or '').lower())}"
            data-h="{_ea((g['home_team'] or '').lower())}"
            data-a="{_ea((g['away_team'] or '').lower())}"
            data-ref1="{_ea((g['referee_1'] or '').lower())}"
            data-ref2="{_ea((g['referee_2'] or '').lower())}"
            data-cm="{g['competition_mod']:.4f}"
            data-mq="{g['match_quality']:.4f}"
            data-sf="{g['score_factor']:.4f}"
            data-ns="{g['nomination_score']:.4f}">
          <td class="num rank">#{i}</td>
          <td data-sort="{g['date'] or ''}" class="num dim">{fmt_date(g['date'])}</td>
          <td class="ell" title="{_ea(g['competicion_name'] or '')}">{g['competicion_name'] or '—'}</td>
          <td class="ell dim" style="font-size:.77rem" title="{_ea(g['torneo_name'] or '')}">{g['torneo_name'] or '—'}</td>
          <td class="ell" title="{_ea(g['home_team'] or '')}">{(g['home_team'] or '').title()}</td>
          <td class="ell" title="{_ea(g['away_team'] or '')}">{(g['away_team'] or '').title()}</td>
          <td class="num">{score}</td>
          <td class="ell" title="{_ea(g['referee_1'] or '')}">{(g['referee_1'] or '').title() or '—'}</td>
          <td class="ell" title="{_ea(g['referee_2'] or '')}">{(g['referee_2'] or '').title() or '—'}</td>
          <td class="num dim">{g['competition_mod']:.2f}</td>
          <td class="num dim">{g['match_quality']:.3f}</td>
          <td class="num dim">{g['score_factor']:.3f}</td>
          <td class="num bold">{g['nomination_score']:.3f}</td>
        </tr>"""
    return rows


def render_stats_panel(overall, by_category, by_competition):
    total = overall["total_matches"] or 1
    cat_rows = ""
    for r in by_category:
        cat_rows += f"""
        <tr>
          <td>{r['categoria_name']}</td>
          <td class="num">{r['matches']}</td>
          <td class="num">{r['finalizado']}</td>
          <td class="num">{r['pendiente']}</td>
          <td>{pct_bar(r['with_refs'], r['matches'])}</td>
          <td class="num">{fmt_date(r['min_date'])}</td>
          <td class="num">{fmt_date(r['max_date'])}</td>
        </tr>"""

    comp_rows = ""
    for (cat, comp), group in groupby(by_competition, key=lambda r: (r["categoria_name"], r["competicion_name"])):
        torneos = list(group)
        span = len(torneos)
        for i, r in enumerate(torneos):
            is_first = i == 0
            cat_td  = f'<td class="cat-cell" rowspan="{span}">{cat}</td>' if is_first else ""
            comp_td = f'<td class="comp-cell" rowspan="{span}">{comp}</td>' if is_first else ""
            comp_rows += f"""
        <tr class="{'first-torneo' if is_first else 'extra-torneo'}">
          {cat_td}{comp_td}
          <td class="torneo-cell">{r['torneo_name']}</td>
          <td class="num">{r['matches']}</td>
          <td class="num">{r['finalizado']}</td>
          <td class="num">{r['pendiente']}</td>
          <td>{pct_bar(r['with_refs'], r['matches'])}</td>
          <td class="num">{fmt_date(r['min_date'])}</td>
          <td class="num">{fmt_date(r['max_date'])}</td>
        </tr>"""

    return f"""
<div class="cards">
  <div class="card"><div class="card-label">Partidos totales</div><div class="card-value">{overall['total_matches']:,}</div></div>
  <div class="card"><div class="card-label">Con pareja asignada</div><div class="card-value">{overall['with_refs']:,}</div><div class="card-sub">{round(overall['with_refs']/total*100)}% del total</div></div>
  <div class="card"><div class="card-label">Finalizados</div><div class="card-value">{overall['finalizado']:,}</div></div>
  <div class="card"><div class="card-label">Pendientes</div><div class="card-value">{overall['pendiente']:,}</div></div>
  <div class="card"><div class="card-label">Primer partido</div><div class="card-value" style="font-size:1.3rem">{fmt_date(overall['min_date'])}</div></div>
  <div class="card"><div class="card-label">Último partido</div><div class="card-value" style="font-size:1.3rem">{fmt_date(overall['max_date'])}</div></div>
</div>
<h2>Por categoría</h2>
<div class="section"><table>
  <thead><tr>
    <th title="Categoría nacional">Categoría</th><th style="text-align:right" title="Total de partidos en el sistema">Partidos</th>
    <th style="text-align:right" title="Partidos ya disputados">Finaliz.</th><th style="text-align:right" title="Partidos aún por disputar">Pendien.</th>
    <th title="Porcentaje de partidos con dos árbitros asignados">Pareja asignada</th><th style="text-align:right" title="Fecha del primer partido">Inicio</th><th style="text-align:right" title="Fecha del último partido">Fin</th>
  </tr></thead>
  <tbody>{cat_rows}</tbody>
</table></div>
<h2>Por competición</h2>
<div class="section"><table>
  <thead><tr>
    <th title="Categoría nacional">Categoría</th><th title="Nombre de la competición">Competición</th><th title="Fase o grupo dentro de la competición">Fase / Grupo</th>
    <th style="text-align:right" title="Total de partidos">Partidos</th><th style="text-align:right" title="Partidos ya disputados">Finaliz.</th>
    <th style="text-align:right" title="Partidos aún por disputar">Pendien.</th><th title="Porcentaje con pareja asignada">Pareja asignada</th>
    <th style="text-align:right" title="Fecha del primer partido">Inicio</th><th style="text-align:right" title="Fecha del último partido">Fin</th>
  </tr></thead>
  <tbody>{comp_rows}</tbody>
</table></div>"""


_MOVE_ICONS = {"up": "↑", "down": "↓", "new": "★", "gone": "✗"}
_MOVE_CLASSES = {"up": "move-up", "down": "move-down", "new": "move-new", "gone": "move-gone"}
_CAT_LEVEL_COLOR = {3: "#7c3aed", 2: "#0ea5e9", 1: "#10b981", 0: "#64748b"}
_CAT_LEVEL_LABEL = {3: "Élite", 2: "D.H.", 1: "Primera", 0: "—"}


def render_refs_rows(identities: list[dict]) -> str:
    rows = ""
    for ident in identities:
        cat = ident["category"] or "?"
        color = CAT_COLOR.get(cat, "#64748b")
        label = CAT_LABEL.get(cat, cat)
        badge = f'<span class="badge" style="background:{color}">{label}</span>'

        # Color each season badge by the category they had that season
        season_badges_list = []
        for s in ident["season_ids"]:
            season_cat = ident["seasons"][s].get("category", "?")
            season_color = CAT_COLOR.get(season_cat, "#64748b")
            season_label = CAT_LABEL.get(season_cat, "?")
            season_badges_list.append(
                f'<span class="badge" style="background:{season_color};font-size:0.68rem" title="{season_label}">{_season_label(s)}</span>'
            )
        season_badges = " ".join(season_badges_list)

        if ident["has_variants"]:
            variant_list = "; ".join(
                f'<span style="color:#94a3b8">{name}</span>'
                f' <span style="color:#475569">({_season_label(s)})</span>'
                for s, name in sorted(ident["variants"].items(), reverse=True)
            )
        else:
            variant_list = '<span style="color:#334155">—</span>'

        has_v = "1" if ident["has_variants"] else "0"
        rows += f"""
        <tr data-has-variants="{has_v}" data-name="{_ea(ident['canonical'].lower())}">
          <td style="font-weight:500">{ident['canonical']}</td>
          <td>{badge}</td>
          <td style="white-space:nowrap">{season_badges}</td>
          <td style="font-size:0.8rem">{variant_list}</td>
        </tr>"""
    return rows


def _render_moves_rows(all_movements: dict) -> str:
    rows = ""
    for transition_key, mvs in all_movements.items():
        for r in mvs:
            mt = r["move_type"]
            icon_cls = _MOVE_CLASSES[mt]
            icon = _MOVE_ICONS[mt]

            c_old = _CAT_LEVEL_COLOR.get(r["lvl_old"], "#64748b")
            c_new = _CAT_LEVEL_COLOR.get(r["lvl_new"], "#64748b")
            lbl_old = _CAT_LEVEL_LABEL.get(r["lvl_old"], "—") if r["cat_old"] else "—"
            lbl_new = _CAT_LEVEL_LABEL.get(r["lvl_new"], "—") if r["cat_new"] else "—"

            badge_old = f'<span class="badge" style="background:{c_old}">{lbl_old}</span>' \
                        if r["cat_old"] else '<span style="color:#475569">—</span>'
            badge_new = f'<span class="badge" style="background:{c_new}">{lbl_new}</span>' \
                        if r["cat_new"] else '<span style="color:#475569">—</span>'

            def _fmt(v): return f"{v:.3f}" if v is not None else "—"
            def _fmti(v): return str(v) if v is not None else "—"

            cat_for_filter = r.get('cat_new') or r.get('cat_old') or ''
            rows += f"""
        <tr data-transition="{transition_key}" data-type="{mt}" data-category="{cat_for_filter}">
          <td><span class="{icon_cls}" style="font-weight:700">{icon}</span></td>
          <td>{r['name'].title()}</td>
          <td>{badge_old}</td>
          <td style="color:#475569;text-align:center">→</td>
          <td>{badge_new}</td>
          <td class="num dim">{_fmti(r['noms_old'])}</td>
          <td class="num dim">{_fmt(r['score_old'])}</td>
          <td class="num">{_fmti(r['noms_new'])}</td>
          <td class="num bold">{_fmt(r['score_new'])}</td>
          <td class="num">{r['rank_str']}</td>
        </tr>"""
    return rows


def render_html(overall, by_category, by_competition, couples, couple_games, all_games,
                stats_2526=None, stats_2425=None, all_movements=None, identities=None,
                progression_data=None, games_filters=None):
    couple_rows = render_couple_rows(couples)
    game_rows   = render_game_rows(all_games)
    all_movements = all_movements or {}
    moves_rows  = _render_moves_rows(all_movements)
    refs_rows   = render_refs_rows(identities or [])
    progression_data = progression_data or {}


    # Transition buttons — newest transition first
    seasons_with_data = {config.SEASON_ID, config.PREV_SEASON_ID}
    transitions = list(all_movements.keys())
    default_transition = transitions[0] if transitions else ""
    moves_transition_btns = ""
    for i, key in enumerate(transitions):
        s_o, s_n = key.split("-")
        lbl = f"{_season_label(s_o)} → {_season_label(s_n)}"
        active = "active" if i == 0 else ""
        moves_transition_btns += f'  <button class="season-btn trans-btn {active}" onclick="setMovesTransition(\'{key}\',this)">{lbl}</button>\n'

    moves_with_data_js = json.dumps(
        {k: any(s in seasons_with_data for s in k.split("-")) for k in transitions}
    )

    _cg = {f"{ra.lower()}|||{rb.lower()}": gs for (ra, rb), gs in couple_games.items()}
    _cg_js = json.dumps(_cg, ensure_ascii=False, separators=(',', ':')).replace('</script>', r'<\/script>')

    # Convert progression data to JS format (season → couple_comp_key → data)
    # Key is JSON.stringify([refA, refB, comp]) to match JS
    _pd = {}
    for season_id, couples in progression_data.items():
        _pd[season_id] = {}
        for (ref_a, ref_b, comp), data in couples.items():
            couple_key = json.dumps([ref_a, ref_b, comp], separators=(',', ':'), ensure_ascii=False)
            _pd[season_id][couple_key] = data
    _pd_js = json.dumps(_pd, ensure_ascii=False, separators=(',', ':')).replace('</script>', r'<\/script>')

    # Games filters for cascading dropdowns
    games_filters = games_filters or {}
    _gf_js = json.dumps(games_filters, ensure_ascii=False, separators=(',', ':'))

    # Build competition options
    game_comp_options = ""
    for comp in sorted(games_filters.keys()):
        game_comp_options += f'        <option value="{_ea(comp)}">{comp}</option>\n'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Árbitros Balonmano 2025/26</title>
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ font-family:system-ui,sans-serif; background:#0f172a; color:#e2e8f0; padding:2rem; }}
h1 {{ font-size:1.5rem; font-weight:700; margin-bottom:0.25rem; color:#f8fafc; }}
.subtitle {{ color:#94a3b8; font-size:0.875rem; margin-bottom:2rem; }}
.cards {{ display:flex; gap:1rem; flex-wrap:wrap; margin-bottom:2.5rem; }}
.card {{ background:#1e293b; border:1px solid #334155; border-radius:0.75rem; padding:1.25rem 1.75rem; min-width:160px; }}
.card-label {{ font-size:0.75rem; color:#94a3b8; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.4rem; }}
.card-value {{ font-size:2rem; font-weight:700; color:#f8fafc; }}
.card-sub {{ font-size:0.8rem; color:#64748b; margin-top:0.2rem; }}
h2 {{ font-size:1rem; font-weight:600; color:#cbd5e1; margin:2rem 0 0.75rem; }}
table {{ width:100%; border-collapse:collapse; font-size:0.85rem; }}
thead th {{ background:#1e293b; color:#94a3b8; font-weight:600; padding:0.6rem 0.75rem; text-align:left; border-bottom:1px solid #334155; }}
tbody tr:nth-child(even) {{ background:#111827; }}
tbody tr:hover {{ background:#1e3a5f; }}
td {{ padding:0.5rem 0.75rem; border-bottom:1px solid #1e293b; vertical-align:middle; }}
td.num {{ text-align:right; color:#94a3b8; }}
td.ell {{ max-width:160px; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }}
td.cat-cell {{ color:#64748b; font-size:0.75rem; max-width:220px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; vertical-align:top; padding-top:0.75rem; border-top:1px solid #334155; }}
td.comp-cell {{ font-weight:600; vertical-align:top; padding-top:0.75rem; border-top:1px solid #334155; }}
td.torneo-cell {{ color:#94a3b8; font-size:0.82rem; padding-left:1.5rem; }}
tr.first-torneo td {{ border-top:1px solid #334155; }}
tr.extra-torneo td {{ border-top:1px solid #1e293b; }}
.bar-wrap {{ display:flex; align-items:center; gap:0.5rem; min-width:120px; }}
.bar {{ height:6px; border-radius:3px; }}
.bar-wrap span {{ font-size:0.8rem; color:#94a3b8; min-width:2.5rem; }}
.section {{ overflow-x:auto; }}
td.couple-names div {{ font-weight:500; }}
th.sortable {{ cursor:pointer; user-select:none; }}
th.sortable:hover {{ color:#e2e8f0; }}
th.sort-asc::after  {{ content:" ▲"; font-size:0.7rem; }}
th.sort-desc::after {{ content:" ▼"; font-size:0.7rem; }}
.tabs {{ display:flex; gap:0.5rem; margin-bottom:1.5rem; flex-wrap:wrap; }}
.tab-btn {{ padding:0.45rem 1.1rem; border:1px solid #334155; border-radius:0.5rem; background:#1e293b; color:#94a3b8; cursor:pointer; font-size:0.85rem; }}
.tab-btn.active {{ background:#3b82f6; border-color:#3b82f6; color:#fff; }}
.tab-panel {{ display:none; }}
.tab-panel.active {{ display:block; }}
td.rank {{ color:#64748b; width:2.5rem; }}
td.bold {{ font-weight:600; color:#f8fafc; }}
td.dim  {{ color:#64748b; }}
td.terr {{ font-size:0.75rem; color:#64748b; max-width:180px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.badge {{ display:inline-block; padding:0.15rem 0.5rem; border-radius:0.3rem; font-size:0.72rem; font-weight:600; color:#fff; }}
.count-label {{ color:#64748b; font-size:0.8rem; text-align:right; margin-bottom:0.4rem; min-height:1.2em; }}
#couples-body tr {{ cursor:pointer; }}
#couples-table th:nth-child(n+9),
#couples-table td:nth-child(n+9) {{ display:none !important; width:0 !important; padding:0 !important; border:none !important; }}
#games-table th:nth-child(10),
#games-table th:nth-child(11),
#games-table th:nth-child(12),
#games-table td:nth-child(10),
#games-table td:nth-child(11),
#games-table td:nth-child(12) {{ display:none !important; width:0 !important; padding:0 !important; border:none !important; }}
/* column 13 (Score) stays visible */
tr.filter-row td {{ background:#0d1d35; padding:0.18rem 0.35rem; border-bottom:1px solid #334155; }}
tr.filter-row input, tr.filter-row select {{
  width:100%; background:#0f172a; border:1px solid #1e293b;
  color:#94a3b8; padding:0.15rem 0.3rem; border-radius:0.2rem; font-size:0.72rem; }}
tr.filter-row input:focus, tr.filter-row select:focus {{ outline:none; border-color:#3b82f6; }}
.date-pair {{ display:flex; flex-direction:column; gap:2px; }}
.season-btn {{
  padding:0.35rem 0.9rem; border:1px solid #334155; border-radius:0.5rem;
  background:#1e293b; color:#94a3b8; cursor:pointer; font-size:0.82rem; }}
.season-btn.active {{ background:#0f4c8a; border-color:#1d6fb8; color:#fff; font-weight:600; }}
.season-btn:hover:not(.active) {{ border-color:#475569; color:#e2e8f0; }}
.move-up   {{ color:#22c55e; font-weight:700; }}
.move-down {{ color:#f87171; font-weight:700; }}
.move-new  {{ color:#f59e0b; font-weight:700; }}
.move-gone {{ color:#64748b; font-weight:700; }}
.clear-all-btn {{
  background:none; border:1px solid #334155; color:#64748b;
  padding:0.3rem 0.75rem; border-radius:0.4rem; font-size:0.8rem; cursor:pointer; }}
.clear-all-btn:hover {{ border-color:#475569; color:#94a3b8; }}
#c-tip {{
  position:fixed; z-index:1000; pointer-events:none; display:none;
  background:#0f172a; border:1px solid #475569; border-radius:0.5rem;
  padding:0.55rem 0.8rem; font-size:0.78rem; max-width:580px;
  box-shadow:0 4px 18px rgba(0,0,0,0.65);
}}
#c-tip td {{ padding:0.13rem 0.4rem; border:none; color:#cbd5e1; }}
#c-tip .tip-hdr {{ font-weight:600; color:#f8fafc; margin-bottom:0.35rem; font-size:0.82rem; }}
#c-modal-bg {{
  display:none; position:fixed; inset:0; z-index:2000;
  background:rgba(0,0,0,0.78); overflow-y:auto; padding:2rem 1rem;
}}
#c-modal {{
  background:#1e293b; border:1px solid #334155; border-radius:0.75rem;
  width:min(1400px, 96vw); margin:0 auto; padding:1.5rem; position:relative;
}}
#c-modal h3 {{ color:#f8fafc; font-size:1.05rem; margin-bottom:0.2rem; }}
#c-modal .m-sub {{ color:#64748b; font-size:0.8rem; margin-bottom:1rem; }}
#c-modal .close-btn {{
  position:absolute; top:0.7rem; right:1rem; background:none; border:none;
  color:#64748b; font-size:1.7rem; cursor:pointer; line-height:1;
}}
#c-modal .close-btn:hover {{ color:#e2e8f0; }}
#modal-games-table {{ font-size:0.8rem; width:100%; table-layout:fixed; border-collapse:collapse; }}
#modal-games-table th {{ background:#1e293b; color:#94a3b8; font-weight:600; padding:0.5rem 0.6rem;
  text-align:left; border-bottom:1px solid #334155; overflow:hidden; white-space:nowrap;
  text-overflow:ellipsis; cursor:pointer; user-select:none; }}
#modal-games-table th:hover {{ color:#e2e8f0; }}
#modal-games-table th.sort-asc::after  {{ content:" ▲"; font-size:0.7rem; }}
#modal-games-table th.sort-desc::after {{ content:" ▼"; font-size:0.7rem; }}
#modal-games-table td {{ padding:0.45rem 0.6rem; border-bottom:1px solid #1e293b;
  overflow:hidden; white-space:nowrap; text-overflow:ellipsis; vertical-align:middle; }}
#modal-games-table td.num {{ text-align:right; color:#94a3b8; }}
#modal-games-table td.bold {{ font-weight:600; color:#f8fafc; }}
#modal-games-table td.dim {{ color:#64748b; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
</head>
<body>
<h1>Árbitros Balonmano España · <span id="season-label">Temporada 2025/26</span></h1>
<div style="display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap;margin-bottom:1.5rem;">
  <p class="subtitle">Datos: resultadosbalonmano.isquad.es · Categorías nacionales · <span id="season-range">Rango: {fmt_date(overall['min_date'] if stats_2526 is None else stats_2526[0]['min_date'])} – {fmt_date(overall['max_date'] if stats_2526 is None else stats_2526[0]['max_date'])}</span></p>
  <div style="display:flex;gap:0.5rem;">
    <button class="season-btn active" onclick="setSeason('2526',this)">2025/26</button>
    <button class="season-btn" onclick="setSeason('2425',this)">2024/25</button>
    <button class="season-btn" onclick="setSeason('all',this)">Todas</button>
  </div>
</div>

<div class="tabs">
  <button class="tab-btn active" onclick="showTab('stats',this)">Estadísticas</button>
  <button class="tab-btn" onclick="showTab('couples',this)">Ranking parejas</button>
  <button class="tab-btn" onclick="showTab('progression',this)">Progresión</button>
  <button class="tab-btn" onclick="showTab('games',this)">Partidos</button>
  <button class="tab-btn" onclick="showTab('moves',this)">Ascensos/descensos</button>
  <button class="tab-btn" onclick="showTab('refs',this)">Árbitros</button>
</div>

<!-- ── STATS ──────────────────────────────────────────────────────────────── -->
<div id="tab-stats" class="tab-panel active">
  <div id="stats-2526" class="stats-panel">{render_stats_panel(*stats_2526) if stats_2526 else ''}</div>
  <div id="stats-2425" class="stats-panel" style="display:none">{render_stats_panel(*stats_2425) if stats_2425 else ''}</div>
  <div id="stats-all"  class="stats-panel" style="display:none">{render_stats_panel(overall, by_category, by_competition)}</div>
</div><!-- /tab-stats -->

<!-- ── COUPLES ────────────────────────────────────────────────────────────── -->
<div id="tab-couples" class="tab-panel">
<div style="display:flex;align-items:center;justify-content:space-between;gap:0.75rem;flex-wrap:wrap;margin-bottom:0.75rem;">
  <span class="count-label" id="couple-count-label" style="margin-bottom:0"></span>
  <div style="display:flex;gap:0.5rem;">
    <button class="season-btn active" id="cg-all" onclick="filterCoupleGender('all',this)">Todos</button>
    <button class="season-btn" id="cg-m" onclick="filterCoupleGender('M',this)">Masculino</button>
    <button class="season-btn" id="cg-f" onclick="filterCoupleGender('F',this)">Femenino</button>
  </div>
  <button onclick="clearAllCoupleFilters()" class="clear-all-btn">✕ Limpiar filtros</button>
</div>
<div class="section">
<table id="couples-table">
  <thead>
    <tr>
      <th title="Posición en el ranking">Pos.</th>
      <th title="Categoría más alta en la que arbitra la pareja según el PDF de la temporada actual">Cat.</th>
      <th class="sortable" onclick="sortCouples(this,2)">Pareja</th>
      <th class="sortable" style="text-align:right" onclick="sortCouples(this,3)">Partidos</th>
      <th class="sortable" style="text-align:right" title="Fecha del primer partido" onclick="sortCouples(this,4)">1er partido</th>
      <th class="sortable" style="text-align:right" title="Fecha del último partido" onclick="sortCouples(this,5)">Último</th>
      <th class="sortable" style="text-align:right" title="Puntuación total de nominación" onclick="sortCouples(this,6)">Total</th>
      <th class="sortable sort-desc" style="text-align:right" title="Media de puntos por partido" onclick="sortCouples(this,7)">Media ▼</th>
      <th class="sortable" style="text-align:right;display:none" onclick="sortCouples(this,8)">Mejor</th>
      <th class="sortable" style="text-align:right;display:none" onclick="sortCouples(this,9)">Mod. comp.</th>
      <th class="sortable" style="text-align:right;display:none" onclick="sortCouples(this,10)">Calidad</th>
      <th class="sortable" style="text-align:right;display:none" onclick="sortCouples(this,11)">Factor res.</th>
    </tr>
    <tr class="filter-row">
      <td></td>
      <td><select data-col="cat" onchange="filterCouples()">
        <option value="">Todas</option>
        <option value="elite">Élite</option>
        <option value="honor">Honor</option>
        <option value="primera">1ª Div.</option>
      </select></td>
      <td><input type="text" data-col="name" placeholder="buscar…" oninput="filterCouples()"></td>
      <td><input type="number" data-col="games" placeholder="≥" min="1" oninput="filterCouples()"></td>
      <td><input type="date" id="date-from" title="Desde" onchange="filterCouples()" style="width:100%"></td>
      <td><input type="date" id="date-to" title="Hasta" onchange="filterCouples()" style="width:100%"></td>
      <td><input type="number" data-col="total"   placeholder="≥" step="0.001" oninput="filterCouples()"></td>
      <td><input type="number" data-col="avg"     placeholder="≥" step="0.001" oninput="filterCouples()"></td>
      <td style="display:none"><input type="number" data-col="best"    placeholder="≥" step="0.001" oninput="filterCouples()"></td>
      <td style="display:none"><input type="number" data-col="cmod"    placeholder="≥" step="0.01"  oninput="filterCouples()"></td>
      <td style="display:none"><input type="number" data-col="quality" placeholder="≥" step="0.001" oninput="filterCouples()"></td>
      <td style="display:none"><input type="number" data-col="sf"      placeholder="≥" step="0.001" oninput="filterCouples()"></td>
    </tr>
  </thead>
  <tbody id="couples-body">
{couple_rows}
  </tbody>
</table>
</div>
</div><!-- /tab-couples -->

<!-- ── PROGRESSION ──────────────────────────────────────────────────────────── -->
<div id="tab-progression" class="tab-panel">
<div style="margin-bottom:1rem;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:0.75rem;">
  <div>
    <label style="display:block;color:#94a3b8;font-size:0.75rem;margin-bottom:0.3rem;font-weight:600;">Categoría:</label>
    <select id="prog-category" onchange="clearAndUpdateProgDropdown()" style="width:100%;padding:0.35rem;background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:0.3rem;font-size:0.85rem;">
      <option value="">Todas</option>
      <option value="elite">Élite</option>
      <option value="honor">Honor</option>
      <option value="primera">1ª División</option>
    </select>
  </div>
  <div>
    <label style="display:block;color:#94a3b8;font-size:0.75rem;margin-bottom:0.3rem;font-weight:600;">Género:</label>
    <select id="prog-gender" onchange="clearAndUpdateProgDropdown()" style="width:100%;padding:0.35rem;background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:0.3rem;font-size:0.85rem;">
      <option value="">Todos</option>
      <option value="M">Masculino</option>
      <option value="F">Femenino</option>
    </select>
  </div>
  <div>
    <label style="display:block;color:#94a3b8;font-size:0.75rem;margin-bottom:0.3rem;font-weight:600;">Mín. partidos:</label>
    <input type="number" id="prog-min-games" value="1" min="1" onchange="clearAndUpdateProgDropdown()" style="width:100%;padding:0.35rem;background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:0.3rem;font-size:0.85rem;">
  </div>
</div>
<div style="margin-bottom:1rem;position:relative;">
  <label style="display:block;color:#94a3b8;font-size:0.75rem;margin-bottom:0.3rem;font-weight:600;">Buscar y elegir parejas:</label>
  <input type="text" id="prog-search" placeholder="Escribe un nombre para filtrar…" onfocus="showProgDropdown()" oninput="updateProgDropdown()" style="width:100%;padding:0.35rem;background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:0.3rem;font-size:0.85rem;">
  <div id="prog-dropdown" style="display:none;position:absolute;top:100%;left:0;right:0;background:#1e293b;border:1px solid #334155;border-radius:0.3rem;max-height:300px;overflow-y:auto;z-index:1000;margin-top:0.25rem;">
  </div>
</div>
<div style="margin-bottom:1rem;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.3rem;">
    <label style="color:#94a3b8;font-size:0.75rem;font-weight:600;">Parejas seleccionadas:</label>
    <button onclick="clearProgSelection()" style="padding:0.2rem 0.6rem;background:#1e293b;border:1px solid #334155;color:#94a3b8;border-radius:0.3rem;cursor:pointer;font-size:0.75rem;">✕ Limpiar</button>
  </div>
  <div id="prog-selected" style="display:flex;flex-wrap:wrap;gap:0.5rem;min-height:2rem;padding:0.5rem;background:#0f172a;border:1px solid #334155;border-radius:0.3rem;">
    <span style="color:#94a3b8;font-size:0.8rem;">Ninguna seleccionada</span>
  </div>
</div>
<button onclick="drawProgression()" style="padding:0.5rem 1rem;background:#0ea5e9;color:white;border:none;border-radius:0.4rem;cursor:pointer;margin-bottom:1rem;">Mostrar</button>
<div style="position:relative;height:400px;margin-bottom:1rem;">
  <canvas id="progressionChart"></canvas>
</div>
<div id="prog-stats" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:0.75rem;margin-top:1rem;">
</div>
</div><!-- /tab-progression -->

<!-- ── GAMES ──────────────────────────────────────────────────────────────── -->
<div id="tab-games" class="tab-panel">
<div style="display:flex;align-items:center;justify-content:space-between;gap:0.75rem;flex-wrap:wrap;margin-bottom:0.75rem;">
  <span class="count-label" id="games-count-label" style="margin-bottom:0"></span>
  <div style="display:flex;gap:0.5rem;">
    <button class="season-btn active" id="gg-all" onclick="filterGameGender('all',this)">Todos</button>
    <button class="season-btn" id="gg-m" onclick="filterGameGender('M',this)">Masculino</button>
    <button class="season-btn" id="gg-f" onclick="filterGameGender('F',this)">Femenino</button>
  </div>
  <button onclick="clearAllGameFilters()" class="clear-all-btn">✕ Limpiar filtros</button>
</div>
<div class="section">
<table id="games-table">
  <thead>
    <tr>
      <th style="width:2.5rem">#</th>
      <th class="sortable sort-desc" style="text-align:right;width:85px" onclick="sortGames(this,1)">Fecha ▼</th>
      <th class="sortable" style="width:16%" onclick="sortGames(this,2)">Competición</th>
      <th class="sortable" style="width:14%" onclick="sortGames(this,3)">Fase</th>
      <th class="sortable" style="width:13%" onclick="sortGames(this,4)">Local</th>
      <th class="sortable" style="width:13%" onclick="sortGames(this,5)">Visitante</th>
      <th style="text-align:right;width:65px" title="Goles local – Goles visitante (Pend. = pendiente de disputar)">Result.</th>
      <th class="sortable" style="width:12%" onclick="sortGames(this,7)">Árbitro 1</th>
      <th class="sortable" style="width:12%" onclick="sortGames(this,8)">Árbitro 2</th>
      <th class="sortable" style="text-align:right;width:55px;display:none" onclick="sortGames(this,9)">Mod.</th>
      <th class="sortable" style="text-align:right;width:60px;display:none" onclick="sortGames(this,10)">Calidad</th>
      <th class="sortable" style="text-align:right;width:60px;display:none" onclick="sortGames(this,11)">Factor</th>
      <th class="sortable" style="text-align:right;width:60px" onclick="sortGames(this,12)">Score</th>
    </tr>
    <tr class="filter-row">
      <td></td>
      <td><div class="date-pair">
        <input type="date" id="gdate-from" title="Desde" onchange="filterGames()">
        <input type="date" id="gdate-to"   title="Hasta" onchange="filterGames()">
      </div></td>
      <td><select id="games-comp-filter" onchange="filterGamesComp(); filterGames()" style="width:100%;padding:0.25rem;background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:0.3rem;font-size:0.85rem;">
        <option value="">Todas</option>
{game_comp_options}
      </select></td>
      <td><select id="games-phase-filter" onchange="filterGames()" style="width:100%;padding:0.25rem;background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:0.3rem;font-size:0.85rem;">
        <option value="">Todas</option>
      </select></td>
      <td><input type="text" data-col="h"     placeholder="buscar…" oninput="filterGames()"></td>
      <td><input type="text" data-col="a"     placeholder="buscar…" oninput="filterGames()"></td>
      <td></td>
      <td><input type="text" data-col="ref1"  placeholder="buscar…" oninput="filterGames()"></td>
      <td><input type="text" data-col="ref2"  placeholder="buscar…" oninput="filterGames()"></td>
      <td style="display:none"><input type="number" data-col="cm" placeholder="≥" step="0.01"  oninput="filterGames()"></td>
      <td style="display:none"><input type="number" data-col="mq" placeholder="≥" step="0.001" oninput="filterGames()"></td>
      <td style="display:none"><input type="number" data-col="sf" placeholder="≥" step="0.001" oninput="filterGames()"></td>
      <td style="display:none"><input type="number" data-col="ns" placeholder="≥" step="0.001" oninput="filterGames()"></td>
    </tr>
  </thead>
  <tbody id="games-body">
{game_rows}
  </tbody>
</table>
</div>
</div><!-- /tab-games -->

<!-- ── MOVEMENTS ───────────────────────────────────────────────────────────── -->
<div id="tab-moves" class="tab-panel">
<div style="margin-bottom:0.75rem">
  <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.5rem;">
    <span style="color:#64748b;font-size:0.82rem">Transición:</span>
{moves_transition_btns}
  </div>
  <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
    <span style="color:#64748b;font-size:0.82rem">Ver:</span>
    <button class="season-btn active" id="mf-all"  onclick="filterMoves('all',this)">Todos</button>
    <button class="season-btn" id="mf-up"   onclick="filterMoves('up',this)"><span class="move-up">↑</span> Ascensos</button>
    <button class="season-btn" id="mf-down" onclick="filterMoves('down',this)"><span class="move-down">↓</span> Descensos</button>
    <button class="season-btn" id="mf-new"  onclick="filterMoves('new',this)"><span class="move-new">★</span> Nuevos</button>
    <button class="season-btn" id="mf-gone" onclick="filterMoves('gone',this)"><span class="move-gone">✗</span> Desaparecen</button>
    <span id="moves-count-label" style="color:#64748b;font-size:0.8rem;margin-left:auto"></span>
  </div>
  <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;margin-top:0.5rem;">
    <span style="color:#64748b;font-size:0.82rem">Categoría:</span>
    <select id="moves-category-filter" onchange="filterMovesCategory()" style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:0.35rem 0.7rem;border-radius:0.4rem;font-size:0.85rem;">
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
    <th style="text-align:right" title="Posición en su categoría durante la temporada del cambio (ej. 5/30 = 5º de 30 árbitros de Élite). Solo disponible para temporadas con datos de nominaciones.">Ranking</th>
  </tr></thead>
  <tbody id="moves-body">
{moves_rows}
  </tbody>
</table>
</div>
</div><!-- /tab-moves -->

<!-- ── ÁRBITROS ────────────────────────────────────────────────────────────── -->
<div id="tab-refs" class="tab-panel">
<div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.75rem;flex-wrap:wrap;">
  <input id="refs-search" type="text" placeholder="Buscar árbitro…"
    oninput="filterRefs()"
    style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;
           padding:0.35rem 0.7rem;border-radius:0.4rem;font-size:0.85rem;min-width:220px">
  <button class="season-btn active" id="rf-all"      onclick="filterRefType('all',this)">Todos</button>
  <button class="season-btn"        id="rf-variants" onclick="filterRefType('variants',this)">Con variantes</button>
  <span id="refs-count-label" style="color:#64748b;font-size:0.8rem;margin-left:auto"></span>
</div>
<p style="color:#64748b;font-size:0.78rem;margin-bottom:0.75rem">
  Nombre canónico tomado del PDF más reciente. Las variantes son los nombres
  que aparecen en otras temporadas con una ortografía diferente.
  Para corregir un emparejamiento incorrecto añade una entrada a
  <code>MANUAL_CROSS_ALIASES</code> en <code>config.py</code>.
</p>
<div class="section">
<table id="refs-table">
  <thead><tr>
    <th title="Nombre oficial según el PDF más reciente">Árbitro</th>
    <th title="Categoría en la temporada más reciente en que aparece">Cat.</th>
    <th title="Temporadas en que aparece en los PDFs de plantilla">Temporadas</th>
    <th title="Nombres distintos con que aparece en otras temporadas de PDF">Variantes de nombre</th>
  </tr></thead>
  <tbody id="refs-body">
{refs_rows}
  </tbody>
</table>
</div>
</div><!-- /tab-refs -->

<div id="c-tip"></div>
<div id="c-modal-bg"><div id="c-modal"></div></div>

<script>
const SEASON_LABELS = {{
  '2526': 'Temporada 2025/26',
  '2425': 'Temporada 2024/25',
  'all':  'Todas las temporadas',
}};
const SEASON_RANGE = {{
  '2526': '{fmt_date(stats_2526[0]["min_date"] if stats_2526 else "")} – {fmt_date(stats_2526[0]["max_date"] if stats_2526 else "")}',
  '2425': '{fmt_date(stats_2425[0]["min_date"] if stats_2425 else "")} – {fmt_date(stats_2425[0]["max_date"] if stats_2425 else "")}',
  'all':  '{fmt_date(overall["min_date"])} – {fmt_date(overall["max_date"])}',
}};

let _currentSeason = '2526';
// Games tab season filter stays in sync with season selector for consistency with other tabs
let _gamesSeasonFilter = '2526';
let _gamesGenderFilter = 'all';
let _couplesGenderFilter = 'all';

function setSeason(season, btn) {{
  _currentSeason = season;
  _gamesSeasonFilter = season;
  _progSelected.clear();  // Reset progression selection when season changes
  document.querySelectorAll('.season-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('season-label').textContent = SEASON_LABELS[season]||season;
  document.getElementById('season-range').textContent = 'Rango: '+(SEASON_RANGE[season]||'');
  document.querySelectorAll('.stats-panel').forEach(p=>p.style.display='none');
  document.getElementById('stats-'+season).style.display='block';
  filterCouples();
  filterGames();
  // Update progression tab if it exists
  if (document.getElementById('tab-progression')) {{
    updateProgDropdown();
  }}
}}

function filterGameGender(gender, btn) {{
  _gamesGenderFilter = gender;
  document.querySelectorAll('#gg-all, #gg-m, #gg-f').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  filterGames();
}}

function filterCoupleGender(gender, btn) {{
  _couplesGenderFilter = gender;
  document.querySelectorAll('#cg-all, #cg-m, #cg-f').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  filterCouples();
}}

function showTab(name, btn) {{
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  btn.classList.add('active');
}}

// ── Couple tooltip ────────────────────────────────────────────────────────
const COUPLE_GAMES = {_cg_js};
const COUPLE_PROGRESSION = {_pd_js};
const GAMES_FILTERS = {_gf_js};
const _cs = {{col:7, asc:false}};

function _getCG(row) {{ return COUPLE_GAMES[row.dataset.key] || []; }}

function showTooltip(row, e) {{
  const games = _getCG(row);
  if (!games.length) return;
  const names = Array.from(row.querySelectorAll('.couple-names div')).map(d=>d.textContent).join(' / ');
  let html = `<div class="tip-hdr">${{names}}</div><table>`;
  // already sorted date-desc from Python; show most recent 7
  games.slice(0,7).forEach(g => {{
    const score = g.sh!=null ? `${{g.sh}}–${{g.sa}}` : 'Pend.';
    const phase = (g.phase||'').replace(/^[^-]+-[ ]*/,'').substring(0,34);
    html += `<tr><td>${{g.dt}}</td>
      <td style="color:#94a3b8;max-width:150px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">${{phase}}</td>
      <td>${{g.h}} – ${{g.a}}</td>
      <td><b>${{score}}</b></td><td style="color:#22c55e">${{g.ns.toFixed(3)}}</td></tr>`;
  }});
  if (games.length>7) html += `<tr><td colspan="5" style="color:#475569">…y ${{games.length-7}} más</td></tr>`;
  html += '</table>';
  const tip = document.getElementById('c-tip');
  tip.innerHTML = html; tip.style.display='block'; reposTooltip(e);
}}

function reposTooltip(e) {{
  const tip = document.getElementById('c-tip');
  if (tip.style.display==='none') return;
  const x=e.clientX+18, y=e.clientY+18;
  tip.style.left=(x+tip.offsetWidth>window.innerWidth-8 ? e.clientX-tip.offsetWidth-10 : x)+'px';
  tip.style.top =(y+tip.offsetHeight>window.innerHeight-8? e.clientY-tip.offsetHeight-10: y)+'px';
}}

function hideTooltip() {{ document.getElementById('c-tip').style.display='none'; }}

// ── Couple modal ─────────────────────────────────────────────────────────
const _ms = {{col:-1, asc:false}};

function sortModal(th, colIdx) {{
  const tbody = document.getElementById('modal-games-body');
  if (!tbody) return;
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const asc = _ms.col===colIdx ? !_ms.asc : false;
  _ms.col=colIdx; _ms.asc=asc;
  document.querySelectorAll('#modal-games-table th').forEach(h=>h.classList.remove('sort-asc','sort-desc'));
  th.classList.add(asc?'sort-asc':'sort-desc');
  rows.sort((a,b) => {{
    const ca=a.cells[colIdx], cb=b.cells[colIdx];
    const va=(ca?.dataset.sort ?? ca?.textContent.trim().replace(/[—#,]/g,''))||'';
    const vb=(cb?.dataset.sort ?? cb?.textContent.trim().replace(/[—#,]/g,''))||'';
    const na=parseFloat(va), nb=parseFloat(vb);
    const cmp=(isNaN(na)||isNaN(nb)) ? va.localeCompare(vb,'es') : na-nb;
    return asc?cmp:-cmp;
  }});
  rows.forEach(r=>tbody.appendChild(r));
}}

function showModal(row) {{
  hideTooltip();
  // already sorted date-desc from Python
  const games = _getCG(row);
  const names = Array.from(row.querySelectorAll('.couple-names div')).map(d=>d.textContent).join(' / ');
  _ms.col=-1; _ms.asc=false;
  const colDefs = [
    {{label:'Fecha',       w:'7%',  align:'left'}},
    {{label:'Competición', w:'15%', align:'left'}},
    {{label:'Fase',        w:'14%', align:'left'}},
    {{label:'Partido',     w:'24%', align:'left'}},
    {{label:'Result.',     w:'8%',  align:'right'}},
    {{label:'Clasif.',     w:'10%', align:'right'}},
    {{label:'Score',       w:'8%',  align:'right'}},
  ];
  const thead = colDefs.map((c,i) =>
    `<th style="width:${{c.w}};text-align:${{c.align}}" onclick="sortModal(this,${{i}})">${{c.label}}</th>`
  ).join('');
  let tbody='';
  games.forEach(g => {{
    const score = g.sh!=null ? `${{g.sh}}–${{g.sa}}` : '—';
    const ranks = (g.rh && g.n>1) ? `${{g.rh}}º/${{g.ra}}º` : '—';
    tbody += `<tr>
      <td data-sort="${{g.dt}}">${{g.dt}}</td>
      <td class="dim" title="${{g.comp}}">${{g.comp}}</td>
      <td class="dim" style="font-size:.76rem" title="${{g.phase}}">${{g.phase}}</td>
      <td title="${{g.h}} – ${{g.a}}">${{g.h}} – ${{g.a}}</td>
      <td class="num"><b>${{score}}</b></td>
      <td class="num dim">${{ranks}}</td>
      <td class="num bold">${{g.ns.toFixed(3)}}</td></tr>`;
  }});
  document.getElementById('c-modal').innerHTML = `
    <button class="close-btn" onclick="closeModal()">×</button>
    <h3>${{names}}</h3>
    <p class="m-sub">${{games.length}} partido${{games.length!==1?'s':''}} juntos · Clic en cabecera para ordenar</p>
    <table id="modal-games-table">
      <thead><tr>${{thead}}</tr></thead>
      <tbody id="modal-games-body">${{tbody}}</tbody>
    </table>`;
  document.getElementById('c-modal-bg').style.display='block';
}}

function closeModal() {{ document.getElementById('c-modal-bg').style.display='none'; }}
document.getElementById('c-modal-bg').addEventListener('click', function(e) {{
  if (e.target===this) closeModal();
}});

// ── Couple filter / sort ─────────────────────────────────────────────────
function _fmtDate(d) {{
  if (!d) return '—';
  const [y,m,day]=d.split('-'); return day+'/'+m+'/'+y;
}}

function clearAllCoupleFilters() {{
  document.getElementById('date-from').value='';
  document.getElementById('date-to').value='';
  document.querySelectorAll('#couples-table .filter-row input[data-col]').forEach(el=>{{el.value='';}});
  document.querySelectorAll('#couples-table .filter-row select[data-col]').forEach(el=>{{el.value='';}});
  _couplesGenderFilter='all';
  document.getElementById('cg-all').click();
  filterCouples();
}}

function filterCouples() {{
  const fromDate = document.getElementById('date-from').value;
  const toDate   = document.getElementById('date-to').value;
  const hasDate  = fromDate || toDate;

  document.querySelectorAll('#couples-body tr').forEach(row => {{
    const all = _getCG(row);
    let gs = (_currentSeason !== 'all')
      ? all.filter(g => g.s === _currentSeason)
      : (hasDate ? all.filter(g=>(!fromDate||g.dt>=fromDate)&&(!toDate||g.dt<=toDate)) : all);
    if (_currentSeason !== 'all' && hasDate)
      gs = gs.filter(g=>(!fromDate||g.dt>=fromDate)&&(!toDate||g.dt<=toDate));
    if (_couplesGenderFilter !== 'all')
      gs = gs.filter(g => g.g === _couplesGenderFilter);
    const n = gs.length;
    if (n===0) {{
      row.dataset.games='0'; row.dataset.total='0'; row.dataset.avg='0';
      row.dataset.best='0'; row.dataset.cmod='0'; row.dataset.quality='0';
      row.dataset.sf='0'; row.dataset.first=''; row.dataset.last='';
      row.cells[3].textContent='0';
      for(let i=4;i<=11;i++) row.cells[i].textContent='—';
    }} else {{
      const tot=gs.reduce((s,g)=>s+g.ns,0);
      const avg=tot/n, best=Math.max(...gs.map(g=>g.ns));
      const acm=gs.reduce((s,g)=>s+g.cm,0)/n;
      const amq=gs.reduce((s,g)=>s+g.mq,0)/n;
      const asf=gs.reduce((s,g)=>s+g.sf,0)/n;
      const dates=gs.map(g=>g.dt).sort();
      const first=dates[0], last=dates[dates.length-1];
      row.dataset.games=n; row.dataset.total=tot.toFixed(3);
      row.dataset.avg=avg.toFixed(3); row.dataset.best=best.toFixed(3);
      row.dataset.cmod=acm.toFixed(2); row.dataset.quality=amq.toFixed(3);
      row.dataset.sf=asf.toFixed(3); row.dataset.first=first; row.dataset.last=last;
      row.cells[3].textContent=n;
      row.cells[4].textContent=_fmtDate(first);
      row.cells[5].textContent=_fmtDate(last);
      row.cells[6].textContent=tot.toFixed(3);
      row.cells[7].textContent=avg.toFixed(3);
      row.cells[8].textContent=best.toFixed(3);
      row.cells[9].textContent=acm.toFixed(2);
      row.cells[10].textContent=amq.toFixed(3);
      row.cells[11].textContent=asf.toFixed(3);
    }}
  }});

  const colF={{}};
  document.querySelectorAll('#couples-table .filter-row input[data-col], #couples-table .filter-row select[data-col]').forEach(el=>{{
    if (el.value.trim()) colF[el.dataset.col]=el.value.trim();
  }});
  let visible=0;
  document.querySelectorAll('#couples-body tr').forEach(row=>{{
    let show=!(hasDate && parseInt(row.dataset.games||0)===0);
    // Games are already filtered by gender when computing stats, so couples with no matching
    // gender games will show n=0. Hide those rows when a gender filter is active.
    if (show && _couplesGenderFilter !== 'all' && parseInt(row.dataset.games||0)===0) show=false;
    if (show) {{
      for (const [col,val] of Object.entries(colF)) {{
        if (col==='cat') {{
          if (row.dataset.cat!==val) {{show=false;break;}}
        }} else if (col==='name') {{
          const v=val.toLowerCase();
          if (!(row.dataset.refA||'').includes(v)&&!(row.dataset.refB||'').includes(v)) {{show=false;break;}}
        }} else if (col==='games') {{
          if (parseInt(row.dataset.games||0)<parseInt(val)) {{show=false;break;}}
        }} else {{
          const rv=parseFloat(row.dataset[col]);
          if (!isNaN(rv)&&rv<parseFloat(val)) {{show=false;break;}}
        }}
      }}
    }}
    row.style.display=show?'':'none';
    if (show) visible++;
  }});
  document.getElementById('couple-count-label').textContent=visible+' pareja'+(visible!==1?'s':'');
}}

function sortCouples(th, colIdx) {{
  const tbody=document.getElementById('couples-body');
  const rows=Array.from(tbody.querySelectorAll('tr'));
  const asc=_cs.col===colIdx ? !_cs.asc : (colIdx===2);
  _cs.col=colIdx; _cs.asc=asc;
  document.querySelectorAll('#couples-table th').forEach(h=>h.classList.remove('sort-asc','sort-desc'));
  th.classList.add(asc?'sort-asc':'sort-desc');
  rows.sort((a,b)=>{{
    if (colIdx===4) {{
      const va=a.dataset.first||'', vb=b.dataset.first||'';
      return asc?va.localeCompare(vb):vb.localeCompare(va);
    }}
    if (colIdx===5) {{
      const va=a.dataset.last||'', vb=b.dataset.last||'';
      return asc?va.localeCompare(vb):vb.localeCompare(va);
    }}
    if (colIdx===2) {{
      const va=a.dataset.refA||'', vb=b.dataset.refA||'';
      return asc?va.localeCompare(vb,'es'):vb.localeCompare(va,'es');
    }}
    const va=a.cells[colIdx]?.textContent.trim().replace(/[#,]/g,'')||'';
    const vb=b.cells[colIdx]?.textContent.trim().replace(/[#,]/g,'')||'';
    const na=parseFloat(va), nb=parseFloat(vb);
    const cmp=(isNaN(na)||isNaN(nb))?va.localeCompare(vb,'es'):na-nb;
    return asc?cmp:-cmp;
  }});
  rows.forEach(r=>tbody.appendChild(r));
  let rank=1;
  rows.forEach(r=>{{ if(r.style.display!=='none') r.cells[0].textContent='#'+rank++; }});
}}

try {{ filterCouples(); }} catch(e) {{ console.error('filterCouples init:', e); }}

// ── Games tab ────────────────────────────────────────────────────────────
const _gs={{col:1, asc:false}};

function sortGames(th, colIdx) {{
  const tbody=document.getElementById('games-body');
  const rows=Array.from(tbody.querySelectorAll('tr'));
  const defaultAsc=[2,3,4,5,7,8].includes(colIdx);
  const asc=_gs.col===colIdx ? !_gs.asc : defaultAsc;
  _gs.col=colIdx; _gs.asc=asc;
  document.querySelectorAll('#games-table th').forEach(h=>h.classList.remove('sort-asc','sort-desc'));
  th.classList.add(asc?'sort-asc':'sort-desc');
  rows.sort((a,b)=>{{
    const ca=a.cells[colIdx], cb=b.cells[colIdx];
    const va=(ca?.dataset.sort ?? ca?.textContent.trim().replace(/[#,—]/g,''))||'';
    const vb=(cb?.dataset.sort ?? cb?.textContent.trim().replace(/[#,—]/g,''))||'';
    const na=parseFloat(va), nb=parseFloat(vb);
    const cmp=(isNaN(na)||isNaN(nb))?va.localeCompare(vb,'es'):na-nb;
    return asc?cmp:-cmp;
  }});
  rows.forEach(r=>tbody.appendChild(r));
  let rank=1;
  rows.forEach(r=>{{ if(r.style.display!=='none') r.cells[0].textContent='#'+rank++; }});
}}

// ── Progression tab ───────────────────────────────────────────────────────
let progressionChart = null;
let _progSelected = new Set();
let _progChartDrawn = false;
let _progLastDrawnKey = '';  // serialised selection at last draw

function _progSelectionKey() {{
  return Array.from(_progSelected).sort().join('|');
}}

function updateProgButtonText() {{
  const btn = document.querySelector('#tab-progression button[onclick="drawProgression()"]');
  if (!btn) return;
  if (!_progChartDrawn) {{
    btn.textContent = 'Mostrar';
  }} else {{
    btn.textContent = _progSelectionKey() === _progLastDrawnKey ? 'Actualizar' : 'Actualizar *';
  }}
}}

function clearAndUpdateProgDropdown() {{
  _progSelected.clear();
  _progLastDrawnKey = '';
  _progChartDrawn = false;
  updateProgSelectedDisplay();
  updateProgButtonText();
  updateProgDropdown();
}}

function showProgDropdown() {{
  document.getElementById('prog-dropdown').style.display = 'block';
  updateProgDropdown();
}}

function _progSeasonData() {{
  const s = (_currentSeason === 'all' || !COUPLE_PROGRESSION[_currentSeason]) ? '{config.SEASON_ID}' : _currentSeason;
  return COUPLE_PROGRESSION[s] || {{}};
}}

function updateProgDropdown() {{
  const dropdown = document.getElementById('prog-dropdown');
  const seasonData = _progSeasonData();
  if (!seasonData || !Object.keys(seasonData).length) {{
    dropdown.innerHTML = '<div style="color:#94a3b8;padding:1rem;">No hay datos</div>';
    return;
  }}

  const category   = (document.getElementById('prog-category').value || '').toLowerCase();
  const gender     = document.getElementById('prog-gender').value || '';
  const minGames   = parseInt(document.getElementById('prog-min-games').value) || 1;
  const searchText = (document.getElementById('prog-search').value || '').toLowerCase();

  // Filter and sort couples — key is [refA, refB, comp]
  let couples = Object.entries(seasonData)
    .filter(([key, data]) => {{
      const catMatch   = !category || data.category === category;
      const genMatch   = !gender   || data.gender === gender;
      const gamesMatch = data.games >= minGames;
      const parsed = JSON.parse(key);
      const nameStr = (parsed[0] + ' ' + parsed[1]).toLowerCase();
      const searchMatch = !searchText || nameStr.includes(searchText);
      return catMatch && genMatch && gamesMatch && searchMatch;
    }})
    .map(([key, data]) => [JSON.parse(key), data])
    .sort((a, b) => a[0][0].localeCompare(b[0][0]));

  dropdown.innerHTML = '';

  // Auto-select elite on first load
  const autoSelect = !category && !gender && _progSelected.size === 0;

  // "Select all visible" header row
  const header = document.createElement('div');
  header.style.cssText = 'padding:0.4rem 0.5rem;border-bottom:2px solid #334155;display:flex;justify-content:space-between;align-items:center;background:#0f172a;position:sticky;top:0;z-index:1;';
  header.innerHTML = `<span style="color:#94a3b8;font-size:0.75rem;">${{couples.length}} pareja${{couples.length!==1?'s':''}}</span>
    <button style="padding:0.15rem 0.5rem;background:#0ea5e9;color:#0f172a;border:none;border-radius:0.25rem;cursor:pointer;font-size:0.75rem;font-weight:600;">Sel. todos</button>`;
  header.querySelector('button').onclick = (e) => {{
    e.stopPropagation();
    couples.forEach(([couple]) => _progSelected.add(JSON.stringify(couple)));
    updateProgDropdown();
    updateProgSelectedDisplay();
    updateProgButtonText();
  }};
  dropdown.appendChild(header);

  for (const [couple, data] of couples) {{
    const [refA, refB, comp] = couple;
    const coupleStr = refA + ' — ' + refB;
    const coupleKey = JSON.stringify(couple);
    const isSelected = _progSelected.has(coupleKey) || (autoSelect && data.category === 'elite');

    const levelColor = data.category === 'elite' ? '#7c3aed' : data.category === 'honor' ? '#0ea5e9' : '#10b981';
    const levelLabel = data.category === 'elite' ? 'Élite' : data.category === 'honor' ? 'Honor' : '1ª Div';
    const genderLabel = data.gender === 'F' ? '♀' : data.gender === 'M' ? '♂' : '?';

    const item = document.createElement('div');
    item.style.cssText = `padding:0.5rem;cursor:pointer;border-bottom:1px solid #1e293b;transition:background 0.1s;background:${{isSelected ? '#132040' : 'transparent'}};`;
    item.innerHTML = `
      <span style="color:${{levelColor}};font-weight:600;min-width:40px;">${{levelLabel}}</span>
      <span style="color:#94a3b8;margin:0 0.5rem;">${{genderLabel}}</span>
      <span>${{coupleStr}}</span>
      <span style="color:#64748b;font-size:0.75rem;margin-left:auto;">(${{data.games}})</span>
      <span style="color:${{isSelected ? '#0ea5e9' : '#475569'}};margin-left:0.5rem;font-size:1rem;">${{isSelected ? '✓' : '○'}}</span>
    `;

    item.onclick = (e) => {{
      e.stopPropagation();
      if (_progSelected.has(coupleKey)) _progSelected.delete(coupleKey);
      else _progSelected.add(coupleKey);
      updateProgDropdown();
      updateProgSelectedDisplay();
      updateProgButtonText();
    }};

    item.onmouseover = () => item.style.background = '#1e293b';
    item.onmouseout = () => item.style.background = _progSelected.has(coupleKey) ? '#132040' : 'transparent';

    dropdown.appendChild(item);
  }}

  if (autoSelect) {{
    for (const [couple, data] of couples) {{
      if (data.category === 'elite') _progSelected.add(JSON.stringify(couple));
    }}
    setTimeout(() => {{
      drawProgression();
      _progChartDrawn = true;
      updateProgButtonText();
      updateProgSelectedDisplay();
    }}, 100);
  }}

  updateProgSelectedDisplay();
}}

function updateProgSelectedDisplay() {{
  const container = document.getElementById('prog-selected');
  if (_progSelected.size === 0) {{
    container.innerHTML = '<span style="color:#94a3b8;font-size:0.8rem;">Ninguna seleccionada</span>';
    return;
  }}

  container.innerHTML = '';
  Array.from(_progSelected)
    .map(k => JSON.parse(k))
    .sort((a, b) => a[0].localeCompare(b[0]))
    .forEach(couple => {{
      const [refA, refB, comp] = couple;
      const coupleKey = JSON.stringify(couple);
      const tag = document.createElement('div');
      tag.style.cssText = 'display:flex;align-items:center;gap:0.3rem;background:#0ea5e9;color:#0f172a;padding:0.25rem 0.5rem;border-radius:0.25rem;font-size:0.8rem;font-weight:500;cursor:pointer;user-select:none;';
      tag.dataset.coupleKey = coupleKey;
      tag.title = 'Clic para eliminar';
      tag.innerHTML = `${{refA}} — ${{refB}} <span style="opacity:0.7;margin-left:0.2rem;">×</span>`;
      tag.onclick = () => removeProgCouple(coupleKey);
      tag.onmouseover = () => tag.style.background = '#38bdf8';
      tag.onmouseout = () => tag.style.background = '#0ea5e9';
      container.appendChild(tag);
    }});
}}

function removeProgCouple(coupleKey) {{
  _progSelected.delete(coupleKey);
  updateProgSelectedDisplay();
  updateProgDropdown();
}}

function clearProgSelection() {{
  _progSelected.clear();
  updateProgSelectedDisplay();
  updateProgDropdown();
}}

function drawProgression() {{
  const seasonData = _progSeasonData();
  if (!seasonData) {{
    if (progressionChart) progressionChart.destroy();
    document.getElementById('prog-stats').innerHTML = '<div style="color:#e2e8f0;padding:1rem;">No hay datos para esta temporada</div>';
    _progChartDrawn = false;
    return;
  }}

  const selected = Array.from(_progSelected).map(k => {{
    try {{
      return JSON.parse(k);
    }} catch (e) {{
      console.error('Error parsing couple key:', k, e);
      return null;
    }}
  }}).filter(c => c !== null);

  if (selected.length === 0) {{
    if (progressionChart) progressionChart.destroy();
    document.getElementById('prog-stats').innerHTML = '<div style="color:#e2e8f0;padding:1rem;">Selecciona al menos una pareja</div>';
    _progChartDrawn = false;
    return;
  }}

  _progChartDrawn = true;
  _progLastDrawnKey = _progSelectionKey();

  // Abbreviate a full name to initials: "ALBERTO GARCIA RODRIGUEZ" → "A.G.R."
  function initials(name) {{
    return name.trim().split(' ').filter(w => w.length > 0).map(w => w[0].toUpperCase()).join('.');
  }}

  const colors = ['#0ea5e9', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#eab308',
                  '#f97316', '#a3e635', '#22d3ee', '#e879f9', '#fb7185', '#4ade80', '#facc15', '#60a5fa'];
  let colorIdx = 0;

  // Read current filters
  const _fCat = (document.getElementById('prog-category').value || '').toLowerCase();
  const _fGen = document.getElementById('prog-gender').value || '';
  const _fMin = parseInt(document.getElementById('prog-min-games').value) || 1;

  // Build avg carry-forward for every eligible couple (for rank recomputation)
  const eligibleAvg = {{}};
  for (const [key, kd] of Object.entries(seasonData)) {{
    const catOk = !_fCat || kd.category === _fCat;
    const genOk = !_fGen || kd.gender === _fGen;
    if (!catOk || !genOk || kd.games < _fMin) continue;
    const prog = kd.progression;
    eligibleAvg[key] = (d) => {{
      let v = null;
      for (const p of prog) {{
        if (p.date <= d) v = p.avg;
        else break;
      }}
      return v;
    }};
  }}
  const eligibleKeys = Object.keys(eligibleAvg);

  // First pass: collect all dates
  let allLabels = new Set();
  for (const couple of selected) {{
    const data = seasonData[JSON.stringify(couple)];
    if (!data || !data.progression) continue;
    data.progression.forEach(p => allLabels.add(p.date));
    if (data.season_end) allLabels.add(data.season_end);
  }}
  const labels = Array.from(allLabels).sort();

  // Second pass: build datasets
  const datasets = [];
  const fullNames = [];  // keep for tooltip

  for (const couple of selected) {{
    const coupleKey = JSON.stringify(couple);
    const data = seasonData[coupleKey];
    if (!data || !data.progression) continue;

    // Use last_game_date (actual game) for dashed-line start
    const lastGameDate = data.last_game_date || data.progression[data.progression.length - 1]?.date;
    const lastRealIdx = lastGameDate ? labels.indexOf(lastGameDate) : -1;

    // Build avg+rank carry-forward directly from this couple's progression entries
    const progMap = {{}};
    data.progression.forEach(p => {{ progMap[p.date] = {{ rank: p.rank, avg: p.avg }}; }});
    let carryRank = null, carryAvg = null;

    const chartData = labels.map(d => {{
      if (d in progMap) {{ carryRank = progMap[d].rank; carryAvg = progMap[d].avg; }}
      if (carryAvg === null) return null;  // not played yet

      if (_fMin <= 1 && !_fCat && !_fGen) return carryRank;  // use pre-computed

      // Recompute rank within the eligible set at this date
      let rank = 1;
      for (const eKey of eligibleKeys) {{
        if (eKey === coupleKey) continue;
        const otherAvg = eligibleAvg[eKey](d);
        if (otherAvg !== null && otherAvg > carryAvg) rank++;
      }}
      return rank;
    }});

    const color = colors[colorIdx % colors.length];
    colorIdx++;
    const lri = lastRealIdx;  // capture for closure

    datasets.push({{
      label: initials(couple[0]) + ' – ' + initials(couple[1]),  // couple[2] = comp
      data: chartData,
      borderColor: color,
      borderWidth: 2,
      tension: 0.3,
      fill: false,
      spanGaps: true,
      pointRadius: 0,
      pointHoverRadius: 0,
      pointHitRadius: 20,
      segment: {{
        borderDash: ctx => (lri >= 0 && ctx.p0DataIndex >= lri) ? [5, 5] : undefined,
      }},
    }});
    fullNames.push(couple[0] + ' — ' + couple[1]);
  }}

  if (progressionChart) progressionChart.destroy();

  // Snapshot original colors for clean restore during hover
  const origColors = datasets.map(ds => ds.borderColor);

  function _showHighlight(chart, idx) {{
    chart.data.datasets.forEach((ds, i) => {{
      ds.borderWidth = i === idx ? 4 : 1;
      ds.borderColor = i === idx ? origColors[i] : origColors[i] + '22';
    }});
    chart.update('none');
  }}
  function _clearHighlight(chart) {{
    chart.data.datasets.forEach((ds, i) => {{
      ds.borderWidth = 2;
      ds.borderColor = origColors[i];
    }});
    chart.update('none');
  }}

  const ctx = document.getElementById('progressionChart').getContext('2d');
  progressionChart = new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: labels,
      datasets: datasets
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: 'nearest', intersect: false }},
      plugins: {{
        legend: {{
          labels: {{ color: '#e2e8f0', font: {{ size: 11 }}, boxWidth: 14 }},
          display: true,
          position: 'right',
          onHover: (event, item, legend) => {{
            const hovIdx = item.datasetIndex ?? item.index;
            let tip = document.getElementById('_prog_leg_tip');
            if (!tip) {{
              tip = document.createElement('div');
              tip.id = '_prog_leg_tip';
              tip.style.cssText = 'position:fixed;background:#0f172a;color:#e2e8f0;padding:0.35rem 0.6rem;border-radius:0.3rem;font-size:0.82rem;pointer-events:none;z-index:9999;border:1px solid #334155;white-space:nowrap;';
              document.body.appendChild(tip);
            }}
            tip.textContent = fullNames[hovIdx] || item.text;
            tip.style.display = 'block';
            const cx = event.native.clientX, cy = event.native.clientY;
            if (cx > window.innerWidth / 2) {{
              tip.style.left = '';
              tip.style.right = (window.innerWidth - cx + 12) + 'px';
            }} else {{
              tip.style.right = '';
              tip.style.left = (cx + 12) + 'px';
            }}
            tip.style.top = (cy - 10) + 'px';
            _showHighlight(legend.chart, hovIdx);
          }},
          onLeave: (event, item, legend) => {{
            const tip = document.getElementById('_prog_leg_tip');
            if (tip) tip.style.display = 'none';
            _clearHighlight(legend.chart);
          }},
        }},
        tooltip: {{
          callbacks: {{
            title: items => fullNames[items[0]?.datasetIndex] || items[0]?.dataset.label || '',
            label: ctx => ctx.label + '   →   #' + ctx.parsed.y
          }},
          titleFont: {{ size: 13, weight: 'bold' }},
          bodyFont: {{ size: 12 }},
          padding: 10,
        }}
      }},
      onHover: (event, elements, chart) => {{
        if (elements.length > 0) {{
          _showHighlight(chart, elements[0].datasetIndex);
        }} else {{
          _clearHighlight(chart);
        }}
      }},
      scales: {{
        x: {{
          ticks: {{ color: '#94a3b8', maxRotation: 45 }},
          grid: {{ color: '#1e293b' }}
        }},
        y: {{
          ticks: {{ color: '#94a3b8', stepSize: 1, precision: 0, callback: v => v >= 1 ? v : '' }},
          grid: {{ color: '#1e293b' }},
          title: {{ display: true, text: 'Ranking (menor es mejor)', color: '#94a3b8' }},
          reverse: true,
          min: 0
        }}
      }}
    }}
  }});

  document.getElementById('prog-stats').innerHTML = `<div class="card"><div class="card-label">Parejas mostradas</div><div class="card-value">${{selected.length}}</div></div>`;
  updateProgButtonText();
}}

// Initialize on load
// (progression init is handled at the bottom of script)

function filterGamesComp() {{
  const compSel = document.getElementById('games-comp-filter');
  const phaseSel = document.getElementById('games-phase-filter');
  const comp = compSel.value;

  // Clear and repopulate phase dropdown
  phaseSel.innerHTML = '<option value="">Todas</option>';
  if (comp && GAMES_FILTERS[comp]) {{
    for (const phase of GAMES_FILTERS[comp]) {{
      const opt = document.createElement('option');
      opt.value = phase.toLowerCase();
      opt.textContent = phase;
      phaseSel.appendChild(opt);
    }}
  }}
}}

function clearAllGameFilters() {{
  document.getElementById('gdate-from').value='';
  document.getElementById('gdate-to').value='';
  document.getElementById('games-comp-filter').value='';
  document.getElementById('games-phase-filter').value='';
  document.querySelectorAll('#games-table .filter-row input[data-col]').forEach(el=>{{el.value='';}});
  _gamesGenderFilter='all';
  document.getElementById('gg-all').click();
  filterGames();
}}

function filterGames() {{
  const fromDate=document.getElementById('gdate-from').value;
  const toDate  =document.getElementById('gdate-to').value;
  const comp = (document.getElementById('games-comp-filter').value||'').toLowerCase();
  const phase = (document.getElementById('games-phase-filter').value||'').toLowerCase();
  const colF={{}};
  document.querySelectorAll('#games-table .filter-row input[data-col]').forEach(el=>{{
    if (el.value.trim()) colF[el.dataset.col]=el.value.trim().toLowerCase();
  }});
  let visible=0;
  document.querySelectorAll('#games-body tr').forEach(row=>{{
    const dt=row.dataset.date||'';
    let show=true;
    if (_gamesSeasonFilter !== 'all' && row.dataset.season !== _gamesSeasonFilter) show=false;
    if (show && _gamesGenderFilter !== 'all' && row.dataset.gender !== _gamesGenderFilter) show=false;
    if (show && comp && !(row.dataset.comp||'').includes(comp)) show=false;
    if (show && phase && !(row.dataset.phase||'').includes(phase)) show=false;
    if (show && fromDate && dt<fromDate) show=false;
    if (show && toDate   && dt>toDate)   show=false;
    if (show) {{
      for (const [col,val] of Object.entries(colF)) {{
        if (['h','a','ref1','ref2'].includes(col)) {{
          if (!(row.dataset[col]||'').includes(val)) {{show=false;break;}}
        }} else {{
          const rv=parseFloat(row.dataset[col]||'0');
          if (!isNaN(rv)&&rv<parseFloat(val)) {{show=false;break;}}
        }}
      }}
    }}
    row.style.display=show?'':'none';
    if (show) visible++;
  }});
  document.getElementById('games-count-label').textContent=visible+' partido'+(visible!==1?'s':'');
}}

try {{ filterGames(); }} catch(e) {{ console.error('filterGames init:', e); }}

// ── Movements tab ─────────────────────────────────────────────────────────
const MOVES_WITH_DATA = {moves_with_data_js};
let _movesTransition = '{default_transition}';
let _movesType = 'all';
let _movesCategory = '';

function _applyMoveFilters() {{
  let visible=0;
  const rows = document.querySelectorAll('#moves-body tr');
  rows.forEach(row=>{{
    const rowTransition = row.getAttribute('data-transition') || '';
    const rowType = row.getAttribute('data-type') || '';
    const rowCategory = row.getAttribute('data-category') || '';
    const matchT = rowTransition === _movesTransition;
    const matchM = _movesType === 'all' || rowType === _movesType;
    const matchC = !_movesCategory || rowCategory === _movesCategory;
    const show = matchT && matchM && matchC;
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  }});
  document.getElementById('moves-count-label').textContent =
    visible + ' árbitro' + (visible!==1?'s':'');
  // Update column headers
  const parts = _movesTransition.split('-');
  const so = parts[0], sn = parts[1];
  document.getElementById('moves-th-old').textContent = so.slice(0,2)+'/'+so.slice(2);
  document.getElementById('moves-th-new').textContent = sn.slice(0,2)+'/'+sn.slice(2);
  const hasData = MOVES_WITH_DATA[_movesTransition];
  document.getElementById('moves-th-noms-old').textContent  = hasData ? 'Noms '+so.slice(0,2)+'/'+so.slice(2) : '';
  document.getElementById('moves-th-score-old').textContent = hasData ? 'Score '+so.slice(0,2)+'/'+so.slice(2) : '';
  document.getElementById('moves-th-noms-new').textContent  = hasData ? 'Noms '+sn.slice(0,2)+'/'+sn.slice(2) : '';
  document.getElementById('moves-th-score-new').textContent = hasData ? 'Score '+sn.slice(0,2)+'/'+sn.slice(2) : '';
}}

function setMovesTransition(key, btn) {{
  _movesTransition = key;
  document.querySelectorAll('#tab-moves .trans-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  _applyMoveFilters();
}}

function filterMoves(type, btn) {{
  _movesType = type;
  document.querySelectorAll('#tab-moves .season-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  _applyMoveFilters();
}}

function filterMovesCategory() {{
  _movesCategory = document.getElementById('moves-category-filter').value;
  _applyMoveFilters();
}}

try {{ _applyMoveFilters(); }} catch(e) {{ console.error('_applyMoveFilters init:', e); }}

// ── Árbitros tab ──────────────────────────────────────────────────────────
let _refType = 'all';
function filterRefType(type, btn) {{
  _refType = type;
  document.querySelectorAll('#tab-refs .season-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  filterRefs();
}}
function filterRefs() {{
  const q = (document.getElementById('refs-search').value||'').toLowerCase();
  let visible=0;
  document.querySelectorAll('#refs-body tr').forEach(row=>{{
    const matchType = _refType==='all' || row.dataset.hasVariants==='1';
    const matchQ = !q || (row.dataset.name||'').includes(q);
    const show = matchType && matchQ;
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  }});
  document.getElementById('refs-count-label').textContent =
    visible + ' árbitro' + (visible!==1?'s':'');
}}
try {{ filterRefs(); }} catch(e) {{ console.error('filterRefs init:', e); }}

// Close progression dropdown when clicking outside
document.addEventListener('click', (e) => {{
  const dropdown = document.getElementById('prog-dropdown');
  const searchBox = document.getElementById('prog-search');
  if (dropdown && !dropdown.contains(e.target) && !searchBox.contains(e.target)) {{
    dropdown.style.display = 'none';
  }}
}});

// Initialize progression tab
if (document.getElementById('tab-progression')) {{
  updateProgDropdown();
}}
</script>
</body>
</html>"""


if __name__ == "__main__":
    overall, by_category, by_competition = build_stats()
    stats_2526 = build_stats("2526")
    stats_2425 = build_stats("2425")
    couples       = build_couple_rankings()
    couple_games  = build_all_couple_games()
    all_games     = build_all_games()
    all_movements = build_referee_movements()
    identities    = build_referee_identities()
    progression_data = build_couple_progression_by_season()
    games_filters = build_games_filters()
    html = render_html(overall, by_category, by_competition, couples, couple_games, all_games,
                       stats_2526=stats_2526, stats_2425=stats_2425,
                       all_movements=all_movements, identities=identities,
                       progression_data=progression_data, games_filters=games_filters)
    out = Path("output/dashboard.html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Dashboard written to {out}")
    print(f"  {overall['total_matches']} matches · {len(by_competition)} torneos · "
          f"{len(by_category)} categories · {len(couples)} couples ranked")
