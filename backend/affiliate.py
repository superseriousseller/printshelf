"""Affiliate-link rewriter for filament source URLs.

Bare URLs are stored in the DB — tags are injected at click-time by the
`/dashboard/filaments/{id}/buy` redirector. That keeps us aligned with
Amazon Associates' ToS (which prohibits long-term storage of affiliate-
tagged links outside their API) and lets us swap tags later without a
data migration.

Tags come from env vars. An empty/unset tag means "redirect to the bare
URL" — useful before Cam has signed up for a given affiliate program.

Env vars read:
  AMAZON_AFFILIATE_TAG          Amazon Associates tracking id (e.g. "printshelf-20")
  BAMBU_AFFILIATE_REF           Bambu Lab Store referral code
  POLYMAKER_AFFILIATE_REF       Polymaker (Refersion) referral code
  MATTERHACKERS_AFFILIATE_REF   MatterHackers referral code
  ANYCUBIC_AFFILIATE_REF        Anycubic referral code
"""
import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from filament_import_service import detect_store


# Map of store → (env_var_name, query_param_name).
# Query param defaults below are the canonical names used by each
# affiliate program. If a program uses a path-based scheme instead of
# a query param we'd extend this dict with a callable; for now all
# five stores use ?param=tag.
_STORE_TAG = {
    "amazon":        ("AMAZON_AFFILIATE_TAG", "tag"),
    "bambu":         ("BAMBU_AFFILIATE_REF", "ref"),
    "polymaker":     ("POLYMAKER_AFFILIATE_REF", "ref"),
    "matterhackers": ("MATTERHACKERS_AFFILIATE_REF", "aff"),
    "anycubic":      ("ANYCUBIC_AFFILIATE_REF", "ref"),
}


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
    spec = _tag_for(store)
    if spec is None:
        return url
    param, tag = spec
    parsed = urlparse(url)
    # Replace any existing value for this param (a competitor's tag, an
    # old tag of ours, etc.) so we never double up or honor a stale ref.
    pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != param]
    pairs.append((param, tag))
    return urlunparse(parsed._replace(query=urlencode(pairs)))
