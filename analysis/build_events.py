"""Turn every source with an event log (RFEBM, LFH API, FFHB match-sheet PDFs) into one record per game.

Writes data/analysis/games.jsonl. Per game: league, country, gender, season, teams, the score timeline
[[seconds, home, away], ...] and every sanction [{t, side, kind, staff, h, a}] (h/a = score when it happened).
Sides are "H" (home) and "A" (away). Time is seconds from kickoff, 3600 = end of regulation.
"""
import glob
import json
import re
import unicodedata
from multiprocessing import Pool
from pathlib import Path

import pdfplumber

OUT = Path("data/analysis")
LEAGUE = {  # league -> (country, gender)
    "StarLigue": ("FR", "M"), "ProLigue": ("FR", "M"), "D1F": ("FR", "F"), "ASOBAL": ("ES", "M"), "GUERRERAS": ("ES", "F"),
}


def norm(name):
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()


def game(src, gid, league, season, date, home, away, final, tl, sanc):
    country, gender = LEAGUE[league]
    return {"src": src, "id": gid, "league": league, "country": country, "gender": gender, "season": season, "date": date,
            "home": norm(home), "away": norm(away), "final": final, "tl": tl, "sanc": sanc}


# ── RFEBM ────────────────────────────────────────────────────────────────────
RF_KIND = {"Amonestación": "warning", "Exclusión": "two_min", "Descalificación": "disq", "Tarjeta azul": "blue"}


def rf_offset(block):
    b = block.lower()
    if b.startswith("segunda"):
        return 1800
    if "rroga" in b:
        return 3600 if "primera" in b else 3900
    return 0 if b.startswith("prim") else None


def rfebm(path):
    d = json.load(open(path))
    a = d["acta"]["data"]
    p, h_id, a_id = a["partido"], a["partido"]["local"]["id_equipo"], a["partido"]["visitante"]["id_equipo"]
    staff = {t["id_jugador"] for e in a["equipos"].values() for t in e["tecnicos"]}
    h = aw = 0
    tl, sanc = [[0, 0, 0]], []
    for e in a["eventos"]:
        off = rf_offset(e["bloque"])
        if e["id_equipo"] not in (h_id, a_id):
            continue
        if ":" in e["minuto"] and off is not None:
            m, s = e["minuto"].split(":")
            t = off + int(m) * 60 + int(s)
        else:  # some reports have no clock at all: keep the order, drop the time
            t = None
        side = "H" if e["id_equipo"] == h_id else "A"
        if e["tipo_evento"] == "Gol":
            h, aw = (h + 1, aw) if side == "H" else (h, aw + 1)
            tl.append([t, h, aw])
        elif e["tipo_evento"] in RF_KIND:
            sanc.append({"t": t, "side": side, "kind": RF_KIND[e["tipo_evento"]], "staff": e["id_jugador"] in staff, "h": h, "a": aw})
    day, month, year = p["fecha"].split("-")
    league = "ASOBAL" if "MASCULIN" in d["category"] else "GUERRERAS"
    return game("RFEBM", d["match_id"], league, 2000 + int(d["season"][:2]), f"{year}-{month}-{day}", p["local"]["nombre"], p["visitante"]["nombre"],
                [p["local"]["resultado"], p["visitante"]["resultado"]], tl, sanc)


# ── LFH API ──────────────────────────────────────────────────────────────────
LFH_KIND = {"AVERTISSEMENT": "warning", "DEUX MINUTES": "two_min", "CARTON ROUGE": "disq", "CARTON BLEU": "blue"}


def lfh(path):
    d = json.load(open(path))
    if not d["actions"]:
        return None
    r = d["rencontre"]
    season = int(re.search(r"(\d{4})(?:-\d{2,4})?$", d["competition"])[1])
    acts = sorted(d["actions"], key=lambda x: ((int(x["mi_temps"]) - 1) * 1800 + int(x["chrono_seconds"]), int(x["score_home"]) + int(x["score_away"])))
    side_of, tl, sanc = {}, [[0, 0, 0]], []
    ph = pa = 0
    for x in acts:
        h, a = int(x["score_home"]), int(x["score_away"])
        if (h, a) != (ph, pa):
            side_of[x["hv_team_id"]] = "H" if h > ph else "A"
            tl.append([(int(x["mi_temps"]) - 1) * 1800 + int(x["chrono_seconds"]), h, a])
            ph, pa = h, a
    for x in acts:
        if x["type"] in LFH_KIND and x["hv_team_id"] in side_of:
            sanc.append({"t": (int(x["mi_temps"]) - 1) * 1800 + int(x["chrono_seconds"]), "side": side_of[x["hv_team_id"]], "kind": LFH_KIND[x["type"]],
                         "staff": not x["player_number"], "h": int(x["score_home"]), "a": int(x["score_away"])})
    return game("LFH", r["ext_rencontreId"], "D1F", season, r["date"][:10], r["equipe1"]["libelle"], r["equipe2"]["libelle"],
                [int(r["equipe1Score"]), int(r["equipe2Score"])], tl, sanc)


