"""Amazon Product Advertising API (PA-API 5.0) price refresh — Slice 3 stub.

**UNVERIFIED.** Written against Amazon's public PA-API 5.0 docs (GetItems
operation, AWS SigV4 request signing via botocore) with no sandbox or real
credentials to test against. The signing/request-shape logic in particular is
exactly the kind of thing that can be subtly wrong without a live account —
confirm end-to-end the moment real credentials exist, before trusting output.

No-op until AMAZON_PA_API_ACCESS_KEY / AMAZON_PA_API_SECRET_KEY /
AMAZON_PA_API_PARTNER_TAG are all set. That approval (Associates + PA-API) is
Cam's long-pole item, not this code's — the goal is that when it lands, the
remaining work is "paste credentials, flip the flag," not a second build
cycle. Writes through the exact same fulfillments[].price/checked_at/
availability fields the manual/seed-overlay path uses, so downstream cost
computation has one code path regardless of how a price arrived.
"""
import json
import logging
import os
import re
from datetime import datetime

import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from sqlalchemy.orm.attributes import flag_modified

logger = logging.getLogger(__name__)

_HOST = os.environ.get("AMAZON_PA_API_HOST", "webservices.amazon.com")
_REGION = os.environ.get("AMAZON_PA_API_REGION", "us-east-1")
_MARKETPLACE = os.environ.get("AMAZON_PA_API_MARKETPLACE", "www.amazon.com")
_ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", re.IGNORECASE)


def amazon_pa_api_enabled() -> bool:
    """Fails closed: all three credentials must be set, same pattern as the
    other feature flags in this codebase."""
    return bool(
        os.environ.get("AMAZON_PA_API_ACCESS_KEY")
        and os.environ.get("AMAZON_PA_API_SECRET_KEY")
        and os.environ.get("AMAZON_PA_API_PARTNER_TAG")
    )


def _extract_asin(url: str):
    if not url:
        return None
    m = _ASIN_RE.search(url)
    return m.group(1) if m else None


def _sign_request(payload: dict) -> httpx.Response:
    """POST GetItems, signed with SigV4 via botocore (reuses AWS's own tested
    signer rather than hand-rolling HMAC-SHA256 canonical-request construction)."""
    body = json.dumps(payload)
    request = AWSRequest(
        method="POST",
        url=f"https://{_HOST}/paapi5/getitems",
        data=body,
        headers={
            "content-encoding": "amz-1.0",
            "content-type": "application/json; charset=utf-8",
            "host": _HOST,
            "x-amz-target": "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.GetItems",
        },
    )
    creds = Credentials(
        os.environ["AMAZON_PA_API_ACCESS_KEY"],
        os.environ["AMAZON_PA_API_SECRET_KEY"],
    )
    SigV4Auth(creds, "ProductAdvertisingAPI", _REGION).add_auth(request)
    with httpx.Client(timeout=10.0) as client:
        return client.post(request.url, content=body, headers=dict(request.headers))


def _get_items(asins: list[str]) -> dict:
    """Returns {asin: price_or_None}. Raises on transport error — caller decides
    whether to treat a failed batch as 'unknown' rather than 'dead'."""
    payload = {
        "ItemIds": asins,
        "PartnerTag": os.environ["AMAZON_PA_API_PARTNER_TAG"],
        "PartnerType": "Associates",
        "Marketplace": _MARKETPLACE,
        "Resources": ["Offers.Listings.Price"],
    }
    resp = _sign_request(payload)
    resp.raise_for_status()
    data = resp.json()
    prices = {}
    for item in data.get("ItemsResult", {}).get("Items", []):
        asin = item.get("ASIN")
        listings = item.get("Offers", {}).get("Listings", [])
        price = listings[0]["Price"]["Amount"] if listings else None
        prices[asin] = price
    return prices


def refresh_amazon_prices(db) -> dict:
    """No-op (returns immediately) until amazon_pa_api_enabled(). Otherwise
    batches every Amazon-vendor fulfillment across the instruments registry by
    ASIN (extracted from the URL), refreshes price + checked_at through PA-API,
    and marks a batch as 'unknown' (never 'dead') on any transport error —
    same flakiness-tolerance rule as the dead-link checker."""
    if not amazon_pa_api_enabled():
        logger.info("Amazon PA-API not configured — skipping refresh")
        return {"skipped": True}

    from models import RegistryEntry  # local import: avoid a hard models<->this-module cycle

    now = datetime.utcnow()
    entries = db.query(RegistryEntry).filter(RegistryEntry.vertical == "instruments").all()

    # asin -> list of (entry, fulfillment) so one PA-API batch updates every match
    by_asin: dict = {}
    for entry in entries:
        for item in entry.bom or []:
            for fulfillment in item.get("fulfillments", []):
                asin = _extract_asin(fulfillment.get("url"))
                if asin and (fulfillment.get("vendor") or "").lower() == "amazon":
                    by_asin.setdefault(asin, []).append((entry, fulfillment))

    if not by_asin:
        return {"skipped": False, "checked": 0}

    asins = list(by_asin.keys())
    checked = 0
    try:
        # PA-API GetItems caps at 10 ASINs per request
        prices = {}
        for i in range(0, len(asins), 10):
            prices.update(_get_items(asins[i:i + 10]))
    except (httpx.HTTPError, KeyError, ValueError) as e:
        logger.warning("Amazon PA-API refresh failed, leaving prices as-is: %s", e)
        return {"skipped": False, "error": str(e)}

    touched_entries = set()
    for asin, price in prices.items():
        if price is None:
            continue
        for entry, fulfillment in by_asin.get(asin, []):
            fulfillment["price"] = price
            fulfillment["checked_at"] = now.isoformat()
            fulfillment["availability"] = "ok"
            touched_entries.add(id(entry))
            checked += 1

    for entry in entries:
        if id(entry) in touched_entries:
            flag_modified(entry, "bom")

    db.commit()
    logger.info("Amazon PA-API refresh complete: %d fulfillments updated", checked)
    return {"skipped": False, "checked": checked}
