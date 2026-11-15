# Results: run3

Platform: Windows-11-10.0.26300-SP0, Python 3.13.1.

## Pages: did the tool return the page's content, and how fast

Success = the page's unique token was in the text the tool returned. Times are median / p95 in ms, successful and failed navigations together.

| tool | startup ms | static | spa | heavy | slow | state |
|---|---|---|---|---|---|---|
| playwright-load | 1105 | 30/30 · 49 / 63 | 0/30 · 47 / 60 | 30/30 · 130 / 173 | 30/30 · 1586 / 1624 | 30/30 · 46 / 57 |
| playwright-networkidle | 709 | 30/30 · 550 / 561 | 30/30 · 551 / 562 | 30/30 · 628 / 671 | 30/30 · 2090 / 2114 | 30/30 · 549 / 558 |
| crawl4ai | 3226 | 30/30 · 322 / 373 | 0/30 · 284 / 323 | 30/30 · 641 / 756 | 30/30 · 1791 / 1824 | 30/30 · 334 / 361 |
| lightpanda | 1804 | 30/30 · 56 / 73 | 0/30 · 49 / 64 | 30/30 · 98 / 122 | 30/30 · 1552 / 1563 | 30/30 · 52 / 65 |
| agent-browser | 9423 | 30/30 · 516 / 621 | 5/30 · 523 / 599 | 30/30 · 618 / 865 | 30/30 · 2025 / 2162 | 30/30 · 522 / 637 |

### Failure reasons

- **playwright-load**: spa: `token missing` ×30
- **crawl4ai**: spa: `RuntimeError: Blocked by anti-bot protection: Structural: minimal_text on small page` ×30
- **lightpanda**: spa: `token missing` ×30
- **agent-browser**: spa: `token missing` ×25
