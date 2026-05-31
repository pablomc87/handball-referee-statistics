"""FastAPI dependencies."""
import sqlite3
from typing import Generator
import config


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA query_only=ON")
    try:
        yield conn
    finally:
        conn.close()
