import asyncio
import codecs
import re
import unicodedata

import aiohttp
from bs4 import BeautifulSoup, Tag

import config
import db


def _latin1_fallback(exc: Exception) -> tuple:
    """For invalid UTF-8 bytes, decode each byte as Latin-1 instead of replacing."""
    if isinstance(exc, UnicodeDecodeError):
        return ("".join(chr(b) for b in exc.object[exc.start : exc.end]), exc.end)
    raise exc


codecs.register_error("latin1_fallback", _latin1_fallback)


async def _fetch(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url) as resp:
        resp.raise_for_status()
        raw = await resp.read()
        return raw.decode("utf-8", errors="latin1_fallback")


def _base_params(season_id: str | None = None) -> str:
    sid = season_id or config.SEASON_ID
    return (
        f"seleccion=0"
        f"&id_superficie={config.SURFACE_ID}"
        f"&id_temp={sid}"
        f"&id_territorial={config.TERRITORIAL_ID}"
        f"&id_ambito={config.AMBITO_NATIONAL}"
    )


def _comp_url(
    cat_id: str | int = "",
    comp_id: str | int = "",
    torneo_id: str | int = "",
    jornada: int | None = None,
    season_id: str | None = None,
) -> str:
    url = f"{config.BASE_URL}/competicion.php?{_base_params(season_id)}"
    if cat_id:
        url += f"&id_categoria={cat_id}"
    if comp_id:
        url += f"&id_competicion={comp_id}"
    if torneo_id:
        url += f"&id={torneo_id}"
    if jornada is not None:
        url += f"&jornada={jornada}"
    return url


def _parse_select_options(soup: BeautifulSoup, select_id: str) -> list[tuple[str, str]]:
    sel = soup.find("select", id=select_id)
    if not sel:
        return []
    return [
        (opt.get("value", "").strip(), opt.get_text(strip=True))
        for opt in sel.find_all("option")
        if opt.get("value", "").strip()
    ]


def _parse_jornada_nums(soup: BeautifulSoup) -> list[int]:
    nums = set()
    for a in soup.find_all("a", href=True):
        m = re.search(r"jornada=(\d+)", a["href"])
        if m:
            nums.add(int(m.group(1)))
    return sorted(nums)


def _parse_match_rows(soup: BeautifulSoup, torneo_id: int) -> list[dict]:
    matches = []
    for tr in soup.find_all("tr", class_="partido"):
        match_id_str = tr.get("data-id", "").strip()
        status = tr.get("data-estado", "").strip()
        if not match_id_str:
            continue
        try:
            match_id = int(match_id_str)
        except ValueError:
            continue

        # Teams
        equipo_td = tr.find("td")
        home, away = "", ""
        if equipo_td:
            nombres = equipo_td.find("div", class_="nombres-equipos")
            if nombres:
                links = nombres.find_all("a")
                home = links[0].get_text(strip=True) if len(links) > 0 else ""
                away = links[1].get_text(strip=True) if len(links) > 1 else ""

        # Date + time (find a cell with DD/MM/YYYY pattern)
        match_date, match_time = "", ""
        for td in tr.find_all("td"):
            divs = td.find_all("div", recursive=False)
            if len(divs) >= 2:
                date_text = divs[0].get_text(strip=True)
                if re.match(r"\d{2}/\d{2}/\d{4}", date_text):
                    d, mon, y = date_text.split("/")
                    match_date = f"{y}-{mon}-{d}"
                    match_time = divs[1].get_text(strip=True)
                    break

        # Venue
        venue = ""
        for td in tr.find_all("td"):
            if "mostrarLugar" in td.decode_contents():
                span = td.find("span")
                if span:
                    venue = span.get_text(strip=True)
                    break

        # Score (only present for Finalizado matches)
        score_home, score_away = None, None
        marcador = tr.find("td", class_="col-marcador")
        if marcador:
            local_span = marcador.find("span", class_="local")
            visit_span = marcador.find("span", class_=re.compile(r"visitante"))
            if local_span and visit_span:
                try:
                    score_home = int(local_span.get_text(strip=True))
                    score_away = int(visit_span.get_text(strip=True))
                except ValueError:
                    pass

        matches.append({
            "match_id": match_id,
            "torneo_id": torneo_id,
            "home_team": home,
            "away_team": away,
            "date": match_date,
            "time": match_time,
            "venue": venue,
            "status": status,
            "score_home": score_home,
            "score_away": score_away,
        })
    return matches


