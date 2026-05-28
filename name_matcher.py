"""Fuzzy-match DB referee name strings against the PDF catalog."""

import unicodedata

from rapidfuzz import process, fuzz

import config
import db


def _normalize(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    return " ".join(sorted(ascii_str.lower().split()))  # sort tokens for token-set match


def build_name_map(season_id: str | None = None) -> dict[str, dict | None]:
    """
    Returns {db_referee_name: catalog_entry | None}.
    Checks MANUAL_ALIASES first, then falls back to fuzzy token-sort matching.
    """
    catalog = db.get_catalog(season_id=season_id)
    if not catalog:
        return {}

    catalog_by_id = {e["id"]: e for e in catalog}
    catalog_keys = [_normalize(e["normalized"]) for e in catalog]

    db_names = db.get_all_referee_names()
    result: dict[str, dict | None] = {}

    for name in db_names:
        if name in config.MANUAL_ALIASES:
            result[name] = catalog_by_id.get(config.MANUAL_ALIASES[name])
            continue

        query = _normalize(name)
        match = process.extractOne(
            query,
            catalog_keys,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=config.MATCH_THRESHOLD,
        )
        if match:
            best_key, score, idx = match
            result[name] = catalog[idx]
        else:
            result[name] = None

    return result
