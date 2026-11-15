"""Crawl4AI endurance with a per-process memory breakdown.

Same page mix as the endurance suite. Every 100 navigations prints the median time, the number
of browser processes, and RSS per process type, plus the private (unshared) memory total, which
does not double-count pages shared between processes.

  python -m bench.probe_crawl4ai --n 1000
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time
from collections import defaultdict

import psutil

KINDS = ["static", "spa", "heavy", "state"]


def snapshot():
    me = psutil.Process(os.getpid())
    rss, n, private = defaultdict(int), 0, 0
    for p in [me, *me.children(recursive=True)]:
        try:
            cmd = " ".join(p.cmdline())
            mi = p.memory_full_info()
        except psutil.Error:
            continue
        n += 1
        private += getattr(mi, "uss", 0) or getattr(mi, "private", 0)
        t = ("python" if p.pid == me.pid else "node" if "node" in p.name().lower()
             else "renderer" if "--type=renderer" in cmd else "gpu" if "--type=gpu" in cmd
             else "utility" if "--type=" in cmd else "browser")
        rss[t] += mi.rss
    return n, round(private / 2**20), {k: round(v / 2**20) for k, v in sorted(rss.items())}


async def main(n, port):
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

    cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, verbose=False)
    times = []
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False)) as c:
        for j in range(n):
            url = f"http://127.0.0.1:{port}/{KINDS[j % 4]}/{j + 1}"
            t0 = time.perf_counter()
            await c.arun(url, config=cfg)
            times.append((time.perf_counter() - t0) * 1000)
            if (j + 1) % 100 == 0:
                procs, uss, rss = snapshot()
                print(f"{j + 1:5d} median {statistics.median(times[-100:]):5.0f} ms  procs {procs:3d}  "
                      f"private {uss:5d} MB  rss {rss}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    asyncio.run(main(a.n, a.port))