# ── FFHB match-sheet PDF ─────────────────────────────────────────────────────
ROW = re.compile(r"(\d\d):(\d\d) (\d\d)-(\d\d) (\S.*?)(?= \d\d:\d\d \d\d-\d\d |$)")
FF_KIND = (("Avertissement", "warning"), ("2MN", "two_min"), ("Disqualification", "disq"), ("Bleu", "blue"), ("Rouge", "disq"))


def ffhb(job):
    pdf_path, meta = job
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages[1:])
    tl, sanc, seen = [[0, 0, 0]], [], set()
    for line in text.split("\n"):
        for m in ROW.finditer(line):
            t, h, a, act = int(m[1]) * 60 + int(m[2]), int(m[3]), int(m[4]), m[5]
            if (t, h, a, act) in seen:
                continue
            seen.add((t, h, a, act))
            who = re.search(r"^(\w+?)([JO])([VR])(?:N°|[A-Z])", act)
            if not who:
                continue
            if (h, a) != tuple(tl[-1][1:]):
                tl.append([t, h, a])
            for word, kind in FF_KIND:
                if who[1].startswith(word):
                    sanc.append({"t": t, "side": "H" if who[3] == "R" else "A", "kind": kind, "staff": who[2] == "O", "h": h, "a": a})
    tl.sort(key=lambda x: (x[0], x[1] + x[2]))
    return game("FFHB", meta["id"], meta["league"], meta["season"], meta["date"], meta["home"], meta["away"], meta["final"], tl, sanc)


def ffhb_jobs():
    jobs = []
    for f in glob.glob("data/lfh/*.json"):  # D1F seasons the API has no events for, but S3 has the FFHB sheet
        d = json.load(open(f))
        pdf = Path("data/lfh/fdm") / f"{d['rencontre'].get('fdmCode')}.pdf"
        if not d["actions"] and pdf.exists():
            r = d["rencontre"]
            season = int(re.search(r"(\d{4})(?:-\d{2,4})?$", d["competition"])[1])
            jobs.append((str(pdf), {"id": r["ext_rencontreId"], "league": "D1F", "season": season, "date": r["date"][:10],
                                    "home": r["equipe1"]["libelle"], "away": r["equipe2"]["libelle"], "final": [int(r["equipe1Score"]), int(r["equipe2Score"])]}))
    games = Path("data/ffhb/games.jsonl")
    if games.exists():  # men's StarLigue / ProLigue, from fetch_ffhb.py
        for line in games.read_text().splitlines():
            g = json.loads(line)
            pdf = Path("data/ffhb/pdf") / f"{g.get('fdmCode')}.pdf"
            if pdf.exists() and str(g.get("equipe1Score")).isdigit() and str(g.get("equipe2Score")).isdigit():  # skips forfeits ("PE" etc.)
                league = "StarLigue" if "starligue" in g["competition"] else "ProLigue"
                jobs.append((str(pdf), {"id": g["ext_rencontreId"], "league": league, "season": int(g["season"].split("-")[1]), "date": g["date"][:10],
                                        "home": g["equipe1Libelle"], "away": g["equipe2Libelle"], "final": [int(g["equipe1Score"]), int(g["equipe2Score"])]}))
    return jobs


def safe(fn, arg):
    try:
        return fn(arg)
    except Exception:  # ponytail: unparseable files are skipped and counted below
        return None


def run(job):
    kind, arg = job
    return safe({"rfebm": rfebm, "lfh": lfh, "ffhb": ffhb}[kind], arg)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [("rfebm", p) for p in glob.glob("data/isquad/*.json")] + [("lfh", p) for p in glob.glob("data/lfh/*.json")] + [("ffhb", j) for j in ffhb_jobs()]
    with Pool() as pool:
        games = [g for g in pool.map(run, jobs, chunksize=20) if g]
    print(len(jobs), "inputs ->", len(games), "games with events;", sum(len(g["sanc"]) for g in games), "sanctions")
    with open(OUT / "games.jsonl", "w") as f:
        f.write("\n".join(json.dumps(g, ensure_ascii=False) for g in games))
