import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import db as scraper_db
from api import cache, queries
from api.deps import get_db
from api.routers import seasons, stats, couples, games, referees, movements, progression


def _warm_caches() -> None:
    """Pre-compute expensive caches at startup (runs in thread pool)."""
    conn_gen = get_db()
    conn = next(conn_gen)
    try:
        print("  Warming referee identities cache…")
        identities = queries.build_referee_identities(conn)
        cache.cache.set("referees", identities)

        print("  Warming movements cache…")
        mvs = queries.build_referee_movements(conn, identities=identities)
        cache.cache.set("movements", mvs)

        # Warm only the two most recent seasons for progression
        all_seasons = queries.get_seasons(conn)
        for sid in all_seasons[:2]:
            print(f"  Warming progression cache for {sid}…")
            data = queries.build_progression(conn, sid)
            cache.cache.set(f"progression:{sid}", data)
    finally:
        try:
            conn_gen.send(None)
        except StopIteration:
            pass
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scraper_db.init_db()
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _warm_caches)
    yield


app = FastAPI(title="Handball Referees API", lifespan=lifespan)

_static = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")

for _router in [seasons, stats, couples, games, referees, movements, progression]:
    app.include_router(_router.router, prefix="/api")


@app.get("/")
def index():
    return FileResponse(str(_static / "index.html"))
