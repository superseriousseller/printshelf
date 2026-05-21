"""Spike: validate OG meta extraction for v1 import platforms.

Per-platform UA strategy because Cloudflare-protected sites behave differently:
  * Printables: blocks browser UAs on model pages; allowlists `facebookexternalhit`
  * Makerworld: model pages return 200 with browser UA — but OG meta is JS-rendered
  * Thingiverse: browser UA, og:property tags work
  * Cults3D: browser UA, og:property tags work

Printables uses non-standard `<meta name="og:..."` (instead of property=),
so the extractor checks both attributes.

Usage:
    python scraper_spike.py <url>
"""
import json
import re
import sys
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
UNFURL_UA = "facebookexternalhit/1.1"


def platform_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "makerworld" in host:
        return "makerworld"
    if "printables" in host:
        return "printables"
    if "cults3d" in host or "cults" in host:
        return "cults3d"
    if "thingiverse" in host:
        return "thingiverse"
    return "manual"


def headers_for(platform: str) -> dict:
    if platform == "printables":
        return {"User-Agent": UNFURL_UA, "Accept": "text/html"}
    return {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }


def _og(soup: BeautifulSoup, key: str) -> str | None:
    """Look up `og:<key>` via either `property=` (standard) or `name=` (Printables)."""
    for attr in ("property", "name"):
        el = soup.find("meta", attrs={attr: f"og:{key}"})
        if el and el.get("content"):
            return el["content"].strip()
    return None


def extract(url: str) -> dict:
    platform = platform_from_url(url)
    with httpx.Client(timeout=20.0, follow_redirects=True, headers=headers_for(platform)) as c:
        r = c.get(url)
    soup = BeautifulSoup(r.text, "html.parser")

    title = _og(soup, "title")
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
    description = _og(soup, "description")
    thumbnail = _og(soup, "image")

    # Designer / author via JSON-LD if available
    designer = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            author = node.get("author") or node.get("creator")
            if isinstance(author, dict):
                designer = author.get("name") or designer
            elif isinstance(author, str):
                designer = author or designer
            if designer:
                break
        if designer:
            break

    # Fallback: parse "by <name>" out of og:title (Printables format)
    if not designer and title:
        m = re.search(r"\bby\s+([^|]+?)(?:\s*\||\s+\|)", title)
        if m:
            designer = m.group(1).strip()

    # Heuristic: did we actually get a model-specific result, or a generic site page?
    generic_signals = [
        thumbnail and "og-icon" in thumbnail,
        title and platform == "makerworld" and "MakerWorld" in title and len(title) < 60,
        description and platform == "makerworld" and "leading 3D printing model community" in description,
    ]
    is_generic = any(generic_signals)

    return {
        "platform": platform,
        "status_code": r.status_code,
        "final_url": str(r.url),
        "title": title,
        "designer": designer,
        "thumbnail_url": thumbnail,
        "description": (description[:140] + "...") if description and len(description) > 140 else description,
        "looks_generic": is_generic,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: scraper_spike.py <url>", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(extract(sys.argv[1]), indent=2))
