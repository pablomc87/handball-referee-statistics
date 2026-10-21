"""Does knowing who has the ball explain why staff-sanctioned teams score the next goal less often? (LFH API games only)"""
import glob
import json
import math
from collections import defaultdict

LOSS = {"BUT", "BUT SUR PENALTY", "TIR ARRETE", "TIR A COTE", "TIR RATE", "TIR SUR POTEAU", "MAUVAISE PASSE", "PERTE DE BALLE", "PASSAGE EN FORCE", "MARCHER", "ZONE"}
# the actor's team ends its possession -> the other team has the ball; for these the actor's team gets it
GAIN = {"GARDIEN ARRETE LE TIR", "PENALTY OBTENU", "PROVOQUE UNE SANCTION"}
SANCTION = {"AVERTISSEMENT": "warning", "DEUX MINUTES": "two_min", "CARTON ROUGE": "disq"}
GOALS = {"BUT", "BUT SUR PENALTY"}


def holder(acts, i, teams):
    """Team with the ball just before acts[i], from the last event that settles possession."""
    for j in range(i - 1, -1, -1):
        a = acts[j]
        if a["type"] in LOSS:
            return next(t for t in teams if t != a["hv_team_id"])
        if a["type"] in GAIN:
            return a["hv_team_id"]
        if a["type"] == "DEUX MINUTES":
            return next(t for t in teams if t != a["hv_team_id"])
    return None


def next_goal_team(acts, i):
    return next((a["hv_team_id"] for a in acts[i + 1:] if a["type"] in GOALS), None)


obs, base = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
for f in glob.glob("data/lfh/*.json"):
    acts = json.load(open(f))["actions"]
    if not acts:
        continue
    acts = sorted(acts, key=lambda a: ((int(a["mi_temps"]) - 1) * 1800 + int(a["chrono_seconds"]), int(a["id"])))
    teams = sorted({a["hv_team_id"] for a in acts})
    if len(teams) != 2:
        continue
    for i, a in enumerate(acts):
        if a["type"] in SANCTION and not a["player_number"]:
            h, nxt = holder(acts, i, teams), next_goal_team(acts, i)
            if h and nxt:
                o = obs["own has ball" if h == a["hv_team_id"] else "opponent has ball"]
                o[0] += nxt == a["hv_team_id"]; o[1] += 1
    t_last = -1
    for i, a in enumerate(acts):  # baseline: first event of every minute, both teams
        t = (int(a["mi_temps"]) - 1) * 1800 + int(a["chrono_seconds"])
        if t // 60 == t_last:
            continue
        t_last = t // 60
        h, nxt = holder(acts, i, teams), next_goal_team(acts, i - 1)
        if h and nxt:
            for team in teams:
                b = base["own has ball" if h == team else "opponent has ball"]
                b[0] += nxt == team; b[1] += 1

print("next goal scored by the sanctioned team (LFH games with an event log; staff sanctions of every kind)")
tot = [0, 0]
for k in ("own has ball", "opponent has ball"):
    o, b = obs[k], base[k]
    p = o[0] / o[1]
    print(f"  {k:18} n={o[1]:3}  after sanction {100 * p:3.0f}% (±{100 * 1.96 * math.sqrt(p * (1 - p) / o[1]):.0f})   baseline {100 * b[0] / b[1]:3.0f}% (n={b[1]})")
    tot[0] += o[0]; tot[1] += o[1]
print(f"  all: {100 * tot[0] / tot[1]:.0f}% of {tot[1]}")
