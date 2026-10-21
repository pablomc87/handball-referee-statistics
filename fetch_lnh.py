"""Download LNH (StarLigue/ProLigue) match stat sheets: lnh.fr serves one PDF per global match id (cid)."""
import asyncio
import sys
from pathlib import Path

import aiohttp

URL = "https://www.lnh.fr/daikin-starligue/calendriers/20262027/dsl/j07/caen/paris?cid={}&task=pdf"
OUT = Path("data/lnh")
UA = {"User-Agent": "handball-referee-statistics (research; contact pablomc87@gmail.com)"}


async def fetch(session, sem, cid, log):
    f = OUT / f"{cid}.pdf"
    if f.exists():
        return
    async with sem:
        for attempt in range(4):
            try:
                async with session.get(URL.format(cid)) as r:
                    body = await r.read()
                    if r.ok:
                        break
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(2**attempt)
        else:
            log.write(f"{cid}\terror\n")
            return
        await asyncio.sleep(0.2)
    if body[:4] != b"%PDF":  # ponytail: LNH answers 200 with a short text such as "Erreur match - ..."
        log.write(f"{cid}\t{body[:60].decode(errors='replace').strip()}\n")
        return
    f.write_bytes(body)


async def main(lo, hi):
    OUT.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(4)
    timeout = aiohttp.ClientTimeout(total=60)
    with open(OUT / "_log.tsv", "a", buffering=1) as log:
        async with aiohttp.ClientSession(headers=UA, timeout=timeout) as s:
            await asyncio.gather(*(fetch(s, sem, c, log) for c in range(lo, hi + 1)))


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]), int(sys.argv[2])))
