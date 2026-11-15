"""One adapter per tool. Each exposes the same three calls:

    await a.start()
    text = await a.fetch(url)   # what an agent would read from the page
    await a.stop()
    a.pids() -> list[int]       # root processes whose tree is the tool's memory footprint
    a.mem_bytes() -> int | None # override when memory is not a local process tree

Every adapter uses the tool's own default "open the page and give me its text" path.
The harness adds no waits of its own, so a page whose content arrives late shows up as
a miss for tools that return before it renders. That is a property of the default, not a
bug in the harness, and the README reports it that way.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]


def tree_rss(pids: list[int]) -> int:
    seen, total = set(), 0
    for pid in pids:
        try:
            p = psutil.Process(pid)
        except psutil.Error:
            continue
        for q in [p, *p.children(recursive=True)]:
            if q.pid in seen:
                continue
            seen.add(q.pid)
            try:
                total += q.memory_info().rss
            except psutil.Error:
                pass
    return total


class Adapter:
    name = "base"
    host = "127.0.0.1"  # host the test site is reached at, from the browser's point of view

    async def start(self): ...
    async def fetch(self, url: str) -> str: ...
    async def stop(self): ...

    def pids(self) -> list[int]:
        return []

    def mem_bytes(self) -> int | None:
        return tree_rss(self.pids())


# --- Playwright (baseline) -------------------------------------------------------------


class PlaywrightAdapter(Adapter):
    """One headless Chromium, one context, one tab reused for every page, like an agent."""

    def __init__(self, wait_until: str = "load"):
        self.wait_until = wait_until
        self.name = f"playwright-{wait_until}"

    async def start(self):
        from playwright.async_api import async_playwright

        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(headless=True)
        self.ctx = await self.browser.new_context()
        self.page = await self.ctx.new_page()

    async def fetch(self, url):
        await self.page.goto(url, wait_until=self.wait_until, timeout=30_000)
        return await self.page.inner_text("body")

    async def stop(self):
        await self.browser.close()
        await self.pw.stop()

    def pids(self):
        # the Playwright driver (node) is a child of this Python process; the browser is its child
        return [os.getpid()]


# --- Crawl4AI ---------------------------------------------------------------------------


class Crawl4AIAdapter(Adapter):
    """AsyncWebCrawler with its defaults, cache bypassed, markdown as the text."""

    name = "crawl4ai"

    async def start(self):
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

        self.crawler = AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False))
        await self.crawler.start()
        self.run_cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, verbose=False)

    async def fetch(self, url):
        r = await self.crawler.arun(url, config=self.run_cfg)
        if not r.success:
            raise RuntimeError(r.error_message or "crawl failed")
        md = r.markdown
        return str(getattr(md, "raw_markdown", md) or "")

    async def stop(self):
        await self.crawler.close()

    def pids(self):
        return [os.getpid()]


# --- Lightpanda (Docker, driven over CDP by Playwright) ---------------------------------


class LightpandaAdapter(Adapter):
    name = "lightpanda"
    host = "host.docker.internal"
    image = "lightpanda/browser:1.0.4"
    container = "abb-lightpanda"

    async def start(self):
        from playwright.async_api import async_playwright

        subprocess.run(["docker", "rm", "-f", self.container], capture_output=True)
        subprocess.run(
            ["docker", "run", "-d", "--name", self.container, "-p", "9222:9222", self.image],
            check=True,
            capture_output=True,
        )
        self.pw = await async_playwright().start()
        for _ in range(50):
            try:
                self.browser = await self.pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
                break
            except Exception:
                await asyncio.sleep(0.2)
        else:
            raise RuntimeError("lightpanda did not accept a CDP connection")
        self.ctx = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
        self.page = await self.ctx.new_page()

    async def fetch(self, url):
        await self.page.goto(url, wait_until="load", timeout=30_000)
        return await self.page.inner_text("body")

    async def stop(self):
        try:
            await self.browser.close()
        finally:
            await self.pw.stop()
            subprocess.run(["docker", "rm", "-f", self.container], capture_output=True)

    def mem_bytes(self):
        out = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}", self.container],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not out:
            return None
        usage = json.loads(out)["MemUsage"].split("/")[0].strip()
        units = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
        for u in ("GiB", "MiB", "KiB", "B"):
            if usage.endswith(u):
                return int(float(usage[: -len(u)]) * units[u])
        return None


# --- agent-browser (Vercel Labs CLI) ------------------------------------------------------


class AgentBrowserAdapter(Adapter):
    """`agent-browser open <url>` then `agent-browser get text body`, as an agent would call it.

    Each call is a CLI process talking to the tool's background daemon, so per-call process
    start-up is part of the measured time: that is the cost an agent using the CLI pays.
    """

    name = "agent-browser"
    session = "abb"

    def __init__(self):
        exe = ROOT / "tools" / "node_modules" / ".bin" / ("agent-browser.cmd" if sys.platform == "win32" else "agent-browser")
        self.exe = str(exe)
        self._daemon_pids: list[int] = []

    async def _run(self, *args, timeout=60):
        proc = await asyncio.create_subprocess_exec(
            self.exe, "--session", self.session, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
        if proc.returncode != 0:
            raise RuntimeError((err or out).decode(errors="replace").strip()[:300])
        return out.decode(errors="replace")

    async def start(self):
        before = {p.pid for p in psutil.process_iter()}
        await self._run("open", "about:blank")
        # the daemon and its browser outlive the CLI call: find the new root processes
        new = [p for p in psutil.process_iter(["pid", "name", "ppid"]) if p.pid not in before]
        new_pids = {p.pid for p in new}
        self._daemon_pids = [p.pid for p in new if p.info["ppid"] not in new_pids]

    async def fetch(self, url):
        await self._run("open", url)
        return await self._run("get", "text", "body")

    async def stop(self):
        try:
            await self._run("close", timeout=30)
        except Exception:
            pass

    def pids(self):
        return [p for p in self._daemon_pids if psutil.pid_exists(p)]


def make(name: str) -> Adapter:
    return {
        "playwright-load": lambda: PlaywrightAdapter("load"),
        "playwright-networkidle": lambda: PlaywrightAdapter("networkidle"),
        "crawl4ai": Crawl4AIAdapter,
        "lightpanda": LightpandaAdapter,
        "agent-browser": AgentBrowserAdapter,
    }[name]()


ALL = ["playwright-load", "playwright-networkidle", "crawl4ai", "lightpanda", "agent-browser"]
