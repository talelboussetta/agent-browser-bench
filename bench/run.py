"""Run the benchmark.

  python -m bench.run pages      --tools all --n 30
  python -m bench.run endurance  --tools all --n 1000

pages:     N pages of each kind per tool: did the tool return the page's token, and how long it took.
endurance: N navigations in a row on one browser (static/spa/heavy/state, cycling), to see whether
           a long-lived browser slows down or grows in memory.

Raw rows go to results/<suite>-<tool>.jsonl, one per navigation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import time
from pathlib import Path

from bench.adapters import ALL, make

PORT = int(os.environ.get("ABB_PORT", "8765"))
OUT = Path(os.environ.get("ABB_OUT", "results"))
PAGE_KINDS = ["static", "spa", "heavy", "slow", "state"]
ENDURANCE_KINDS = ["static", "spa", "heavy", "state"]


async def one(adapter, url: str, token: str, timeout: float = 45.0) -> dict:
    t0 = time.perf_counter()
    err, ok = None, False
    try:
        text = await asyncio.wait_for(adapter.fetch(url), timeout)
        ok = token in text
        if not ok:
            err = "token missing"
    except Exception as e:  # a failure is data, not a crash
        err = f"{type(e).__name__}: {str(e)[:200]}"
    return {"ms": round((time.perf_counter() - t0) * 1000, 1), "ok": ok, "err": err}


async def suite(name: str, tool: str, n: int, seed_offset: int) -> None:
    adapter = make(tool)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}-{tool}.jsonl"
    base = f"http://{adapter.host}:{PORT}"
    t_start = time.perf_counter()
    await adapter.start()
    startup_ms = round((time.perf_counter() - t_start) * 1000, 1)
    # one throwaway navigation so the first measured page is not paying for cold caches
    await one(adapter, f"{base}/static/0", "TOKEN-static-0")

    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"meta": True, "tool": tool, "suite": name, "n": n,
                            "startup_ms": startup_ms, "platform": platform.platform(),
                            "python": platform.python_version()}) + "\n")
        try:
            if name == "pages":
                seq = [(k, i) for i in range(1, n + 1) for k in PAGE_KINDS]
            else:
                seq = [(ENDURANCE_KINDS[j % len(ENDURANCE_KINDS)], j + 1) for j in range(n)]
            for idx, (kind, i) in enumerate(seq):
                i += seed_offset
                row = await one(adapter, f"{base}/{kind}/{i}", f"TOKEN-{kind}-{i}")
                row.update({"idx": idx, "kind": kind})
                if name == "endurance" and idx % 50 == 0:
                    row["mem"] = adapter.mem_bytes()
                f.write(json.dumps(row) + "\n")
                if idx % 100 == 0:
                    print(f"  {tool} {name} {idx}/{len(seq)} {row['ms']}ms ok={row['ok']}", flush=True)
            if name == "endurance":
                f.write(json.dumps({"final_mem": adapter.mem_bytes()}) + "\n")
        finally:
            await adapter.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("suite", choices=["pages", "endurance"])
    ap.add_argument("--tools", default="all")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed-offset", type=int, default=0)
    a = ap.parse_args()
    tools = ALL if a.tools == "all" else a.tools.split(",")
    for t in tools:
        print(f"== {t}", flush=True)
        asyncio.run(suite(a.suite, t, a.n, a.seed_offset))


if __name__ == "__main__":
    main()
