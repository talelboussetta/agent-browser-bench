"""Deterministic local test site for the benchmark.

Every page carries a unique token (TOKEN-<kind>-<i>). A tool "got the page" only if
that token is in the text it returns, so a blank SPA shell or a half-loaded page counts
as a failure, not a success.

Page kinds:
  static  ~40 KB server-rendered article
  spa     empty shell; the content (and token) is inserted by JS 300 ms after load
  heavy   ~6,000 DOM nodes and 30 small images
  slow    the server waits 1.5 s before answering
  state   writes ~512 KB to localStorage and sets cookies on every visit, so browser
          state grows with use (the kind of accumulation that slowed pooled browsers
          in crawl4ai#2231)

Run: python site/server.py [port] [host]   (default 127.0.0.1)
"""

import http.server
import random
import socketserver
import sys
import time
from functools import lru_cache

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
HOST = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"

WORDS = (
    "browser agent page network render script layout memory latency token crawl "
    "extract model context cache cookie storage request response header socket"
).split()


@lru_cache(maxsize=4096)
def prose(seed: int, n_words: int) -> str:
    rnd = random.Random(seed)
    return " ".join(rnd.choice(WORDS) for _ in range(n_words))


def page(title: str, body: str, head: str = "") -> bytes:
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>{head}"
        f"</head><body>{body}</body></html>"
    ).encode()


PIXEL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def render(kind: str, i: int) -> bytes:
    token = f"TOKEN-{kind}-{i}"
    if kind == "static":
        paras = "".join(f"<p>{prose(i * 100 + k, 120)}</p>" for k in range(40))
        return page(token, f"<h1>Article {i}</h1><p id='t'>{token}</p>{paras}")
    if kind == "spa":
        js = (
            "<script>setTimeout(function(){var d=document.getElementById('app');"
            f"d.innerHTML='<h1>App {i}</h1><p id=\"t\">{token}</p><p>{prose(i, 200)}</p>';"
            "},300);</script>"
        )
        return page(f"app {i}", "<div id='app'>Loading...</div>" + js)
    if kind == "heavy":
        rows = "".join(
            f"<tr><td>{r}</td><td>{prose(i * 1000 + r, 6)}</td><td><span>{r * 7}</span></td></tr>"
            for r in range(1200)
        )
        imgs = "".join(f"<img src='/img/{i}-{k}.png' width=8 height=8>" for k in range(30))
        return page(token, f"<h1>Table {i}</h1><p id='t'>{token}</p>{imgs}<table>{rows}</table>")
    if kind == "slow":
        time.sleep(1.5)
        return page(token, f"<h1>Slow {i}</h1><p id='t'>{token}</p><p>{prose(i, 300)}</p>")
    if kind == "state":
        js = (
            "<script>try{var s='x'.repeat(65536);"
            f"for(var k=0;k<8;k++){{localStorage.setItem('k{i}_'+k,s);}}"
            f"document.cookie='visit{i % 50}={i}; path=/';}}catch(e){{}}</script>"
        )
        return page(token, f"<h1>State {i}</h1><p id='t'>{token}</p><p>{prose(i, 150)}</p>" + js)
    return b""


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        parts = self.path.strip("/").split("/")
        if parts[0] == "img":
            self._send(200, PIXEL_PNG, "image/png")
            return
        if len(parts) == 2 and parts[1].isdigit():
            body = render(parts[0], int(parts[1]))
            if body:
                self._send(200, body, "text/html; charset=utf-8")
                return
        if parts == [""]:
            self._send(200, page("index", "ok"), "text/html")
            return
        self._send(404, b"not found", "text/plain")

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    with Server((HOST, PORT), Handler) as httpd:
        print(f"serving on :{PORT}", flush=True)
        httpd.serve_forever()
