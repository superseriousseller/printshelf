"""Filament product URL → metadata extractor.

Sister module to import_service.py (which handles model pages). This one
targets filament retailer product pages and extracts brand / material /
color / price for pre-filling the "Add filament" form.

Supported stores (decided in scoping):
  amazon         Amazon Associates. og:title is usually present; the
                 facebookexternalhit UA fares better than browser UAs
                 against Amazon's bot defenses. Brand falls out of
                 og:site_name or the product title; we never persist
                 the affiliate tag — it's injected at click-time.
  bambu          us.store.bambulab.com / store.bambulab.com — clean
                 og tags, brand is always "Bambu Lab".
  polymaker      us.polymaker.com — clean og tags, brand "Polymaker".
  matterhackers  matterhackers.com — clean og tags; brand is the
                 in-title manufacturer (we read JSON-LD `brand` when
                 present, else fall back to "MatterHackers").
  anycubic       store.anycubic.com — clean og tags, brand "Anycubic".

When extraction succeeds partially (e.g. Amazon blocks the request and
we can only recover a slug-title), the result includes `partial=True`
so the UI can warn the user to fill in the rest manually.
"""
import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from import_service import (
    BROWSER_HEADERS,
    UNFURL_HEADERS,
    REQUEST_TIMEOUT,
    ImportError_,
    _og,
    _title_from_url_slug,
)

logger = logging.getLogger(__name__)


# Materials we recognize in a product title. Order matters: longer/more
# specific names first so "PLA-CF" matches before "PLA".
MATERIALS = [
    "PLA-CF", "PETG-CF", "PA-CF", "PA12-CF", "PAHT-CF", "PET-CF",
    "PLA Pro", "PLA+", "PLA Plus", "PLA Matte", "PLA Silk", "PLA Basic",
    "PETG HF", "PETG",
    "ABS", "ASA",
    "TPU", "TPE",
    "PC", "PA", "PVA", "HIPS",
    "Nylon", "Wood", "Carbon Fiber",
    "PLA",
]

# Color words we look for as a last-resort heuristic. Most filament
# product titles include the color near the end ("… 1kg Galaxy Black"),
# so we scan the title for any of these tokens.
COLORS = [
    "Black", "White", "Gray", "Grey", "Silver", "Gold", "Bronze", "Copper",
    "Red", "Orange", "Yellow", "Green", "Blue", "Purple", "Pink", "Magenta",
    "Cyan", "Brown", "Beige", "Tan", "Clear", "Transparent", "Natural",
    "Galaxy", "Jade", "Matte", "Silk", "Glow", "Marble", "Wood",
]