# ── Discovery ───────────────────────────────────────────────────────────────

async def _fetch_comp_torneos(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    cat_id: str,
    cat_name: str,
    comp_id: str,
    comp_name: str,
    season_id: str,
) -> None:
    """Fetch torneos for one (categoria, competition) pair and store them."""
    url = _comp_url(cat_id=cat_id, comp_id=comp_id, season_id=season_id)
    async with semaphore:
        try:
            html = await _fetch(session, url)
        except Exception as e:
            print(f"  [warn] cat={cat_id} comp={comp_id} fetch failed: {e}")
            return

    soup = BeautifulSoup(html, "lxml")
    torneo_opts = _parse_select_options(soup, "torneos")

    for torneo_id_str, torneo_name in torneo_opts:
        try:
            torneo_id = int(torneo_id_str)
        except ValueError:
            continue

        await asyncio.to_thread(
            db.upsert_torneo,
            {
                "torneo_id": torneo_id,
                "cat_id": int(cat_id),
                "comp_id": int(comp_id),
                "categoria_name": cat_name,
                "competicion_name": comp_name,
                "torneo_name": torneo_name,
                "season_id": season_id,
            },
        )

    print(f"  [{cat_name[:35]}] {comp_name[:40]} → {len(torneo_opts)} torneos")


async def _fetch_cat_comps(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    cat_id: str,
    cat_name: str,
    season_id: str,
) -> None:
    """Fetch all competitions for a category, then fetch their torneos in parallel."""
    url = _comp_url(cat_id=cat_id, season_id=season_id)
    async with semaphore:
        try:
            html = await _fetch(session, url)
        except Exception as e:
            print(f"  [warn] cat={cat_id} fetch failed: {e}")
            return

    soup = BeautifulSoup(html, "lxml")
    comp_opts = _parse_select_options(soup, "competiciones")

    await asyncio.gather(*[
        _fetch_comp_torneos(session, semaphore, cat_id, cat_name, comp_id, comp_name, season_id)
        for comp_id, comp_name in comp_opts
    ])


async def discover_competitions(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    season_id: str = config.SEASON_ID,
) -> None:
    print(f"Phase 1 [{season_id}]: Discovering competitions...")

    url = _comp_url(season_id=season_id)
    async with semaphore:
        html = await _fetch(session, url)
    soup = BeautifulSoup(html, "lxml")
    all_cats = _parse_select_options(soup, "categorias")

    def _norm(s: str) -> str:
        return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().upper()

    target_norm = {_norm(n) for n in config.TARGET_CATEGORIES}
    target_cats = [
        (cat_id, cat_name)
        for cat_id, cat_name in all_cats
        if _norm(cat_name) in target_norm
    ]
    print(f"  Found {len(target_cats)}/{len(config.TARGET_CATEGORIES)} target categories")

    await asyncio.gather(*[
        _fetch_cat_comps(session, semaphore, cat_id, cat_name, season_id)
        for cat_id, cat_name in target_cats
    ])

    await asyncio.to_thread(db.mark_discovery_done, season_id)


# ── Jornada discovery ────────────────────────────────────────────────────────

async def discover_jornadas(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
) -> None:
    """For each torneo, find available jornada numbers and store them."""
    torneos = await asyncio.to_thread(db.get_torneos_needing_jornada_discovery)
    if not torneos:
        return

    print(f"Phase 2a: Discovering jornadas for {len(torneos)} torneos...")

    async def _one(torneo: dict) -> None:
        url = _comp_url(
            cat_id=torneo["cat_id"],
            comp_id=torneo["comp_id"],
            torneo_id=torneo["torneo_id"],
        )
        async with semaphore:
            try:
                html = await _fetch(session, url)
            except Exception as e:
                print(f"  [warn] torneo={torneo['torneo_id']} jornada discovery failed: {e}")
                return

        soup = BeautifulSoup(html, "lxml")
        jornada_nums = _parse_jornada_nums(soup)

        if jornada_nums:
            await asyncio.to_thread(db.upsert_jornadas_batch, torneo["torneo_id"], jornada_nums)
        else:
            # No jornada navigation → single implicit page (jornada=0)
            await asyncio.to_thread(db.upsert_jornadas_batch, torneo["torneo_id"], [0])

        await asyncio.to_thread(db.mark_torneo_jornadas_discovered, torneo["torneo_id"])

    await asyncio.gather(*[_one(t) for t in torneos])


