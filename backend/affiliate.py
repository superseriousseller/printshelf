"""Affiliate-link rewriter for filament source URLs.

Bare URLs are stored in the DB — tags are injected at click-time by the
`/dashboard/filaments/{id}/buy` redirector. That keeps us aligned with
Amazon Associates' ToS (which prohibits long-term storage of affiliate-
tagged links outside their API) and lets us swap tags later without a
data migration.

Tags come from env vars. An empty/unset tag means "redirect to the bare
URL" — useful before Cam has signed up for a given affiliate program.

Direct affiliate programs (appends ?param=tag to the product URL):
  AMAZON_AFFILIATE_TAG          Amazon Associates tracking id (e.g. "printshelf-20")
  BAMBU_AFFILIATE_REF           Bambu Lab Store referral code
  POLYMAKER_AFFILIATE_REF       Polymaker (Refersion) referral code
  MATTERHACKERS_AFFILIATE_REF   MatterHackers referral code
  SUNLU_AFFILIATE_REF           SUNLU sca_ref token (e.g. "9625568.zGmL14Ga1b")

Impact network programs (appends irpid + attribution flags to product URL):
  FLASHFORGE_IMPACT_PID         FlashForge Impact publisher ID (7371845)

Awin network programs (wraps product URL in Awin redirect):
  AWIN_AFFILIATE_ID             Your Awin publisher ID (shared across all Awin merchants)
  ANYCUBIC_AWIN_MERCHANT_ID     Anycubic's Awin merchant ID (69360)
"""
import os
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse

from filament_import_service import detect_store

# Domains from which Print Links are accepted. Only supported affiliate
# stores — ensures every saved link gets a tag and prevents spam/off-topic links.
_ALLOWED_LINK_DOMAINS: frozenset[str] = frozenset({
    "www.amazon.com", "amazon.com", "amzn.to",
    "us.store.bambulab.com", "eu.store.bambulab.com", "store.bambulab.com",
    "us.polymaker.com", "polymaker.com", "shop.polymaker.com",
    "store.anycubic.com",
    "www.matterhackers.com", "matterhackers.com",
    "store.sunlu.com", "www.sunlu.com", "sunlu.com",
    "www.flashforge.com", "flashforge.com",
})


def is_allowed_link_domain(url: str) -> bool:
    """Return True if url is from a supported affiliate store."""
    if not url or not url.startswith(("http://", "https://")):
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
        return host in _ALLOWED_LINK_DOMAINS
    except Exception:
        return False


_AWIN_BASE = "https://www.awin1.com/cread.php"

# Awin network merchants: store → env var holding that merchant's Awin ID.
# The publisher (affiliate) ID is shared — read once from AWIN_AFFILIATE_ID.
_AWIN_MERCHANT = {
    "anycubic": "ANYCUBIC_AWIN_MERCHANT_ID",
}

# Impact network merchants: store → env var holding the publisher ID (irpid).
# Static params (irgwc, afsrc, utm_source) appended alongside irpid.
# irclickid is skipped — Impact falls back to cookie-based attribution.
_IMPACT_MERCHANT = {
    "flashforge": "FLASHFORGE_IMPACT_PID",
}

# Direct affiliate programs: store → (env_var, query_param_name).
_STORE_TAG = {
    "amazon":        ("AMAZON_AFFILIATE_TAG", "tag"),
    "bambu":         ("BAMBU_AFFILIATE_REF", "ref"),
    "polymaker":     ("POLYMAKER_AFFILIATE_REF", "ref"),
    "matterhackers": ("MATTERHACKERS_AFFILIATE_REF", "aff"),
    "sunlu":         ("SUNLU_AFFILIATE_REF", "sca_ref"),
}


def _impact_url(url: str, pid: str) -> str:
    _IMPACT_PARAMS = {"irpid", "irgwc", "afsrc", "utm_source"}
    parsed = urlparse(url)
    pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if k not in _IMPACT_PARAMS]
    pairs += [("irpid", pid), ("irgwc", "1"), ("afsrc", "1"), ("utm_source", "impact")]
    return urlunparse(parsed._replace(query=urlencode(pairs)))


