from fastapi import APIRouter, Depends, Query
import sqlite3
from api.deps import get_db
from api import queries, cache

router = APIRouter()


@router.get("/movements")
def get_movements(
    transition: str | None = Query(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    data = cache.cache.get("movements")
    if data is None:
        identities = cache.cache.get("referees") or queries.build_referee_identities(conn)
        data = queries.build_referee_movements(conn, identities=identities)
        cache.cache.set("movements", data)

    if transition:
        return {transition: data.get(transition, [])}
    return data


@router.get("/movements/transitions")
def list_transitions(conn: sqlite3.Connection = Depends(get_db)) -> list[str]:
    data = cache.cache.get("movements")
    if data is None:
        identities = cache.cache.get("referees") or queries.build_referee_identities(conn)
        data = queries.build_referee_movements(conn, identities=identities)
        cache.cache.set("movements", data)
    return list(data.keys())
