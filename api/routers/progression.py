import asyncio
import sqlite3
from fastapi import APIRouter, HTTPException, Query
from api import queries, cache
from api.utils import ALLOWED_GENDER
import config

router = APIRouter()


def _compute(season: str, gender: str | None) -> dict:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA query_only=ON")
    try:
        return queries.build_progression(conn, season, gender=gender)
    finally:
        conn.close()


@router.get("/progression/{season}")
async def get_progression(season: str, gender: str | None = Query(None)):
    if gender and gender not in ALLOWED_GENDER:
        raise HTTPException(400, f"gender must be M or F")
    key = f"progression:{season}:{gender or 'all'}"
    data = cache.cache.get(key)
    if data is not None:
        return data

    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _compute, season, gender)
    except Exception as e:
        raise HTTPException(500, f"Progression computation failed: {e}")

    cache.cache.set(key, data)
    return data
