"""Turn results/<dir>/*.jsonl into results/<dir>/REPORT.md and two charts.

  python -m bench.report results/run1
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from bench.adapters import ALL


def load(path: Path):
    meta, rows, final = {}, [], {}
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("meta"):
            meta = r
        elif "final_mem" in r:
            final = r
        else:
            rows.append(r)
    return meta, rows, final


def pct(xs, q):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def mb(b):
    return "n/a" if b is None else f"{b / 1024**2:.0f}"


def main(d: Path):
    out = []
    tools = [t for t in ALL if (d / f"pages-{t}.jsonl").exists() or (d / f"endurance-{t}.jsonl").exists()]

    # ---------------- pages
    kinds = ["static", "spa", "heavy", "slow", "state"]
    out.append("## Pages: did the tool return the page's content, and how fast\n")
    out.append("Success = the page's unique token was in the text the tool returned. "
               "Times are median / p95 in ms, successful and failed navigations together.\n")
    hdr = "| tool | startup ms | " + " | ".join(kinds) + " |"
    out += [hdr, "|" + "---|" * (len(kinds) + 2)]
    errors = {}
    for t in tools:
        p = d / f"pages-{t}.jsonl"
        if not p.exists():
            continue
        meta, rows, _ = load(p)
        cells = []
        for k in kinds:
            rs = [r for r in rows if r["kind"] == k]
            ok = sum(r["ok"] for r in rs)
            ms = [r["ms"] for r in rs]
            cells.append(f"{ok}/{len(rs)} · {pct(ms, .5):.0f} / {pct(ms, .95):.0f}")
        out.append(f"| {t} | {meta.get('startup_ms', 0):.0f} | " + " | ".join(cells) + " |")
        errs = defaultdict(int)
        for r in rows:
            if r["err"]:
                errs[(r["kind"], r["err"].split(" (")[0][:110])] += 1
        errors[t] = errs
    out.append("\n### Failure reasons\n")
    for t, errs in errors.items():
        if errs:
            out.append(f"- **{t}**: " + "; ".join(f"{k}: `{e}` ×{n}" for (k, e), n in sorted(errs.items())))
    out.append("")

    # ---------------- endurance
    end_tools = [t for t in tools if (d / f"endurance-{t}.jsonl").exists()]
    if end_tools:
        out.append("## Endurance: one browser, many navigations in a row\n")
        out.append("Median ms per window of 100 navigations (static/spa/heavy/state, cycling). "
                   "Memory is the tool's process tree (or container) RSS.\n")
        series = {}
        win_hdr = None
        rows_out = []
        for t in end_tools:
            meta, rows, final = load(d / f"endurance-{t}.jsonl")
            n = len(rows)
            wins = [rows[i:i + 100] for i in range(0, n, 100)]
            meds = [statistics.median(r["ms"] for r in w) for w in wins]
            succ = sum(r["ok"] for r in rows)
            mems = [r["mem"] for r in rows if r.get("mem")]
            first_mem = mems[0] if mems else None
            last_mem = final.get("final_mem") or (mems[-1] if mems else None)
            # static pages only, first vs last window: removes the spa/heavy mix from the comparison
            st = [r for r in rows if r["kind"] == "static"]
            st_first = statistics.median(r["ms"] for r in st[:25]) if st else float("nan")
            st_last = statistics.median(r["ms"] for r in st[-25:]) if st else float("nan")
            series[t] = (meds, [(r["idx"], r["mem"]) for r in rows if r.get("mem")])
            win_hdr = win_hdr or len(meds)
            rows_out.append(
                f"| {t} | {succ}/{n} | {meds[0]:.0f} | {meds[-1]:.0f} | {st_first:.0f} → {st_last:.0f} "
                f"| {mb(first_mem)} → {mb(last_mem)} |"
            )
        out += ["| tool | success | first 100 median ms | last 100 median ms | static pages, first 25 → last 25 median ms | memory MB, start → end |",
                "|---|---|---|---|---|---|", *rows_out, ""]
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(1, 2, figsize=(11, 4))
            for t, (meds, mem) in series.items():
                ax[0].plot([(i + 1) * 100 for i in range(len(meds))], meds, marker="o", label=t)
                if mem:
                    ax[1].plot([i for i, _ in mem], [m / 1024**2 for _, m in mem], label=t)
            ax[0].set(title="Median ms per 100 navigations", xlabel="navigations", ylabel="ms")
            ax[1].set(title="Memory (MB)", xlabel="navigations", ylabel="MB")
            for a in ax:
                a.grid(alpha=.3)
            ax[0].legend(fontsize=8)
            fig.tight_layout()
            fig.savefig(d / "endurance.png", dpi=130)
            out.append("![endurance](endurance.png)\n")
        except ImportError:
            pass

    meta_any = next((load(p)[0] for p in sorted(d.glob("*.jsonl"))), {})
    head = [f"# Results: {d.name}\n", f"Platform: {meta_any.get('platform', '?')}, Python {meta_any.get('python', '?')}.\n"]
    (d / "REPORT.md").write_text("\n".join(head + out), encoding="utf-8")
    print((d / "REPORT.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
