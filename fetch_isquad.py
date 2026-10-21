"""Download the top-tier Spanish match reports (Liga ASOBAL, Liga Guerreras Iberdrola) known to handball.db.

Per match: acta JSON (events + line-ups) and the previo.php page (referees, delegates).
"""
import asyncio
import json
import re
import sqlite3
from pathlib import Path

import aiohttp

import config

API = "https://balonmano.isquad.es/json/api/call.php/resultados/actaLive"
OUT = Path("data/isquad")
UA = {"User-Agent": "handball-referee-statistics (research; contact pablomc87@gmail.com)"}
TOP_TIER = """
    SELECT m.match_id, t.season_id, t.categoria_name FROM matches m JOIN torneos t USING (torneo_id)
    WHERE lower(m.status) = 'finalizado'
      AND (t.categoria_name LIKE '%HONOR ELITE FEMENINA' OR t.categoria_name LIKE '%DIVISION DE HONOR FEMENINA'
           OR t.categoria_name LIKE '%DIVISION HONOR FEMENINA'
           OR (t.categoria_name LIKE '%HONOR MASCULIN%' AND t.categoria_name NOT LIKE '%PLATA%'))
"""


async def get(session, sem, url):
    async with sem:
        for attempt in range(4):
            try:
                async with session.get(url) as r:
                    if r.ok:
                        await asyncio.sleep(0.2)
                        return await r.text()
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(2**attempt)
    raise RuntimeError(url)


async def match(session, sem, mid, season, cat, log):
    f = OUT / f"{mid}.json"
    if f.exists():
        return
    try:
        page = await get(session, sem, f"{config.BASE_URL}/acta.php?id_partido={mid}")
        token = re.search(r'data-token="(\w+)"', page).group(1)
        acta = json.loads(await get(session, sem, f"{API}?id_partido={mid}&token={token}"))
        previo = await get(session, sem, f"{config.BASE_URL}/previo.php?id_partido={mid}")
    except Exception as e:  # ponytail: log and move on, rerun retries only the missing files
        log.write(f"{mid}\t{type(e).__name__}: {str(e)[:80]}\n")
        return
    f.write_text(json.dumps({"match_id": mid, "season": season, "category": cat, "acta": acta, "previo_html": previo}, ensure_ascii=False))


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True).execute(TOP_TIER).fetchall()
    print(len(rows), "matches")
    sem = asyncio.Semaphore(4)
    with open(OUT / "_log.tsv", "a", buffering=1) as log:
        async with aiohttp.ClientSession(headers=UA, timeout=aiohttp.ClientTimeout(total=60)) as s:
            await asyncio.gather(*(match(s, sem, *r, log) for r in rows))


if __name__ == "__main__":
    asyncio.run(main())
