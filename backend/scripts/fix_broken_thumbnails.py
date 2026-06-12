"""One-shot script: nulls out photo_url on prints where the stored URL returns a CDN error.

Usage:
    DATABASE_URL=postgresql://... python backend/scripts/fix_broken_thumbnails.py [--dry-run]
"""
import os
import sys
import httpx
from sqlalchemy import create_engine, text

DRY_RUN = "--dry-run" in sys.argv
DATABASE_URL = os.environ.get("DATABASE_URL", "").replace("postgres://", "postgresql://", 1)
if not DATABASE_URL:
    sys.exit("DATABASE_URL not set")

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    rows = conn.execute(
        text("SELECT id, title, photo_url FROM prints WHERE photo_url LIKE 'https://makerworld.%'")
    ).fetchall()

print(f"Checking {len(rows)} Makerworld-hosted thumbnails...")
to_fix = []
with httpx.Client(timeout=8.0) as c:
    for row in rows:
        try:
            resp = c.head(row.photo_url)
            status = resp.status_code
        except Exception as e:
            status = f"err:{e}"
        if isinstance(status, int) and status >= 400:
            print(f"  BROKEN ({status}): [{row.id}] {row.title}")
            to_fix.append(row.id)
        else:
            print(f"  ok     ({status}): [{row.id}] {row.title}")

if not to_fix:
    print("Nothing to fix.")
    sys.exit(0)

print(f"\n{'Would fix' if DRY_RUN else 'Fixing'} {len(to_fix)} print(s)...")
if not DRY_RUN:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE prints SET photo_url = NULL WHERE id = ANY(:ids)"),
            {"ids": to_fix},
        )
    print("Done — photo_url cleared. Re-upload photos from each print's edit page.")
else:
    print("Dry run — no changes made. Re-run without --dry-run to apply.")
