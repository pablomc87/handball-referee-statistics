"""Download StarLigue / ProLigue games from ffhandball.fr: calendar per matchday, then each FFHB match-sheet PDF.

Competition pages come from the site's poule sitemaps; each matchday page embeds the rencontre rows (with fdmCode),
and the sheet lives at fdm.fdme.ffhandball.fr/<c0>/<c1>/<c2>/<c3>/<fdmCode>.pdf.
"""
import asyncio
import html
import json
import re
from pathlib import Path

import aiohttp

SITE = "https://www.ffhandball.fr"
FDM = "https://fdm.fdme.ffhandball.fr/{}/{}/{}/{}/{}.pdf"
OUT = Path("data/ffhb")
UA = {"User-Agent": "handball-referee-statistics (research; contact pablomc87@gmail.com)"}
MEN_PRO = re.compile(r"/(saison-\d{4}-\d{4}-\d+)/national/((?:lnh-|[a-z-]*starligue|[a-z-]*proligue)[a-z0-9-]*)/poule-(\d+)/")
DECODER = json.JSONDecoder()


async def get(session, sem, url, binary=False):
    async with sem:
        status = None
        for attempt in range(6):
            try:
                async with session.get(url) as r:
                    status = r.status
                    if r.status == 404:
                        return None
                    if r.ok:
                        await asyncio.sleep(1.5)
                        return await (r.read() if binary else r.text())
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                status = type(e).__name__
            await asyncio.sleep(3 * 2**attempt)
    print("gave up:", status, url)  # ponytail: rerun fills the gaps
    return None


async def poules(session, sem):
    f = OUT / "poules.txt"
    if not f.exists():
        index = await get(session, sem, f"{SITE}/sitemap.xml")
        urls = []
        for name in re.findall(r"competitions_poules-sitemap\d*\.xml", index):
            urls += re.findall(r"<loc>([^<]+)", await get(session, sem, f"{SITE}/{name}"))
        f.write_text("\n".join(u for u in urls if MEN_PRO.search(u)))
    return [MEN_PRO.search(u).groups() for u in f.read_text().split()]


def rencontres(page):
    text = html.unescape(page)
    out = {}
    for m in re.finditer(r'\{"id":"\d+","ext_rencontreId"', text):
        try:
            o, _ = DECODER.raw_decode(text[m.start():])
            out[o["ext_rencontreId"]] = o
        except ValueError:
            pass
    return out


async def poule_games(session, sem, season, comp, poule):
    base = f"{SITE}/competitions/{season}/national/{comp}/poule-{poule}/"
    first = await get(session, sem, base)
    if first is None:
        return []
    days = sorted(set(map(int, re.findall(r'journee_numero\\*"?:(\d+)', html.unescape(first))))) or [1]
    games = {}
    for d in days:
        page = await get(session, sem, f"{base}journee-{d}/")
        games.update(rencontres(page or ""))
    return [{"season": season, "competition": comp, "poule": poule, **g} for g in games.values()]


async def sheet(session, sem, g, log):
    code = g.get("fdmCode")
    f = OUT / "pdf" / f"{code}.pdf"
    if not code or f.exists():
        return
    body = await get(session, sem, FDM.format(*code[:4], code), binary=True)
    if body and body[:4] == b"%PDF":
        f.write_bytes(body)
    else:
        log.write(f"{code}\t{g['season']}\tnot a pdf\n")


async def main():
    (OUT / "pdf").mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(1)
    async with aiohttp.ClientSession(headers=UA, timeout=aiohttp.ClientTimeout(total=60)) as s:
        lists = await asyncio.gather(*(poule_games(s, sem, *p) for p in await poules(s, sem)))
        games = [g for l in lists for g in l]
        (OUT / "games.jsonl").write_text("\n".join(json.dumps(g, ensure_ascii=False) for g in games))
        print(len(games), "games listed,", sum(bool(g.get("fdmCode")) for g in games), "with a sheet code")
        with open(OUT / "_log.tsv", "a", buffering=1) as log:
            await asyncio.gather(*(sheet(s, sem, g, log) for g in games))


if __name__ == "__main__":
    asyncio.run(main())
