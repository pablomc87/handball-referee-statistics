"""Download Ligue Butagaz Énergie (D1F) games from the LFH JSON API: details + every action per game.

Also copies the FFHB match-sheet PDF from the S3 archive when its fdmCode (= object key) is there.
"""
import asyncio
import json
import os
from pathlib import Path

import aiohttp
import boto3
from botocore.exceptions import ClientError

API = "https://ligue-feminine-handball.fr/wp-json/lfh/v1"
OUT = Path("data/lfh")
UA = {"User-Agent": "handball-referee-statistics (research; contact pablomc87@gmail.com)"}


async def get(session, sem, path):
    async with sem:
        for attempt in range(4):
            try:
                async with session.get(f"{API}/{path}") as r:
                    if r.ok:
                        await asyncio.sleep(0.2)
                        return await r.json()
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(2**attempt)
    raise RuntimeError(f"failed: {path}")


def copy_fdm(code):
    s3, bucket = boto3.client("s3"), os.environ["S3_BUCKET"]
    for key in (f"{code}.pdf", f"downloads/{code}.pdf"):
        try:
            s3.download_file(bucket, key, str(OUT / "fdm" / f"{code}.pdf"))
            return key
        except ClientError:
            pass


async def game(session, sem, g, comp):
    f = OUT / f"{g['ext_rencontreId']}.json"
    if f.exists():
        return
    rid = g["ext_rencontreId"]
    details = await get(session, sem, f"rencontres/{rid}/details?actions_limit=1")
    actions, offset = [], 0
    while True:
        page = await get(session, sem, f"rencontres/{rid}/actions?offset={offset}&limit=50")
        actions += page["items"]
        offset += 50
        if offset >= page["total"]:
            break
    fdm = await asyncio.to_thread(copy_fdm, g["fdmCode"]) if g.get("fdmCode") else None
    f.write_text(json.dumps({"competition": comp, "rencontre": g, "details": details, "actions": actions, "s3_key": fdm}, ensure_ascii=False))


async def main():
    (OUT / "fdm").mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(4)
    async with aiohttp.ClientSession(headers=UA, timeout=aiohttp.ClientTimeout(total=60)) as s:
        comps = (await get(s, sem, "competitions"))["data"]
        poule_comp = {
            p["id"]: c["libelle"] for c in comps if c["logo"] == "D1F" for ph in c["phases"] for p in ph["poules"]
        }
        games, page = [], 1
        while True:
            r = await get(s, sem, f"rencontres?per_page=200&page={page}")
            games += [g for g in r["data"] if g["pouleId"] in poule_comp and g["equipe1Score"] is not None]
            if page >= r["meta"]["pages"]:
                break
            page += 1
        print(len(games), "finished D1F games")
        await asyncio.gather(*(game(s, sem, g, poule_comp[g["pouleId"]]) for g in games))


if __name__ == "__main__":
    asyncio.run(main())
