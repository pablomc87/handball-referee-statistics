from fastapi import APIRouter, Depends, Query, HTTPException
import sqlite3
from api.deps import get_db
from api import queries
from api.utils import ALLOWED_COUPLE_SORT, ALLOWED_CAT, ALLOWED_GENDER

router = APIRouter()


@router.get("/couples")
def list_couples(
    season:    str = Query("all"),
    cat:       str | None = Query(None),
    gender:    str | None = Query(None),
    min_games: int = Query(1, ge=1),
    name:      str | None = Query(None),
    sort_by:   str = Query("avg_score"),
    sort_dir:  str = Query("desc"),
    page:      int = Query(1, ge=1),
    per_page:  int = Query(50, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_db),
):
    if cat and cat not in ALLOWED_CAT:
        raise HTTPException(400, f"cat must be one of {ALLOWED_CAT}")
    if gender and gender not in ALLOWED_GENDER:
        raise HTTPException(400, f"gender must be M or F")
    if sort_by not in ALLOWED_COUPLE_SORT:
        sort_by = "avg_score"
    return queries.get_couples(conn, season, cat, gender, min_games, name, sort_by, sort_dir, page, per_page)


@router.get("/couples/games")
def couple_games(
    ref_a: str = Query(...),
    ref_b: str = Query(...),
    conn: sqlite3.Connection = Depends(get_db),
):
    return queries.get_couple_games(conn, ref_a, ref_b)
