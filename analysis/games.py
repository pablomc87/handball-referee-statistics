"""Flatten the downloaded LNH / LFH / RFEBM files into data/games.csv (one row per game)."""
import csv
import glob
import json
import re
from datetime import datetime
from multiprocessing import Pool

import pdfplumber


def lnh(path):
    t = pdfplumber.open(path).pages[0].extract_text()
    comp = re.search(r"Compétition (.+?) Saison (\d{4}) / \d{4}", t)
    final = re.search(r"^(\d+) Score final (\d+)$", t, re.M)
    ht = re.search(r"^(\d+) Mi-temps (\d+)$", t, re.M)
    date = re.search(r"Date (\d\d)/(\d\d)/(\d{4})", t)
    if not (comp and final and date) or not comp[1].endswith(("StarLigue", "ProLigue")):
        return None
    d = f"{date[3]}-{date[2]}-{date[1]}"
    return ["LNH", path.split("/")[-1][:-4], comp[1].split()[-1], int(comp[2]), d, *final.groups(), *(ht.groups() if ht else ("", ""))]


def lfh(path):
    d = json.load(open(path))
    r = d["rencontre"]
    season = int(re.search(r"(\d{4})(?:-\d{2,4})?$", d["competition"])[1])
    return ["LFH", r["ext_rencontreId"], "D1F", season, r["date"][:10], r["equipe1Score"], r["equipe2Score"], r["equipe1ScoreMT"], r["equipe2ScoreMT"]]


def isq(path):
    d = json.load(open(path))
    p = (d["acta"].get("data") or {}).get("partido")
    if not p:
        return None
    day, month, year = p["fecha"].split("-")
    league = "ASOBAL" if "MASCULIN" in d["category"] else "GUERRERAS"
    return ["RFEBM", d["match_id"], league, 2000 + int(d["season"][:2]), f"{year}-{month}-{day}", p["local"]["resultado"], p["visitante"]["resultado"], "", ""]


def parse(job):
    fn, path = job
    try:
        return fn(path)
    except Exception:  # ponytail: skip unparseable files, counted in the printout below
        return None


if __name__ == "__main__":
    jobs = [(lnh, p) for p in glob.glob("data/lnh/*.pdf")] + [(lfh, p) for p in glob.glob("data/lfh/*.json")] + [(isq, p) for p in glob.glob("data/isquad/*.json")]
    with Pool() as pool:
        rows = [r for r in pool.map(parse, jobs, chunksize=50) if r]
    print(len(jobs), "files ->", len(rows), "games")
    with open("data/games.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "game_id", "league", "season", "date", "home", "away", "ht_home", "ht_away"])
        w.writerows(sorted(rows, key=lambda r: (r[2], r[3], r[4])))
