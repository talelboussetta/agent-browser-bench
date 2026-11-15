"""Isolate the slowdown seen for playwright-load in the endurance run.

One Chromium, one context, one tab, N navigations of a single page kind, wait_until=load.
Prints, every 100 navigations: median ms, and RSS per process type (python, node driver,
browser, renderer, gpu, utility), so the growing process is visible.

  python -m bench.probe_growth --kind static --n 1000 [--wait load|networkidle] [--new-page]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time
from collections import defaultdict

import psutil


def by_type():
    me = psutil.Process(os.getpid())
    out = defaultdict(int)
    out["python"] = me.memory_info().rss
    for p in me.children(recursive=True):
        try:
            cmd = " ".join(p.cmdline())
            rss = p.memory_info().rss
        except psutil.Error:
            continue
        if "node" in p.name().lower():
            t = "node-driver"
        elif "--type=renderer" in cmd:
            t = "renderer"
        elif "--type=gpu" in cmd:
            t = "gpu"
        elif "--type=" in cmd:
            t = "utility"
        else:
            t = "browser"
        out[t] += rss
    return {k: round(v / 1024**2) for k, v in sorted(out.items())}


async def main(kind, n, wait, new_page, port, sleep_ms=0, args=None, force_gc=False):
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True, args=args or [])
    ctx = await b.new_context()
    page = await ctx.new_page()
    times = []
    for i in range(1, n + 1):
        if new_page:
            await page.close()
            page = await ctx.new_page()
        t0 = time.perf_counter()
        await page.goto(f"http://127.0.0.1:{port}/{kind}/{i}", wait_until=wait)
        await page.inner_text("body")
        times.append((time.perf_counter() - t0) * 1000)
        if force_gc:
            await page.evaluate("gc()")
        if sleep_ms:
            await asyncio.sleep(sleep_ms / 1000)
        if i % 100 == 0:
            print(f"{i:5d}  median {statistics.median(times[-100:]):6.0f} ms  {by_type()}", flush=True)
    await b.close()
    await pw.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="static")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--wait", default="load")
    ap.add_argument("--new-page", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--sleep-ms", type=int, default=0)
    ap.add_argument("--gc", action="store_true", help="needs --arg=--js-flags=--expose-gc")
    ap.add_argument("--arg", action="append", default=[])
    a = ap.parse_args()
    asyncio.run(main(a.kind, a.n, a.wait, a.new_page, a.port, a.sleep_ms, a.arg, a.gc))
