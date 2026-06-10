"""Model URL → metadata extractor.

Promoted from the validated spike in backend/scripts/scraper_spike.py.

Per-platform behavior (decided in the spike):

  printables   ✓  Uses non-standard `<meta name="og:..."`. Needs the
                  `facebookexternalhit/1.1` UA — browser UAs get 403.
  thingiverse  ✓  Standard og:property tags with a normal browser UA.
  cults3d      ✓  Standard og:property tags with a normal browser UA.
  makerworld   ✗  Server returns shell HTML; real metadata is hydrated
                  client-side. Returns 200 with `manual=true` so the
                  client knows to ask the user to paste fields manually.
                  (The Chrome extension reads the rendered DOM directly
                  for Makerworld — server-side scraping isn't the path.)
"""
import json
import logging
import os
import re
from typing import Optional
from urllib.parse import urlparse, urlencode

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
UNFURL_UA = "facebookexternalhit/1.1"

BROWSER_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}
UNFURL_HEADERS = {"User-Agent": UNFURL_UA, "Accept": "text/html"}

REQUEST_TIMEOUT = 15.0

# Optional Cloudflare Worker proxy for sites that block Railway IPs (e.g. Makerworld).
# Set CF_FETCH_PROXY_URL and CF_FETCH_PROXY_SECRET in env to enable.
_CF_PROXY_URL = os.environ.get("CF_FETCH_PROXY_URL", "").rstrip("/")
_CF_PROXY_SECRET = os.environ.get("CF_FETCH_PROXY_SECRET", "")


class ImportError_(Exception):
    """Raised when import can't proceed — message is safe to return to the client."""


def detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "makerworld" in host:
        return "makerworld"
    if "printables" in host:
        return "printables"
    if "cults3d" in host or "cults." in host:
        return "cults3d"
    if "thingiverse" in host:
        return "thingiverse"
    return "manual"


def _headers_for(platform: str) -> dict:
    return UNFURL_HEADERS if platform == "printables" else BROWSER_HEADERS


def _og(soup: BeautifulSoup, key: str) -> Optional[str]:
    """Read `og:<key>` from either `property=` (standard) or `name=` (Printables)."""
    for attr in ("property", "name"):
        el = soup.find("meta", attrs={attr: f"og:{key}"})
        if el and el.get("content"):
            return el["content"].strip()
    return None


def _title_from_url_slug(url: str) -> Optional[str]:
    """Extract a human-readable title from a URL slug.

    Most model platforms put the title in the URL as kebab-case after a
    numeric ID (Makerworld, Printables) or after a category (Cults3D).
    This is the last-resort signal when the page itself blocks scraping
    or hydrates metadata client-side (Makerworld).

    Examples:
      /en/models/2815747-fruit-trinket-trays-cherry  → "Fruit Trinket Trays Cherry"
      /model/3-josef-prusa-figure-zombie              → "Josef Prusa Figure Zombie"
      /en/3d-model/game/cosplay-g1-megatron           → "Cosplay G1 Megatron"

    Returns None when the slug yields nothing useful.
    """
    path = urlparse(url).path.rstrip("/")
    if not path:
        return None
    last = path.split("/")[-1]
    # Strip a leading numeric ID + dash ("2815747-fruit..." → "fruit...")
    m = re.match(r"^\d+-(.+)$", last)
    if m:
        last = m.group(1)
    # Drop pure-numeric segments (e.g. "/models/2" → "2")
    if last.isdigit():
        return None
    words = [w for w in last.split("-") if w]
    if not words:
        return None
    # Capitalize but preserve all-caps tokens that look intentional (G1, X1C)
    out = []
    for w in words:
        if w.isupper() and len(w) <= 4:
            out.append(w)
        elif re.match(r"^[a-z]\d+[a-z]?$", w, re.I):  # G1, X1C, v2
            out.append(w.upper())
        else:
            out.append(w.capitalize())
    return " ".join(out)


def _clean_title(title: str) -> str:
    """Strip platform site-name suffixes and trailing author attributions.

    Printables og:title is "Model Name by Author | Download free STL | Printables.com".
    We want just "Model Name".
    """
    had_pipe = " | " in title
    pipe = title.find(" | ")
    if pipe != -1:
        title = title[:pipe].strip()
    # Strip " by Author" only when the title had a "|" separator (platform-attribution pattern)
    if had_pipe:
        m = re.match(r"^(.*?)\s+by\s+\S.*$", title, re.IGNORECASE)
        if m and m.group(1).strip():
            title = m.group(1).strip()
    return title


