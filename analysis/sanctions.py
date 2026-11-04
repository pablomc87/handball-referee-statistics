"""Impact of sanctions on the score, aggregated. Reads data/analysis/games.jsonl, writes data/analysis/by_*.csv.

For every sanction we take the sanctioned team's point of view (diff = its goals - opponent's goals) and measure
what happened afterwards. Each outcome is compared with a baseline: the same measure taken every minute of every game
for every team in the same situation (gender, 10-minute block, lead bucket). "excess" = observed - baseline, so a
sanction at 55 minutes while leading by 5 is not blamed for the lead growing like it usually does.
"""
import csv
import json
import math
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path

OUT = Path("data/analysis")
STAFF_KINDS = {"warning", "two_min", "disq", "blue"}
METRICS = ["win", "draw", "loss", "swing5", "swing10", "swing_final", "next_goal_own", "win10", "lose10"]


def lead_bucket(d):
    return 0 if d <= -4 else 1 if d < 0 else 2 if d == 0 else 3 if d < 4 else 4


def score_at(times, tl, t):
    return tl[bisect_right(times, t) - 1][1:]


def reg_final(g, clocked):
    return (score_at([x[0] for x in g["tl"]], g["tl"], 3600) if clocked else g["tl"][-1][1:])


def valid(g, clocked):
    end = reg_final(g, clocked)
    et = clocked and g["tl"][-1][0] > 3600
    return et or tuple(end) == tuple(g["final"])


def sign(x):
    return (x > 0) - (x < 0)


def measures(g, clocked, times, side, t, h0, a0, total_goals):
    """Observed outcomes for `side` from a moment with score h0-a0 (t is None when the game has no clock)."""
    own = 0 if side == "H" else 1
    f = reg_final(g, clocked)
    d0, df = (h0 - a0) * (1 if own == 0 else -1), (f[0] - f[1]) * (1 if own == 0 else -1)
    m = {"win": df > 0, "draw": df == 0, "loss": df < 0, "swing_final": df - d0}
    for X in (300, 600):
        m[f"swing{X // 60}"] = ((score_at(times, g["tl"], t + X)[0] - score_at(times, g["tl"], t + X)[1]) * (1 if own == 0 else -1) - d0
                              if clocked and t + X <= 3600 else None)
    m["win10"] = None if m["swing10"] is None else m["swing10"] > 0  # outscored the opponent over the next 10 minutes
    m["lose10"] = None if m["swing10"] is None else m["swing10"] < 0
    nxt = next(((e[1], e[2]) for e in g["tl"] if e[1] + e[2] > h0 + a0), None)
    m["next_goal_own"] = None if nxt is None else ((nxt[0] > h0) if own == 0 else (nxt[1] > a0))
    return d0, m, last_scorer(g["tl"], h0, a0, own), momentum(g, times, own, t, d0)


def last_scorer(tl, h0, a0, own):
    """Who scored the goal that made the score h0-a0: the team itself, the opponent, or nobody yet."""
    k = next((i for i, e in enumerate(tl) if e[1] + e[2] == h0 + a0), 0)
    if k == 0:
        return 0
    home_scored = tl[k][1] > tl[k - 1][1]
    return 1 if home_scored == (own == 0) else 2


def momentum(g, times, own, t, d0):
    """Net goals of the team in the 5 minutes before t, bucketed (None without a clock)."""
    if times is None:
        return None
    h, a = score_at(times, g["tl"], max(t - 300, 0))
    net = d0 - (h - a) * (1 if own == 0 else -1)
    return 0 if net <= -2 else 1 if net < 2 else 2


