"""Seed registry_entries (instruments vertical) from the HTML prototype.

Parses REGISTRY + FRONTIER out of docs/instruments/printable-instruments-index.html
and upserts RegistryEntry rows keyed on (vertical, slug) — safe to re-run.

Nothing is invented: filament_usage, retail prices, effort_*, objective_score
all stay null. Only function_axis (from the HTML's playability `level`) has
real seed data. Rendered cost/price surfaces must show "pending verification"
for anything null, never a fabricated number.

Usage:
    DATABASE_URL=postgresql://... python backend/scripts/seed_instruments.py [--dry-run]
"""
import html
import json
import os
import re
import sys
from datetime import datetime

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import RegistryEntry, SessionLocal, slugify  # noqa: E402

DRY_RUN = "--dry-run" in sys.argv
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML_PATH = os.path.join(_REPO_ROOT, "docs", "instruments", "printable-instruments-index.html")
OVERLAY_PATH = os.path.join(_REPO_ROOT, "seed", "instruments_overlay.yaml")

TAG_RE = re.compile(r"<[^>]+>")
NONE_PREFIX_RE = re.compile(r"^none\b", re.IGNORECASE)


def _extract_array(source: str, varname: str) -> str:
    m = re.search(r"const " + varname + r" = (\[.*?\n\]);", source, re.S)
    if not m:
        raise ValueError(f"couldn't find `const {varname} = [...]` in {HTML_PATH}")
    return m.group(1)


def _js_array_to_json(raw: str) -> str:
    """Convert this file's restricted JS-object-literal subset to JSON.

    Handles: whole-line `//` comments (never inline — this file's URLs
    contain `//` too, so an inline-comment strip would truncate them),
    unquoted object keys, trailing commas. Safe because this is Cam's own
    controlled, consistent-format data — not arbitrary/untrusted JS.
    """
    s = re.sub(r"^[ \t]*//.*\n", "", raw, flags=re.M)
    s = re.sub(r"([{,]\s*)(\w+):", r'\1"\2":', s)
    s = re.sub(r",\s*([\]}])", r"\1", s)
    return s


def _clean(value):
    """Empty string -> None; otherwise pass through."""
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _strip_html(value):
    if not value:
        return value
    return html.unescape(TAG_RE.sub("", value)).strip()


def _bom_from_non_printed(non_printed: str):
    """Returns (bom_list, note_suffix). 'None'-prefixed strings seed as an
    empty BOM (not a fake part to source) with any remainder folded into note."""
    non_printed = (non_printed or "").strip()
    if not non_printed:
        return [], None
    if NONE_PREFIX_RE.match(non_printed):
        remainder = non_printed
        return [], remainder
    return [{
        "spec": non_printed,
        "qty": 1,
        "tier": "build",
        "consumable": False,
        "fulfillments": [],  # empty = "source needed" (spec's own dead-link handling), nothing invented
    }], None


def _build_note(base_note: str, bed: str, filament: str, bom_note_suffix: str) -> str:
    lines = []
    if bed:
        lines.append(f"Bed: {bed}")
    if filament:
        lines.append(f"Suggested material: {filament}")
    if bom_note_suffix:
        lines.append(bom_note_suffix)
    if base_note:
        lines.append(base_note)
    return "\n".join(lines) if lines else None


def registry_to_entry(item: dict) -> dict:
    bom, bom_note_suffix = _bom_from_non_printed(item.get("nonPrinted"))
    return {
        "vertical": "instruments",
        "slug": slugify(item["name"]),
        "name": item["name"],
        "designer": _clean(item.get("by")),
        "family": _clean(item.get("fam")),
        "status": "listed",
        "function_axis": item.get("level"),
        "verified_by_owner": bool(item.get("verified", False)),
        "license": _clean(item.get("license")),
        "source_url": _clean(item.get("source")),
        "demo_url": _clean(item.get("demo")),
        "note": _build_note(_clean(item.get("note")), item.get("bed"), item.get("filament"), bom_note_suffix),
        "bom": bom,
        "filament_usage": [],
        "media": [],
        # Explicitly None (not omitted) so re-seeding with an empty/changed
        # overlay always resets these back — the row dict fully determines
        # final state on every run, no leftover from a prior overlay can
        # survive an upsert that no longer sets these keys.
        "retail_budget_price": None,
        "retail_budget_url": None,
        "retail_budget_checked_at": None,
        "retail_premium_price": None,
        "retail_premium_url": None,
        "retail_premium_checked_at": None,
    }