# ── Match collection ─────────────────────────────────────────────────────────

async def collect_matches(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
) -> None:
    jornadas = await asyncio.to_thread(db.get_jornadas_needing_scrape)
    if not jornadas:
        return

    print(f"Phase 2b: Collecting matches for {len(jornadas)} jornadas...")

    async def _one(jornada: dict) -> None:
        jornada_param = jornada["jornada_num"] if jornada["jornada_num"] != 0 else None
        url = _comp_url(
            cat_id=jornada["cat_id"],
            comp_id=jornada["comp_id"],
            torneo_id=jornada["torneo_id"],
            jornada=jornada_param,
        )
        async with semaphore:
            try:
                html = await _fetch(session, url)
            except Exception as e:
                print(
                    f"  [warn] torneo={jornada['torneo_id']} "
                    f"jornada={jornada['jornada_num']} fetch failed: {e}"
                )
                return

        soup = BeautifulSoup(html, "lxml")
        matches = _parse_match_rows(soup, jornada["torneo_id"])

        await asyncio.to_thread(db.upsert_matches_batch, matches)
        await asyncio.to_thread(
            db.mark_jornada_scraped, jornada["torneo_id"], jornada["jornada_num"]
        )

    await asyncio.gather(*[_one(j) for j in jornadas])


# ── Referee fetch ─────────────────────────────────────────────────────────────

_ROLE_MAP = {
    "ARBITRO": ("referee_1", "referee_2"),
    "ANOTADOR/CRONOMETRADOR": ("scorekeeper_1", "scorekeeper_2"),
    "ANOTADOR": ("scorekeeper_1", "scorekeeper_2"),
    "CRONOMETRADOR": ("scorekeeper_1", "scorekeeper_2"),
    "DELEGADOS DE MESA": ("table_delegate",),
    "DELEGADO DE MESA": ("table_delegate",),
    "TV": ("tv",),
}


def _parse_referee_divs(soup: BeautifulSoup) -> dict:
    extra = soup.find("div", class_="extra-data")
    if not extra:
        return {}

    result: dict[str, str] = {}
    role_counters: dict[str, int] = {}

    for div in extra.find_all("div", class_=re.compile(r"^div\d+$")):
        # Use only Tag children (skip NavigableString whitespace nodes)
        children = [c for c in div.children if isinstance(c, Tag)]
        if len(children) < 2:
            continue
        role_label = children[0].get_text(strip=True).upper()
        name = children[1].get_text(strip=True)

        matched_key = None
        for key in _ROLE_MAP:
            if key in role_label:
                matched_key = key
                break
        if matched_key is None:
            continue

        slots = _ROLE_MAP[matched_key]
        idx = role_counters.get(matched_key, 0)
        if idx < len(slots):
            result[slots[idx]] = name
        role_counters[matched_key] = idx + 1

    return result


async def fetch_referees(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
) -> None:
    matches = await asyncio.to_thread(db.get_matches_needing_referee_scrape)
    if not matches:
        return

    print(f"Phase 3: Fetching referees for {len(matches)} matches...")

    async def _one(match: dict) -> None:
        url = f"{config.BASE_URL}/previo.php?id_partido={match['match_id']}"
        async with semaphore:
            try:
                html = await _fetch(session, url)
            except Exception as e:
                print(f"  [warn] match={match['match_id']} previo fetch failed: {e}")
                return

        soup = BeautifulSoup(html, "lxml")
        referee_data = _parse_referee_divs(soup)

        # Determine current status from the preview page
        current_status = match["status"]
        status_span = soup.find("span", class_="custom-col")
        if status_span:
            text = status_span.get_text(strip=True)
            if "Finalizado" in text:
                current_status = "Finalizado"
            elif "Pendiente" in text:
                current_status = "Pendiente"

        await asyncio.to_thread(db.upsert_referees, match["match_id"], referee_data)
        await asyncio.to_thread(
            db.mark_referee_scraped, match["match_id"], current_status
        )

    await asyncio.gather(*[_one(m) for m in matches])