def key(gender, t, d0, last, mom=None):
    return gender, min(5, int(t // 600)), lead_bucket(d0), last, mom


def main():
    games = [json.loads(l) for l in open(OUT / "games.jsonl")]
    base, sanctions, dropped = defaultdict(lambda: defaultdict(list)), [], 0
    for g in games:
        clocked = all(x[0] is not None for x in g["tl"]) and all(x["t"] is not None for x in g["sanc"])
        if not valid(g, clocked):
            dropped += 1
            continue
        times = [x[0] for x in g["tl"]] if clocked else None
        total = g["tl"][-1][1] + g["tl"][-1][2]
        if clocked:  # baseline: every minute, both teams
            for k in range(1, 60):
                h0, a0 = score_at(times, g["tl"], k * 60)
                for side in "HA":
                    d0, m, last, mom = measures(g, True, times, side, k * 60, h0, a0, total)
                    for name, v in m.items():
                        if v is not None:
                            base[key(g["gender"], k * 60, d0, last, mom)][name].append(float(v))
                            base[key(g["gender"], k * 60, d0, last)][name].append(float(v))  # same, without momentum (clockless games)
        for s in g["sanc"]:
            if clocked and s["t"] > 3600:
                continue
            t = s["t"] if clocked else 3600 * (s["h"] + s["a"]) / max(total, 1)
            d0, m, last, mom = measures(g, clocked, times, s["side"], s["t"], s["h"], s["a"], total)
            sanctions.append({"g": g, "s": s, "d0": d0, "m": m, "key": key(g["gender"], t, d0, last, mom), "t": t})
    print(f"{len(games)} games, {dropped} dropped (timeline does not end on the official score), {len(sanctions)} sanctions")
    mean = lambda v: sum(v) / len(v)
    exp = {k: {n: mean(v) for n, v in d.items()} for k, d in base.items()}

    def team(r):
        g, s = r["g"], r["s"]
        return f"{g['league']} {g['home'] if s['side'] == 'H' else g['away']}"

    dims = {
        "total": lambda r: "all",
        "kind": lambda r: r["s"]["kind"],
        "league": lambda r: r["g"]["league"],
        "country": lambda r: r["g"]["country"],
        "gender": lambda r: r["g"]["gender"],
        "season": lambda r: r["g"]["season"],
        "state": lambda r: "leading" if r["d0"] > 0 else "tied" if r["d0"] == 0 else "trailing",
        "side": lambda r: "home" if r["s"]["side"] == "H" else "away",
        "team": team,
    }

    def agg(rows):
        out = {"n": len(rows), "lead%": 100 * mean([r["d0"] > 0 for r in rows]), "tied%": 100 * mean([r["d0"] == 0 for r in rows]),
               "trail%": 100 * mean([r["d0"] < 0 for r in rows]), "mean_diff_at_sanction": mean([r["d0"] for r in rows])}
        for n in METRICS:
            pairs = [(float(r["m"][n]), exp.get(r["key"], {}).get(n)) for r in rows if r["m"][n] is not None]
            pairs = [(o, e) for o, e in pairs if e is not None]
            if len(pairs) < 2:
                continue
            ex = [o - e for o, e in pairs]
            sd = math.sqrt(sum((x - mean(ex)) ** 2 for x in ex) / (len(ex) - 1))
            out[f"{n}_obs"], out[f"{n}_exp"], out[f"{n}_excess"], out[f"{n}_se"], out[f"{n}_n"] = (mean([o for o, _ in pairs]), mean([e for _, e in pairs]),
                                                                                                  mean(ex), sd / math.sqrt(len(ex)), len(pairs))
        return out

    groups = {"staff": [r for r in sanctions if r["s"]["staff"] and r["s"]["kind"] in STAFF_KINDS],
              "player_2min": [r for r in sanctions if not r["s"]["staff"] and r["s"]["kind"] == "two_min"]}
    for gname, rows in groups.items():
        for dim, fn in dims.items():
            buckets = defaultdict(list)
            for r in rows:
                buckets[fn(r)].append(r)
            res = {k: agg(v) for k, v in sorted(buckets.items(), key=lambda kv: str(kv[0])) if len(v) >= (8 if dim == "team" else 1)}
            cols = sorted({c for v in res.values() for c in v}, key=lambda c: (c != "n", c))
            with open(OUT / f"by_{dim}_{gname}.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow([dim] + cols)
                for k, v in res.items():
                    w.writerow([k] + [round(v[c], 3) if c in v else "" for c in cols])
            if gname == "staff" and dim != "state":  # who wins from the state the game was in when the sanction came
                with open(OUT / f"transitions_{dim}.csv", "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow([dim, "state", "n", "win", "draw", "loss", "win_exp", "draw_exp", "loss_exp", "final_margin_change", "final_margin_change_exp"])
                    for k, rs in sorted(buckets.items(), key=lambda kv: str(kv[0])):
                        for st, sf in (("leading", lambda r: r["d0"] > 0), ("tied", lambda r: r["d0"] == 0), ("trailing", lambda r: r["d0"] < 0)):
                            sub = [r for r in rs if sf(r)]
                            if sub:
                                e = lambda n: mean([exp[r["key"]][n] for r in sub if r["key"] in exp])
                                w.writerow([k, st, len(sub)] + [round(mean([float(r["m"][n]) for r in sub]), 3) for n in ("win", "draw", "loss")]
                                           + [round(e(n), 3) for n in ("win", "draw", "loss")]
                                           + [round(mean([r["m"]["swing_final"] for r in sub]), 3), round(e("swing_final"), 3)])
            if dim in ("total", "kind", "state", "gender", "league"):
                print(f"\n== {gname} by {dim}")
                print(f"{'':12}{'n':>6}{'lead%':>7}{'win%':>6}{'(exp)':>7}{'swing_final':>12}{'(exp)':>7}{'sw10 excess':>12}{'nextgoal':>9}{'(exp)':>7}")
                for k, v in res.items():
                    print(f"{str(k):12}{v['n']:6}{v['lead%']:7.0f}{100 * v.get('win_obs', 0):6.0f}{100 * v.get('win_exp', 0):7.0f}"
                          f"{v.get('swing_final_obs', 0):12.2f}{v.get('swing_final_exp', 0):7.2f}{v.get('swing10_excess', 0):10.2f}±{v.get('swing10_se', 0):.2f}"
                          f"{100 * v.get('next_goal_own_obs', 0):7.0f}{100 * v.get('next_goal_own_exp', 0):7.0f}")


if __name__ == "__main__":
    main()
