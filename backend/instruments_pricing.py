"""Cost computation for the instruments registry (Slice 3).

Nothing here is stored or cached: spool/build/play cost is computed fresh from
RegistryEntry.filament_usage + .bom + the FilamentPrice table on every render,
so a number can never go stale independent of its own inputs.

Three states per tier, matching the rest of the registry's honesty pattern
(the same affirmative/source-needed/pending shape the BOM rendering already
uses, extended to cost):
  - pending     -> the input doesn't exist yet (e.g. no filament_usage) -> None
  - incomplete  -> we know what's needed but a required item has no usable
                   price yet ("source needed") -> None
  - real        -> spool is a single float; build/play are (low, high) pairs,
                   collapsing to one number when there's no multi-vendor spread

A fulfillment stops being "usable" for cost math the moment its own price
would be hidden as stale (>180d) or marked dead — a hidden number shouldn't
silently power a visible one.
"""
from datetime import datetime, timedelta

STALE_AGING_DAYS = 90
STALE_HIDE_DAYS = 180


def _parse_dt(value):
    """checked_at is stored as an ISO string inside JSON columns (JSON has no
    native datetime type) — parse back to a datetime, or None if unparseable."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def staleness_state(checked_at) -> str:
    """Returns 'none' | 'fresh' | 'aging' | 'stale' for a checked_at value
    (ISO string or datetime or None)."""
    dt = _parse_dt(checked_at)
    if dt is None:
        return "none"
    age = datetime.utcnow() - dt
    if age > timedelta(days=STALE_HIDE_DAYS):
        return "stale"
    if age > timedelta(days=STALE_AGING_DAYS):
        return "aging"
    return "fresh"


def _usable_fulfillments(fulfillments):
    """Fulfillments eligible for cost math: has a price, not marked dead, and
    not past the staleness auto-hide threshold."""
    usable = []
    for f in fulfillments or []:
        if f.get("availability") == "dead":
            continue
        if f.get("price") is None:
            continue
        if staleness_state(f.get("checked_at")) == "stale":
            continue
        usable.append(f)
    return usable


def compute_spool_cost(filament_usage, price_table: dict):
    """price_table: {material: price_per_kg}. Returns float or None (pending —
    either no filament_usage yet, or a material isn't in the price table)."""
    if not filament_usage:
        return None
    total = 0.0
    for item in filament_usage:
        price = price_table.get(item.get("material"))
        if price is None:
            return None  # any unpriced material -> pending, never a partial/wrong number
        total += (item.get("grams") or 0) * price / 1000.0
    return total


def _tier_spread(bom, tier: str, base_low: float, base_high: float):
    """Layers one cost tier ("build" or "play") on top of a base (low, high).
    Returns None ('incomplete') if any item in this tier has zero usable
    fulfillments — a partial sum would understate the true cost, so we show
    'incomplete' rather than a number that looks precise but is wrong."""
    low, high = base_low, base_high
    for item in bom or []:
        if item.get("tier") != tier:
            continue
        usable = _usable_fulfillments(item.get("fulfillments"))
        if not usable:
            return None
        prices = [f["price"] for f in usable]
        low += min(prices)
        high += max(prices)
    return (low, high)


def compute_costs(entry, price_table: dict) -> dict:
    """entry: a RegistryEntry. Returns {"spool": float|None,
    "build": (low,high)|None, "play": (low,high)|None}."""
    spool = compute_spool_cost(entry.filament_usage, price_table)
    if spool is None:
        return {"spool": None, "build": None, "play": None}

    build = _tier_spread(entry.bom, "build", spool, spool)
    if build is None:
        return {"spool": spool, "build": None, "play": None}

    play = _tier_spread(entry.bom, "play", build[0], build[1])
    return {"spool": spool, "build": build, "play": play}
