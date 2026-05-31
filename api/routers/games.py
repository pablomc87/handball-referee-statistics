from fastapi import APIRouter, Depends, Query
import sqlite3
from api.deps import get_db
from api import queries

router = APIRouter()


@router.get("/games")
def list_games(
    season:      str | None = Query(None),
    date_from:   str | None = Query(None),
    date_to:     str | None = Query(None),
    competition: str | None = Query(None),
    phase:       str | None = Query(None),
    home:        str | None = Query(None),
    away:        str | None = Query(None),
    ref:         str | None = Query(None),
    gender:      str | None = Query(None),
    page:        int = Query(1, ge=1),
    per_page:    int = Query(50, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_db),
):
    return queries.get_games(conn, season, date_from, date_to, competition,
                             phase, home, away, ref, gender, page, per_page)


@router.get("/competitions")
def list_competitions(
    season: str | None = Query(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    return queries.get_competitions(conn, season)