def detect_store(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "amazon." in host or host.startswith("amzn."):
        return "amazon"
    if "bambulab.com" in host:
        return "bambu"
    if "polymaker.com" in host:
        return "polymaker"
    if "matterhackers.com" in host:
        return "matterhackers"
    if "anycubic.com" in host:
        return "anycubic"
    if "sunlu.com" in host:
        return "sunlu"
    return "manual"


# Per-store default brand. Many filament retailers also sell other brands
# (MatterHackers) so we keep these as a fallback only.
_DEFAULT_BRAND = {
    "bambu": "Bambu Lab",
    "polymaker": "Polymaker",
    "anycubic": "Anycubic",
    "matterhackers": "MatterHackers",
}


def _headers_for(store: str) -> dict:
    # Amazon serves leaner OG metadata to crawlers than to browsers, and
    # Cloudflare-fronted browser-UA requests from Railway IPs get challenged.
    if store == "amazon":
        return UNFURL_HEADERS
    return BROWSER_HEADERS


def _detect_material(text: str) -> Optional[str]:
    """First-match material lookup in product title/description.

    Uses word-boundary regex so short tokens like "PA" don't match inside
    "Panchroma" or "PASTEL". Order in MATERIALS still controls preference
    (longest/most-specific first).
    """
    if not text:
        return None
    for mat in MATERIALS:
        # `\b` doesn't work around "+", so we anchor a custom boundary
        # for tokens that end in non-word chars (PLA+, PETG+, etc.).
        pattern = re.escape(mat)
        if mat[-1].isalnum():
            pattern = rf"(?<!\w){pattern}(?!\w)"
        else:
            pattern = rf"(?<!\w){pattern}"
        if re.search(pattern, text, flags=re.IGNORECASE):
            if mat.lower() in ("pla plus", "pla+"):
                return "PLA+"
            return mat
    return None


def _detect_color(title: str, material: Optional[str], brand: Optional[str]) -> Optional[str]:
    """Heuristic: strip brand/material/common-noise from the title and keep what's left,
    then look for any known color word. Returns the matched word(s) or None."""
    if not title:
        return None
    stripped = title
    for noise in [brand, material, "1kg", "1 kg", "0.5kg", "500g", "1.75mm", "2.85mm", "3D Printer Filament", "Filament", "Spool"]:
        if not noise:
            continue
        stripped = re.sub(re.escape(noise), "", stripped, flags=re.IGNORECASE)
    # Look for a known color token (case-insensitive). Prefer two-word combos like "Galaxy Black".
    lowered = stripped.lower()
    for c1 in COLORS:
        for c2 in COLORS:
            if c1 == c2:
                continue
            combo = f"{c1} {c2}".lower()
            if combo in lowered:
                return f"{c1} {c2}"
    for c in COLORS:
        if re.search(rf"\b{re.escape(c)}\b", stripped, flags=re.IGNORECASE):
            return c.capitalize()
    return None


def _extract_brand_from_jsonld(soup: BeautifulSoup) -> Optional[str]:
    """JSON-LD Product schemas almost always include `brand.name`."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            brand = node.get("brand")
            if isinstance(brand, dict) and brand.get("name"):
                return str(brand["name"]).strip()
            if isinstance(brand, str) and brand.strip():
                return brand.strip()
    return None


def _extract_amazon_brand(soup: BeautifulSoup, title: str) -> Optional[str]:
    """Amazon doesn't reliably include brand in JSON-LD. Try DOM sources."""
    # 1. bylineInfo element — "Visit the SUNLU Store" or "Brand: SUNLU"
    byline = soup.find(id="bylineInfo")
    if byline:
        text = byline.get_text(" ", strip=True)
        m = re.search(r"Visit the (.+?) Store", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r"Brand[:\s]+([A-Za-z0-9][A-Za-z0-9\s&+'\-]{0,30})", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # 2. Product details table (desktop layout uses th/td pairs)
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) >= 2 and "brand" in cells[0].get_text(strip=True).lower():
            val = cells[1].get_text(strip=True)
            if val and len(val) < 50:
                return val

    # 3. Heuristic: first token of the title if it looks like a brand word
    #    (all-caps acronym like "SUNLU", "HATCHBOX", or a short CamelCase word)
    if title:
        first = title.split()[0] if title.split() else ""
        if first and re.match(r'^[A-Z]{2,}$|^[A-Z][a-z]+[A-Z]', first):
            return first

    return None


def _extract_price_from_jsonld(soup: BeautifulSoup) -> Optional[float]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            offers = node.get("offers")
            if isinstance(offers, dict):
                p = offers.get("price") or offers.get("lowPrice")
                if p is not None:
                    try:
                        return float(p)
                    except (TypeError, ValueError):
                        continue
            if isinstance(offers, list) and offers:
                first = offers[0]
                if isinstance(first, dict) and first.get("price") is not None:
                    try:
                        return float(first["price"])
                    except (TypeError, ValueError):
                        continue
    return None


def _price_from_og(soup: BeautifulSoup) -> Optional[float]:
    p = _og(soup, "price:amount") or _og(soup, "product:price:amount")
    if p:
        try:
            return float(p)
        except ValueError:
            return None
    return None


def extract(url: str) -> dict:
    """Fetch and parse a filament product URL.

    Returns a dict with keys: store, brand, material, color_name, price,
    source_url, thumbnail_url, partial. Raises ImportError_ when the
    URL is unusable.
    """
    if not url or not url.startswith(("http://", "https://")):
        raise ImportError_("Provide a full http(s) URL")

    store = detect_store(url)

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers=_headers_for(store)) as c:
            r = c.get(url)
    except httpx.RequestError as e:
        logger.warning("filament import fetch failed for %s: %s", url, e)
        slug_title = _title_from_url_slug(url)
        if slug_title:
            return _partial_from_title(store, slug_title, url)
        raise ImportError_("Could not reach that URL")

    if r.status_code >= 400:
        slug_title = _title_from_url_slug(str(r.url))
        if slug_title:
            return _partial_from_title(store, slug_title, str(r.url))
        raise ImportError_(f"Source returned {r.status_code} — paste the fields manually")

    soup = BeautifulSoup(r.text, "html.parser")
    title = _og(soup, "title")
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        slug_title = _title_from_url_slug(str(r.url))
        if slug_title:
            return _partial_from_title(store, slug_title, str(r.url))
        raise ImportError_("No product title found at that URL")

    # Strip noise like " | Polymaker", " - Bambu Lab US Store"
    title = re.split(r"\s+[|–\-]\s+", title)[0].strip()

    brand = _extract_brand_from_jsonld(soup)
    if not brand and store == "amazon":
        brand = _extract_amazon_brand(soup, title)
    brand = brand or _DEFAULT_BRAND.get(store)
    material = _detect_material(title) or _detect_material(_og(soup, "description") or "")
    color = _detect_color(title, material, brand)
    price = _price_from_og(soup) or _extract_price_from_jsonld(soup)
    thumbnail = _og(soup, "image")

    logger.info(
        "filament import ok store=%s brand=%s material=%s color=%s price=%s url=%s",
        store, brand, material, color, price, url,
    )

    return {
        "store": store,
        "brand": brand,
        "material": material,
        "color_name": color,
        "price": price,
        "source_url": str(r.url),
        "thumbnail_url": thumbnail,
        "title": title,
        "partial": False,
    }


def _partial_from_title(store: str, title: str, url: str) -> dict:
    """When the page blocked us but a slug-derived title is available."""
    brand = _DEFAULT_BRAND.get(store)
    material = _detect_material(title)
    color = _detect_color(title, material, brand)
    return {
        "store": store,
        "brand": brand,
        "material": material,
        "color_name": color,
        "price": None,
        "source_url": url,
        "thumbnail_url": None,
        "title": title,
        "partial": True,
    }