def frontier_to_entry(item: dict) -> dict:
    return {
        "vertical": "instruments",
        "slug": slugify(item["name"]),
        "name": item["name"],
        "status": "frontier",
        "gap_why": _clean(item.get("why")),
        "gap_status": _clean(item.get("status")),
        "gap_closest": _clean(_strip_html(item.get("closest"))),
        "note": _clean(item.get("note")),
        "bom": [],
        "filament_usage": [],
        "media": [],
        "retail_budget_price": None,
        "retail_budget_url": None,
        "retail_budget_checked_at": None,
        "retail_premium_price": None,
        "retail_premium_url": None,
        "retail_premium_checked_at": None,
    }


def _load_overlay(path: str = OVERLAY_PATH) -> dict:
    """Cam's real numbers (filament grams, BOM fulfillment prices, retail
    refs), layered onto the HTML-derived base data at seed time. Keyed by
    slug — see seed/instruments_overlay.yaml for the format. The overlay is
    the source of truth for these fields on every run (re-running the seed
    re-applies it, never clobbers it with HTML-only data), so it's always
    safe to add/edit entries here and reseed. Missing file -> empty, fine."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _apply_overlay(row: dict, overlay_entry: dict, now: datetime) -> dict:
    """Merges one slug's overlay data onto its HTML-derived base row. A
    fulfillment provided this way is being actively verified right now, so it
    gets checked_at=now + availability='ok' immediately (not left null like
    the HTML-only seed placeholders)."""
    if not overlay_entry:
        return row

    if "filament_usage" in overlay_entry:
        row["filament_usage"] = overlay_entry["filament_usage"]

    for match in overlay_entry.get("bom_fulfillments", []):
        target = next(
            (item for item in row["bom"] if match["match"].lower() in item["spec"].lower()),
            None,
        )
        if target is None:
            print(f"  WARNING: overlay bom_fulfillments match {match['match']!r} not found in {row['slug']}'s bom — skipped")
            continue
        target["fulfillments"] = [
            {
                "vendor": f.get("vendor"),
                "url": f.get("url"),
                "price": f.get("price"),
                "currency": f.get("currency", "USD"),
                "checked_at": now.isoformat(),
                "availability": "ok",
                "affiliate": f.get("affiliate", False),
            }
            for f in match.get("fulfillments", [])
        ]

    for field in ("retail_budget", "retail_premium"):
        if field in overlay_entry:
            row[f"{field}_price"] = overlay_entry[field].get("price")
            row[f"{field}_url"] = overlay_entry[field].get("url")
            row[f"{field}_checked_at"] = now  # real DateTime column, not the JSON-embedded string form above

    return row


def main():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        source = f.read()

    registry = json.loads(_js_array_to_json(_extract_array(source, "REGISTRY")))
    frontier = json.loads(_js_array_to_json(_extract_array(source, "FRONTIER")))
    print(f"Parsed {len(registry)} REGISTRY + {len(frontier)} FRONTIER entries")

    overlay = _load_overlay()
    if overlay:
        print(f"Loaded overlay for {len(overlay)} entrie(s) from {OVERLAY_PATH}")

    now = datetime.utcnow()
    rows = [registry_to_entry(item) for item in registry] + [frontier_to_entry(item) for item in frontier]
    rows = [_apply_overlay(row, overlay.get(row["slug"]), now) for row in rows]

    db = SessionLocal()
    created, updated = 0, 0
    try:
        for row in rows:
            existing = (
                db.query(RegistryEntry)
                .filter(RegistryEntry.vertical == row["vertical"], RegistryEntry.slug == row["slug"])
                .first()
            )
            if existing:
                for key, value in row.items():
                    setattr(existing, key, value)
                updated += 1
                action = "UPDATE"
            else:
                db.add(RegistryEntry(**row))
                created += 1
                action = "CREATE"

            if DRY_RUN:
                fulfilled = sum(1 for item in row["bom"] for f in item.get("fulfillments", []))
                extra = f", filament_usage={len(row.get('filament_usage') or [])}, fulfillments={fulfilled}" if (row.get("filament_usage") or fulfilled) else ""
                print(f"  [{action}] {row['vertical']}/{row['slug']} — {row['name']} (status={row['status']}, bom={len(row['bom'])} item(s){extra})")

        if DRY_RUN:
            db.rollback()
            print(f"\nDRY RUN — would create {created}, update {updated}. No changes written.")
        else:
            db.commit()
            print(f"\nDone — created {created}, updated {updated}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
