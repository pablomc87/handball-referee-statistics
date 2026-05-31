from fastapi import APIRouter, Depends
import sqlite3
from api.deps import get_db
from api import queries

router = APIRouter()


@router.get("/seasons")
def list_seasons(conn: sqlite3.Connection = Depends(get_db)) -> list[str]:
    return queries.get_seasons(conn)
