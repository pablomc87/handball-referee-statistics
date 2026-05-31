"""Shared utilities used by API routers and optionally by dashboard.py."""
import sqlite3
import config

CAT_RANK  = {"elite": 0, "honor": 1, "primera": 2, "?": 3}
CAT_COLOR = {"elite": "#7c3aed", "honor": "#0ea5e9", "primera": "#10b981", "?": "#64748b"}
CAT_LABEL = {"elite": "Élite", "honor": "Honor", "primera": "1ª Div", "?": "—"}

ALLOWED_COUPLE_SORT = {"avg_score", "total_score", "best_score", "games", "first_game", "last_game"}
ALLOWED_CAT         = {"elite", "honor", "primera"}
ALLOWED_GENDER      = {"M", "F"}


def season_label(s: str) -> str:
    return f"{s[:2]}/{s[2:]}"


def gender_from_categoria(name: str) -> str:
    n = (name or "").upper()
    if "FEMENIN" in n:
        return "F"
    if "MASCULIN" in n:
        return "M"
    return ""


def best_cat(cat_a: str, cat_b: str) -> str:
    a = cat_a or "?"
    b = cat_b or "?"
    return a if CAT_RANK.get(a, 9) <= CAT_RANK.get(b, 9) else b


def get_seasons_with_data(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT season_id FROM torneos").fetchall()
    have = {r[0] for r in rows}
    return [s for s in config.CATALOG_SEASONS if s in have]
