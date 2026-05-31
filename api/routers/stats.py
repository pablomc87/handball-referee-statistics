from fastapi import APIRouter, Depends, Query
import sqlite3
from api.deps import get_db
from api import queries, cache

router = APIRouter()


@router.get("/stats")
def get_stats(
    season: str | None = Query(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    key = f"stats:{season or 'all'}"
    cached = cache.cache.get(key)
    if cached is not None:
        return cached
    result = queries.get_stats(conn, season)
    cache.cache.set(key, result, ttl=3600)
    return result
