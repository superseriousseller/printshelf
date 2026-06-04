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

Awin network programs (wraps product URL in Awin redirect):
  AWIN_AFFILIATE_ID             Your Awin publisher ID (shared across all Awin merchants)
  ANYCUBIC_AWIN_MERCHANT_ID     Anycubic's Awin merchant ID (69360)
"""
import os
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse

from filament_import_service import detect_store


_AWIN_BASE = "https://www.awin1.com/cread.php"

# Awin network merchants: store → env var holding that merchant's Awin ID.
# The publisher (affiliate) ID is shared — read once from AWIN_AFFILIATE_ID.
_AWIN_MERCHANT = {
    "anycubic": "ANYCUBIC_AWIN_MERCHANT_ID",
}

# Direct affiliate programs: store → (env_var, query_param_name).
_STORE_TAG = {
    "amazon":        ("AMAZON_AFFILIATE_TAG", "tag"),
    "bambu":         ("BAMBU_AFFILIATE_REF", "ref"),
    "polymaker":     ("POLYMAKER_AFFILIATE_REF", "ref"),
    "matterhackers": ("MATTERHACKERS_AFFILIATE_REF", "aff"),
}


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