def _awin_url(destination: str, merchant_id: str) -> str:
    affiliate_id = (os.environ.get("AWIN_AFFILIATE_ID") or "").strip()
    if not affiliate_id:
        return destination
    return f"{_AWIN_BASE}?awinmid={merchant_id}&awinaffid={affiliate_id}&ued={quote_plus(destination)}"


def _tag_for(store: str) -> tuple[str, str] | None:
    spec = _STORE_TAG.get(store)
    if spec is None:
        return None
    env_var, param = spec
    tag = (os.environ.get(env_var) or "").strip()
    if not tag:
        return None
    return param, tag


def apply_affiliate(url: str) -> str:
    """Return `url` with the appropriate affiliate tag added (or replaced).

    No-ops when:
      - the URL isn't from a known store
      - no affiliate env var is set for that store
      - the URL is malformed
    """
    if not url or not url.startswith(("http://", "https://")):
        return url
    store = detect_store(url)

    # Impact network: append irpid + static attribution flags.
    impact_env = _IMPACT_MERCHANT.get(store)
    if impact_env:
        pid = (os.environ.get(impact_env) or "").strip()
        if pid:
            return _impact_url(url, pid)
        return url

    # Awin network: wrap the URL in an Awin redirect.
    merchant_env = _AWIN_MERCHANT.get(store)
    if merchant_env:
        merchant_id = (os.environ.get(merchant_env) or "").strip()
        if merchant_id:
            return _awin_url(url, merchant_id)
        return url

    # Direct programs: append ?param=tag.
    spec = _tag_for(store)
    if spec is None:
        return url
    param, tag = spec
    parsed = urlparse(url)
    # Replace any existing value for this param so we never double up.
    pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != param]
    pairs.append((param, tag))
    return urlunparse(parsed._replace(query=urlencode(pairs)))


# Brand → store-search URL template ({q} = URL-encoded query). Buy-link fallback
# for filaments with no exact product URL. Substring-matched against the brand
# (spaces stripped) so "Bambu Lab"/"BAMBULAB" → bambu, "Matter Hackers" → mh.
# Search paths verified live (2026-06-27).
_BRAND_SEARCH: list[tuple[str, str]] = [
    ("bambu",         "https://us.store.bambulab.com/search?q={q}"),
    ("polyterra",     "https://us.polymaker.com/search?q={q}"),
    ("polylite",      "https://us.polymaker.com/search?q={q}"),
    ("panchroma",     "https://us.polymaker.com/search?q={q}"),
    ("polymaker",     "https://us.polymaker.com/search?q={q}"),
    ("sunlu",         "https://store.sunlu.com/search?q={q}"),
    ("anycubic",      "https://store.anycubic.com/search?q={q}"),
    ("matterhackers", "https://www.matterhackers.com/store/c?q={q}"),
    ("flashforge",    "https://www.flashforge.com/search?q={q}"),
]


def _search_query(*parts: str) -> str:
    return quote_plus(" ".join(p.strip() for p in parts if p and p.strip()))


def store_search_url(brand: str, material: str = "", color: str = "", finish: str = "") -> str | None:
    """Affiliate-tagged 'Buy' link for a filament with no product URL.

    Searches the brand's own store for the material/finish/color; brands with no
    dedicated store fall back to an Amazon search (which carries ~every brand).
    Returns None only when the brand is blank. The affiliate tag is applied via
    apply_affiliate, so the link works bare today and monetizes once the ref is set.
    """
    brand = (brand or "").strip()
    if not brand:
        return None
    key = brand.lower().replace(" ", "")
    for needle, tmpl in _BRAND_SEARCH:
        if needle in key:
            return apply_affiliate(tmpl.format(q=_search_query(material, finish, color)))
    # Catch-all: brand has no dedicated store → Amazon search (brand in the query).
    return apply_affiliate("https://www.amazon.com/s?k=" + _search_query(brand, material, finish, color))


def filament_buy_url(
    brand: str = "", material: str = "", color: str = "", finish: str = "", source_url: str = "",
) -> str | None:
    """Best Buy URL for a filament: its product URL (affiliate-tagged) if present,
    otherwise a store-search fallback by brand. None when neither is available."""
    if source_url:
        return apply_affiliate(source_url)
    return store_search_url(brand, material, color, finish)