def _extract_designer(soup: BeautifulSoup, title: Optional[str]) -> Optional[str]:
    # JSON-LD author / creator
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
            if isinstance(author, dict) and author.get("name"):
                return str(author["name"]).strip()
            if isinstance(author, str) and author.strip():
                return author.strip()

    # Printables packs the designer in the og:title: "Title by Author | …"
    if title:
        m = re.search(r"\bby\s+([^|]+?)(?:\s*\|\s*|$)", title)
        if m:
            return m.group(1).strip()
    return None


def _looks_generic(platform: str, title: Optional[str], description: Optional[str], thumbnail: Optional[str]) -> bool:
    if platform == "makerworld":
        if thumbnail and "og-icon" in thumbnail:
            return True
        if description and "leading 3D printing model community" in description:
            return True
    return False


def _fetch_via_proxy(url: str) -> httpx.Response:
    """Fetch url through the Cloudflare Worker proxy, returning an httpx.Response-like object."""
    proxy_url = _CF_PROXY_URL + "?" + urlencode({"url": url, "token": _CF_PROXY_SECRET})
    with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as c:
        resp = c.get(proxy_url)
    # Surface the original URL from the proxy response header if available
    proxied_url = resp.headers.get("x-proxied-url", url)
    proxied_status = int(resp.headers.get("x-proxied-status", resp.status_code))
    # Patch status_code so downstream error handling sees the real target's status
    resp._proxied_url = proxied_url
    resp._proxied_status = proxied_status
    return resp


def extract(url: str) -> dict:
    """Fetch and parse a model URL.

    Returns a dict with keys: platform, title, designer, thumbnail_url, source_url.
    Raises ImportError_ when extraction fails in a way the client should surface.
    """
    if not url or not url.startswith(("http://", "https://")):
        raise ImportError_("Provide a full http(s) URL")

    platform = detect_platform(url)
    use_proxy = platform == "makerworld" and bool(_CF_PROXY_URL and _CF_PROXY_SECRET)

    try:
        if use_proxy:
            r = _fetch_via_proxy(url)
            effective_url = getattr(r, "_proxied_url", url)
            effective_status = getattr(r, "_proxied_status", r.status_code)
            logger.info("makerworld proxy fetch: status=%s url=%s", effective_status, effective_url)
        else:
            with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers=_headers_for(platform)) as c:
                r = c.get(url)
            effective_url = str(r.url)
            effective_status = r.status_code
    except httpx.RequestError as e:
        logger.warning("import fetch failed for %s: %s", url, e)
        # Even with a network failure we can sometimes salvage a title from the URL slug.
        slug_title = _title_from_url_slug(url)
        if slug_title:
            return {
                "platform": platform, "title": slug_title, "designer": None,
                "thumbnail_url": None, "source_url": url, "partial": True,
            }
        raise ImportError_("Could not reach that URL")

    if effective_status >= 400:
        # Source blocked us (Cloudflare / Railway IP rep / etc). Try the slug.
        slug_title = _title_from_url_slug(effective_url)
        if slug_title:
            return {
                "platform": platform, "title": slug_title, "designer": None,
                "thumbnail_url": None, "source_url": effective_url, "partial": True,
            }
        if platform == "makerworld":
            raise ImportError_(
                "Makerworld blocks server-side imports — paste the title and photo manually for now"
            )
        raise ImportError_(f"Source returned {effective_status} — try a different URL or paste manually")

    soup = BeautifulSoup(r.text, "html.parser")
    title = _og(soup, "title")
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
    description = _og(soup, "description")
    thumbnail = _og(soup, "image")
    designer = _extract_designer(soup, title)  # uses raw title to pull "by Author" attribution
    if title:
        title = _clean_title(title)

    if _looks_generic(platform, title, description, thumbnail):
        # Page metadata is JS-hydrated. Salvage the title from the URL slug if possible.
        slug_title = _title_from_url_slug(effective_url)
        if slug_title:
            return {
                "platform": platform,
                "title": slug_title,
                "designer": None,
                "thumbnail_url": None,
                "source_url": effective_url,
                "partial": True,
            }
        raise ImportError_(
            "That page doesn't expose metadata to scrapers — paste the title and photo manually "
            "(or use the Chrome extension which reads the rendered page)"
        )

    if not title:
        # Last-ditch: try the slug
        slug_title = _title_from_url_slug(effective_url)
        if slug_title:
            return {
                "platform": platform,
                "title": slug_title,
                "designer": None,
                "thumbnail_url": thumbnail,
                "source_url": effective_url,
                "partial": True,
            }
        raise ImportError_("No title found at that URL")

    return {
        "platform": platform,
        "title": title.strip(),
        "designer": designer,
        "thumbnail_url": thumbnail,
        "source_url": effective_url,
        "partial": False,
    }
