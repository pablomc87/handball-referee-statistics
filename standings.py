"""Compute handball standings from match results stored in the DB."""

from datetime import date, timedelta
from functools import lru_cache

import db
import config


def _add_result(table: dict, team: str, gf: int, ga: int, pts: int) -> None:
    if team not in table:
        table[team] = {"pts": 0, "gf": 0, "ga": 0}
    table[team]["pts"] += pts
    table[team]["gf"] += gf
    table[team]["ga"] += ga


def _sort_table(table: dict) -> list[str]:
    return sorted(
        table,
        key=lambda t: (table[t]["pts"], table[t]["gf"] - table[t]["ga"], table[t]["gf"]),
        reverse=True,
    )


def _build_table(matches: list[dict]) -> dict:
    table: dict = {}
    for m in matches:
        sh, sa = m["score_home"], m["score_away"]
        if sh > sa:
            _add_result(table, m["home_team"], sh, sa, 2)
            _add_result(table, m["away_team"], sa, sh, 0)
        elif sh < sa:
            _add_result(table, m["home_team"], sh, sa, 0)
            _add_result(table, m["away_team"], sa, sh, 2)
        else:
            _add_result(table, m["home_team"], sh, sa, 1)
            _add_result(table, m["away_team"], sa, sh, 1)
    return table


@lru_cache(maxsize=None)
def compute_final_standings(torneo_id: int) -> tuple[dict[str, int], int]:
    """
    Final standings for a torneo using ALL completed matches (no date cutoff).
    Used as fallback when a team has no results at the snapshot cutoff.
    """
    matches = db.get_all_finalizado_matches_in_torneo(torneo_id)
    all_teams = db.get_all_teams_in_torneo(torneo_id)
    n = len(all_teams)
    table = _build_table(matches)
    sorted_teams = _sort_table(table)
    rankings = {team: i + 1 for i, team in enumerate(sorted_teams)}
    mid = n // 2 + 1
    for team in all_teams:
        if team not in rankings:
            rankings[team] = mid
    return rankings, n


@lru_cache(maxsize=None)
def compute_standings(torneo_id: int, cutoff_date: str) -> tuple[dict[str, int], int]:
    """
    Standings for a torneo using only matches played before cutoff_date.
    For teams with no results at that date, falls back to their final-season
    standings (where they ended up at the end of the season) instead of
    assigning an uninformative middle rank.
    """
    matches = db.get_finalizado_matches_before(torneo_id, cutoff_date)
    all_teams = db.get_all_teams_in_torneo(torneo_id)
    n = len(all_teams)

    table = _build_table(matches)
    sorted_teams = _sort_table(table)
    rankings = {team: i + 1 for i, team in enumerate(sorted_teams)}

    teams_without_data = all_teams - set(table.keys())
    if teams_without_data:
        final_ranks, _ = compute_final_standings(torneo_id)
        for team in teams_without_data:
            rankings[team] = final_ranks.get(team, n // 2 + 1)

    return rankings, n


def get_match_standings(
    match: dict,
    torneo: dict,
) -> tuple[int, int, int]:
    """
    Return (rank_home, rank_away, n_teams) for a match, using standings
    STANDINGS_LAG_DAYS before the match date.

    For playoff / cup matches, searches the regular season of the same
    category and season. Falls back to (n//2, n//2, n) if no data available.
    """
    match_date = match["date"]
    if not match_date:
        return (1, 1, 1)

    try:
        cutoff = (date.fromisoformat(match_date) - timedelta(days=config.STANDINGS_LAG_DAYS)).isoformat()
    except ValueError:
        return (1, 1, 1)
    torneo_name = (torneo.get("torneo_name") or "").upper()
    season_id = torneo.get("season_id", config.SEASON_ID)

    if "LIGA REGULAR" in torneo_name:
        ranks, n = compute_standings(torneo["torneo_id"], cutoff)
    else:
        # Playoff / cup: find regular season torneos in same category + season
        cat = torneo["categoria_name"]
        reg_torneos = db.get_regular_season_torneos_for_category(cat, season_id)
        if not reg_torneos:
            return (1, 1, 2)

        # Build combined standings at cutoff
        combined_cutoff: dict = {}
        combined_final: dict = {}
        all_teams: set = set()

        for rt in reg_torneos:
            rt_all = db.get_all_teams_in_torneo(rt["torneo_id"])
            all_teams |= rt_all

            for m in db.get_finalizado_matches_before(rt["torneo_id"], cutoff):
                sh, sa = m["score_home"], m["score_away"]
                if sh > sa:
                    _add_result(combined_cutoff, m["home_team"], sh, sa, 2)
                    _add_result(combined_cutoff, m["away_team"], sa, sh, 0)
                elif sh < sa:
                    _add_result(combined_cutoff, m["home_team"], sh, sa, 0)
                    _add_result(combined_cutoff, m["away_team"], sa, sh, 2)
                else:
                    _add_result(combined_cutoff, m["home_team"], sh, sa, 1)
                    _add_result(combined_cutoff, m["away_team"], sa, sh, 1)

            for m in db.get_all_finalizado_matches_in_torneo(rt["torneo_id"]):
                sh, sa = m["score_home"], m["score_away"]
                if sh > sa:
                    _add_result(combined_final, m["home_team"], sh, sa, 2)
                    _add_result(combined_final, m["away_team"], sa, sh, 0)
                elif sh < sa:
                    _add_result(combined_final, m["home_team"], sh, sa, 0)
                    _add_result(combined_final, m["away_team"], sa, sh, 2)
                else:
                    _add_result(combined_final, m["home_team"], sh, sa, 1)
                    _add_result(combined_final, m["away_team"], sa, sh, 1)

        n = max(len(all_teams), 2)
        final_sorted = _sort_table(combined_final)
        final_ranks = {team: i + 1 for i, team in enumerate(final_sorted)}

        cutoff_sorted = _sort_table(combined_cutoff)
        ranks = {team: i + 1 for i, team in enumerate(cutoff_sorted)}
        for team in all_teams:
            if team not in ranks:
                ranks[team] = final_ranks.get(team, n // 2 + 1)

    n = max(n, 2)
    home = ranks.get(match["home_team"], n // 2 + 1)
    away = ranks.get(match["away_team"], n // 2 + 1)

    # For non-regular-season torneos (playoffs, cups) the combined standings
    # span all regular-season groups, so ranks can exceed the actual group
    # size of the torneo being scored.  Ranks beyond the playoff group size
    # are meaningless — replace them with the neutral mid-table rank.
    if "LIGA REGULAR" not in torneo_name:
        n_torneo = len(db.get_all_teams_in_torneo(torneo["torneo_id"]))
        if n_torneo > 1:
            if home > n_torneo:
                home = n_torneo // 2 + 1
            if away > n_torneo:
                away = n_torneo // 2 + 1
            n = n_torneo

    return home, away, n
