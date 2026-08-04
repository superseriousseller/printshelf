"""One-shot backfill: fills thumbnail_url for prints that have none.

Reuses the exact extraction paths the live import pipeline uses
(import_service.py) so results match what a fresh import would produce:
  - makerworld:  design API (coverUrl), same as _extract_makerworld_api
  - printables/thingiverse/cults3d:  og:image, same as extract()
Every resolved URL is HEAD-validated before saving (fail-open on network
error, skip on 4xx/5xx) — same policy as the live pipeline.

Only writes thumbnail_url. Never touches title, designer, or any other field.

Usage:
    DATABASE_URL=postgresql://... python backend/scripts/backfill_thumbnails.py [--dry-run] [--limit N]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text

from import_service import ImportError_, _fetch_json, _makerworld_model_id, _validate_thumbnail, extract

DRY_RUN = "--dry-run" in sys.argv
LIMIT = None
for i, a in enumerate(sys.argv):
    if a == "--limit" and i + 1 < len(sys.argv):
        LIMIT = int(sys.argv[i + 1])

DATABASE_URL = os.environ.get("DATABASE_URL", "").replace("postgres://", "postgresql://", 1)
if not DATABASE_URL:
    sys.exit("DATABASE_URL not set")

USE_PROXY = bool(os.environ.get("CF_FETCH_PROXY_URL") and os.environ.get("CF_FETCH_PROXY_SECRET"))
OG_PLATFORMS = {"printables", "thingiverse", "cults3d"}

engine = create_engine(DATABASE_URL)


def resolve_makerworld(source_url: str):
    """Mirrors import_service._extract_makerworld_api, but surfaces the HTTP
    status so the backfill can log a precise skip reason instead of a bare None."""
    mid = _makerworld_model_id(source_url)
    if not mid:
        return None, "no derivable makerworld id"
    api = f"https://makerworld.com/api/v1/design-service/design/{mid}"
    try:
        status, data = _fetch_json(api, USE_PROXY)
    except Exception as e:
        return None, f"api request error: {e}"
    if status >= 400:
        return None, f"api returned {status}"
    if not isinstance(data, dict):
        return None, "api returned nothing"
    cover = (data.get("coverUrl") or "").strip() or None
    if not cover:
        return None, "api response had no coverUrl"
    validated = _validate_thumbnail(cover)
    if not validated:
        return None, "cover URL failed HEAD validation (4xx/5xx)"
    return validated, None


def resolve_og(source_url: str):
    """Printables / Thingiverse / Cults3D via the shared og:image extractor.
    extract() only HEAD-validates for makerworld internally, so validate here too."""
    try:
        result = extract(source_url)
    except ImportError_ as e:
        return None, f"extractor failed: {e}"
    thumb = result.get("thumbnail_url")
    if not thumb:
        return None, "no og:image found"
    validated = _validate_thumbnail(thumb)
    if not validated:
        return None, "og:image failed HEAD validation (4xx/5xx)"
    return validated, None


with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT id, title, source_platform, source_url FROM prints "
        "WHERE thumbnail_url IS NULL OR thumbnail_url = '' ORDER BY id"
    )).fetchall()

total_before = len(rows)
print(f"Thumbnail-less prints before this run: {total_before}")
if LIMIT:
    rows = rows[:LIMIT]
    print(f"(limiting to first {LIMIT} for this run)")

resolved = []  # (id, thumbnail_url)
skip_reasons = {}
skip_examples = {}


def _skip(reason: str, print_id: int):
    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
    skip_examples.setdefault(reason, []).append(print_id)


for row in rows:
    if not row.source_url:
        _skip("no source_url", row.id)
        print(f"  [{row.id}] skip: no source_url — {row.title!r}")
        continue

    if row.source_platform == "makerworld":
        thumb, reason = resolve_makerworld(row.source_url)
    elif row.source_platform in OG_PLATFORMS:
        thumb, reason = resolve_og(row.source_url)
    else:
        thumb, reason = None, f"no extractor for platform '{row.source_platform}'"

    if thumb:
        resolved.append((row.id, thumb))
        print(f"  [{row.id}] RESOLVED ({row.source_platform}): {thumb[:90]}")
    else:
        _skip(reason, row.id)
        print(f"  [{row.id}] skip ({reason}): {row.title!r}")

print(f"\n{'Would resolve' if DRY_RUN else 'Resolving'} {len(resolved)} of {len(rows)} checked...")

if resolved and not DRY_RUN:
    with engine.begin() as conn:
        for print_id, thumb in resolved:
            conn.execute(
                text("UPDATE prints SET thumbnail_url = :thumb WHERE id = :id"),
                {"thumb": thumb, "id": print_id},
            )
    print("Done — thumbnail_url written for resolved rows only. No other fields touched.")
elif DRY_RUN:
    print("Dry run — no changes made. Re-run without --dry-run to apply.")

with engine.connect() as conn:
    still_missing = conn.execute(text(
        "SELECT COUNT(*) FROM prints WHERE thumbnail_url IS NULL OR thumbnail_url = ''"
    )).scalar()

print(f"\n{'=' * 60}\nSUMMARY\n{'=' * 60}")
print(f"  thumbnail-less before this run: {total_before}")
print(f"  checked this run:               {len(rows)}")
print(f"  resolved:                       {len(resolved)}")
print(f"  thumbnail-less after this run:  {still_missing}")
print("\n  Skip reasons:")
for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
    print(f"    {count:4d}  {reason}  (e.g. ids {skip_examples[reason][:5]})")
