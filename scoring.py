"""Compute nomination scores for every referee/match pair."""

import db
import config
import standings as standings_mod
import name_matcher


def _phase_multiplier(torneo_name: str) -> float:
    t = torneo_name.upper()
    for keyword, mult in config.PHASE_MULTIPLIERS:
        if keyword in t:
            return mult
    return 1.0  # LIGA REGULAR and unknown


def _gender_multiplier(categoria_name: str) -> float:
    return 1.0 if "MASCULIN" in categoria_name.upper() else config.WOMEN_MULTIPLIER


def _tier_multiplier(categoria_name: str) -> float:
    cat = categoria_name.upper()
    for keyword, mult in config.TIER_MODIFIERS:
        if keyword in cat:
            return mult
    return 1.0  # top division (ASOBAL, Liga Guerreras Iberdrola)


def competition_modifier(torneo: dict) -> float:
    cat = torneo["categoria_name"]
    # tier is intentionally excluded here — it's folded into match_quality
    # so that the Calidad column reflects absolute competition level
    return _gender_multiplier(cat) * _phase_multiplier(torneo["torneo_name"])


def match_quality(rank_home: int, rank_away: int, n: int, tier_mod: float = 1.0) -> float:
    if n <= 1:
        return tier_mod
    closeness = 1.0 / (1.0 + abs(rank_home - rank_away))
    prestige = (2 * n - rank_home - rank_away + 2) / (2 * n)
    return round(closeness * prestige * tier_mod, 4)


def score_factor(match: dict) -> float:
    sh, sa = match.get("score_home"), match.get("score_away")
    if sh is None or sa is None:
        return 1.0
    goal_diff = abs(sh - sa)
    return round(1.0 / (1.0 + goal_diff / config.MARGIN_NORM), 4)


def compute_all_scores() -> int:
    """
    For every match with at least one referee, compute and store nomination scores.
    Returns number of score rows written.
    """
    name_map = name_matcher.build_name_map(season_id=config.SEASON_ID)

    # Load all needed data in one query
    with db._conn() as conn:
        rows = conn.execute("""
            SELECT
                m.match_id, m.torneo_id, m.home_team, m.away_team,
                m.date, m.score_home, m.score_away, m.status,
                t.categoria_name, t.competicion_name, t.torneo_name,
                t.cat_id, t.comp_id,
                r.referee_1, r.referee_2
            FROM matches m
            JOIN torneos t ON t.torneo_id = m.torneo_id
            LEFT JOIN referees r ON r.match_id = m.match_id
            WHERE r.referee_1 IS NOT NULL AND r.referee_1 != ''
        """).fetchall()

    score_rows: list[dict] = []

    for row in rows:
        match = dict(row)
        torneo = {k: match[k] for k in ("torneo_id", "cat_id", "comp_id",
                                         "categoria_name", "competicion_name", "torneo_name")}

        comp_mod = competition_modifier(torneo)
        tier_mod = _tier_multiplier(torneo["categoria_name"])
        rank_home, rank_away, n = standings_mod.get_match_standings(match, torneo)
        mq = match_quality(rank_home, rank_away, n, tier_mod)
        sf = score_factor(match)
        nom_score = round(comp_mod * mq * sf, 4)

        for ref_field in ("referee_1", "referee_2"):
            ref_name = match.get(ref_field, "")
            if not ref_name:
                continue
            catalog_entry = name_map.get(ref_name)
            score_rows.append({
                "match_id": match["match_id"],
                "referee_name": ref_name,
                "catalog_id": catalog_entry["id"] if catalog_entry else None,
                "competition_mod": comp_mod,
                "match_quality": mq,
                "score_factor": sf,
                "nomination_score": nom_score,
                "rank_home": rank_home,
                "rank_away": rank_away,
                "n_teams": n,
            })

    db.upsert_nomination_scores(score_rows)
    return len(score_rows)
