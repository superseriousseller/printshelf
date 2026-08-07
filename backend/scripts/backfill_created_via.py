"""Best-effort backfill of `created_via` for rows that predate source tracking.

HEURISTIC — not authoritative. New rows are tagged accurately at create time;
this only refines historical rows still sitting at 'unknown'. It never touches a
row that already has a real value, so it's safe to re-run.

Rules (conservative):
  Filaments (unknown):
    - has a source_url  -> 'extension'  (one-click store-page save is the
      extension's signature; a rare web URL-paste import is possible but minor)
    - no source_url     -> 'web'
  Prints (unknown):
    - source_platform in slicer set                 -> 'slicer'
    - source_platform != 'manual' (makerworld/etc)  -> 'extension'
    - source_platform == 'manual'                   -> 'web'

Usage (from backend/):
    DATABASE_URL=... python scripts/backfill_created_via.py            # dry-run
    DATABASE_URL=... python scripts/backfill_created_via.py --apply    # write
"""
import sys
from collections import Counter

sys.path.insert(0, ".")
from models import SessionLocal, Filament, Print  # noqa: E402

_SLICER = {"slicer", "bambustudio", "orcaslicer", "prusaslicer"}


def _filament_guess(f: Filament) -> str:
    return "extension" if (f.source_url or "").strip() else "web"


def _print_guess(p: Print) -> str:
    sp = (p.source_platform or "manual").strip().lower()
    if sp in _SLICER:
        return "slicer"
    if sp != "manual":
        return "extension"
    return "web"


def main(apply: bool) -> None:
    db = SessionLocal()
    fil = db.query(Filament).filter(Filament.created_via == "unknown").all()
    pr = db.query(Print).filter(Print.created_via == "unknown").all()
    fc, pc = Counter(), Counter()
    for f in fil:
        g = _filament_guess(f); fc[g] += 1
        if apply:
            f.created_via = g
    for p in pr:
        g = _print_guess(p); pc[g] += 1
        if apply:
            p.created_via = g
    if apply:
        db.commit()
    db.close()
    mode = "APPLIED" if apply else "DRY-RUN (no changes written)"
    print(f"== created_via backfill — {mode} ==")
    print(f"Filaments still 'unknown': {len(fil)} -> {dict(fc)}")
    print(f"Prints still 'unknown':    {len(pr)} -> {dict(pc)}")
    if not apply:
        print("Re-run with --apply to write these.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
