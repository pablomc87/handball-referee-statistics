from fastapi import APIRouter, Depends, Query
import sqlite3
from api.deps import get_db
from api import queries, cache

router = APIRouter()


@router.get("/referees")
def list_referees(
    q:             str | None = Query(None),
    variants_only: bool = Query(False),
    conn: sqlite3.Connection = Depends(get_db),
):
    data = cache.cache.get("referees")
    if data is None:
        data = queries.build_referee_identities(conn)
        cache.cache.set("referees", data)  # no TTL — static until next scrape

    if q:
        q_lower = q.lower()
        data = [r for r in data if q_lower in r["canonical"].lower()]
    if variants_only:
        data = [r for r in data if r["has_variants"]]

    return data
