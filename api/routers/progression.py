import asyncio
import sqlite3
from fastapi import APIRouter, HTTPException
from api import queries, cache
import config

router = APIRouter()


def _compute(season: str) -> dict:
    # Open a fresh connection in this thread — SQLite connections are not thread-safe
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA query_only=ON")
    try:
        return queries.build_progression(conn, season)
    finally:
        conn.close()


@router.get("/progression/{season}")
async def get_progression(season: str):
    key = f"progression:{season}"
    data = cache.cache.get(key)
    if data is not None:
        return data

    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _compute, season)
    except Exception as e:
        raise HTTPException(500, f"Progression computation failed: {e}")

    cache.cache.set(key, data)
    return data
