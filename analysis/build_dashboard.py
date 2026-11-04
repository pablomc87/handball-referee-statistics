"""Build dashboard/sanctions.html: one self-contained page (data inlined) from the analysis CSVs. Open it in a browser."""
import csv
import glob
import io
import os
from pathlib import Path

SHIM = """
const RAW = %(raw)s;
const TABLES = {};
for (const k in RAW) TABLES[k] = d3.csvParse(RAW[k]);
window.dash = {
  colors: ['#2f6fd0', '#d9822b', '#2f9e6f', '#a24fbf', '#c8473d', '#7c8794', '#b79a1f', '#1f9aa8'],
  data: (id) => ({status: TABLES[id] ? 'ok' : 'missing', data: TABLES[id] || []}),
  onData: (fn) => { fn(); let t; addEventListener('resize', () => { clearTimeout(t); t = setTimeout(fn, 120); }); },
};
"""

CSS = """
:root { --color-fg: #1c2330; --color-fg-muted: #5d6877; --color-bg: #f4f6f9; --color-panel: #ffffff; --color-border-line: #dde2ea; --color-bad: #c8473d;
  --cds-font-size-title: 1.9rem; --cds-font-size-heading: 1.05rem; --cds-font-size-caption: .8rem; --cds-font-weight-medium: 600;
  --cds-radius: 10px; --cds-pad-xs: .3rem; --cds-pad-sm: .6rem; --cds-pad-lg: 1.1rem; --cds-gap-sm: .5rem; --cds-gap-md: .9rem; --cds-gap-lg: 1.4rem;
  --cds-chart-grid: #e6eaf0; --cds-chart-axis: #aab3c0; --cds-chart-reference: #7b8696; --cds-chart-muted: #9aa5b4;
  --cds-surface-popover: #ffffff; --cds-border: #cfd6e0; --cds-shadow-popover: 0 4px 14px rgba(20,30,50,.15); --cds-text-secondary: #5d6877; --cds-dur-slow: .3s;
  --font-anthropic-sans: system-ui, -apple-system, 'Segoe UI', sans-serif; --font-anthropic-serif: Georgia, 'Times New Roman', serif; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root { --color-fg: #e6eaf1; --color-fg-muted: #97a3b4; --color-bg: #11161d; --color-panel: #1a212b; --color-border-line: #2b3441; --color-bad: #e5675d;
  --cds-chart-grid: #263040; --cds-chart-axis: #55627a; --cds-chart-reference: #7f8da3; --cds-chart-muted: #6c7a90; --cds-surface-popover: #222b37; --cds-border: #364154;
  --cds-shadow-popover: 0 4px 14px rgba(0,0,0,.5); --cds-text-secondary: #97a3b4; color-scheme: dark; } }
body { margin: 0; background: var(--color-bg); color: var(--color-fg); font-family: var(--font-anthropic-sans); font-size: 14px; }
#dash-root { padding: 0 clamp(16px, 4vw, 40px); }
"""


def main():
    raw = {}
    rows, cols = [], set()
    for f in sorted(glob.glob("data/analysis/by_*_*.csv")):
        dim, pop = os.path.basename(f)[3:-4].split("_", 1)
        for r in csv.DictReader(open(f)):
            g = r.pop(dim)
            rows.append({"population": pop, "dimension": dim, "group": g, **r})
            cols |= set(rows[-1])
    order = ["population", "dimension", "group", "n", "lead%", "tied%", "trail%", "mean_diff_at_sanction"]
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=order + sorted(cols - set(order)))
    w.writeheader(); w.writerows(rows)
    raw["summary"] = out.getvalue()
    tr = []
    for f in sorted(glob.glob("data/analysis/transitions_*.csv")):
        dim = os.path.basename(f)[12:-4]
        for r in csv.DictReader(open(f)):
            g = r.pop(dim)
            tr.append({"dimension": dim, "group": g, **r})
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(tr[0]))
    w.writeheader(); w.writerows(tr)
    raw["transitions"] = out.getvalue()
    import json
    page = Path("dashboard/page.html").read_text()
    html = ("<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width, initial-scale=1'>"
            "<title>Sanctions on team officials</title><style>" + CSS + "</style>"
            "<script src='https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js'></script></head><body><div id=dash-root>" + page.replace("<script>", "<script>" + SHIM % {"raw": json.dumps(raw).replace("</", "<\\/")}, 1) + "</div></body></html>")
    Path("dashboard/sanctions.html").write_text(html)
    print("wrote dashboard/sanctions.html", len(html) // 1024, "KB")


if __name__ == "__main__":
    main()
