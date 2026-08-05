"""One-time re-engagement campaign for verified, zero-print users.

Usage:
  DATABASE_URL=postgresql://... python backend/scripts/send_reengagement_campaign.py
  DATABASE_URL=postgresql://... python backend/scripts/send_reengagement_campaign.py --dry-run
  DATABASE_URL=postgresql://... python backend/scripts/send_reengagement_campaign.py --send --limit 25
  DATABASE_URL=postgresql://... python backend/scripts/send_reengagement_campaign.py --send --limit 2 --only-usernames alice,bob

Recipient criteria (ALL must hold):
  - zero prints (queued or printed — neither counts as activated; same
    definition cron.py's drip job already uses)
  - email_verified = true (confirmed a real inbox — cuts bounce/spam-trap risk)
  - email_opt_out = false
  - reengagement_sent_at IS NULL (never sent this campaign)

Safety:
  - Defaults to --dry-run whenever --send isn't explicitly passed. Dry run
    prints the recipient count + a sample of up to 10 and makes NO network
    calls and NO DB writes.
  - --send requires --limit N — there is no way to fire an unbounded send
    through this script.
  - --only-usernames a,b,c further restricts the candidate set — for testing
    against specific accounts without touching anyone else who happens to
    match the criteria.
  - reengagement_sent_at is only set on a CONFIRMED successful send (Resend
    accepted it) and committed immediately per user. A transient failure is
    safe to retry on the next run — it will NOT double-send anyone who
    already succeeded, and a crash mid-batch loses nothing already sent.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DRY_RUN = "--dry-run" in sys.argv
SEND = "--send" in sys.argv

LIMIT = None
for i, a in enumerate(sys.argv):
    if a == "--limit" and i + 1 < len(sys.argv):
        LIMIT = int(sys.argv[i + 1])

ONLY_USERNAMES = None
for i, a in enumerate(sys.argv):
    if a == "--only-usernames" and i + 1 < len(sys.argv):
        ONLY_USERNAMES = {u.strip() for u in sys.argv[i + 1].split(",") if u.strip()}

if SEND and DRY_RUN:
    sys.exit("--send and --dry-run are mutually exclusive")
if SEND and LIMIT is None:
    sys.exit("--send requires --limit N — a real send must always specify a batch size")
if not SEND:
    DRY_RUN = True

DATABASE_URL = os.environ.get("DATABASE_URL", "").replace("postgres://", "postgresql://", 1)
if not DATABASE_URL:
    sys.exit("DATABASE_URL not set")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

import models
from email_service import send_reengagement_campaign


def _first_name(user) -> str:
    if user.display_name and user.display_name.strip():
        return user.display_name.strip().split()[0]
    return user.username


db = SessionLocal()
try:
    query = (
        db.query(models.User)
        .outerjoin(models.Print, models.Print.user_id == models.User.id)
        .filter(
            models.Print.id.is_(None),
            models.User.email_verified == True,  # noqa: E712
            models.User.email_opt_out == False,  # noqa: E712
            models.User.reengagement_sent_at.is_(None),
        )
        .order_by(models.User.created_at.asc())
    )
    if ONLY_USERNAMES:
        query = query.filter(models.User.username.in_(ONLY_USERNAMES))

    candidates = query.all()
    total = len(candidates)
    print(f"Recipient candidates: {total}")

    if DRY_RUN:
        print("Sample (up to 10):")
        for u in candidates[:10]:
            print(f"  [{u.id}] {u.username} <{u.email}> first_name={_first_name(u)!r}")
        print("\nDry run — no emails sent, no DB changes. Re-run with --send --limit N to actually send.")
        sys.exit(0)

    batch = candidates[:LIMIT]
    print(f"Sending to {len(batch)} of {total} candidates (--limit {LIMIT})...")
    sent = failed = 0
    for u in batch:
        ok = send_reengagement_campaign(u.email, _first_name(u), u.unsubscribe_token)
        if ok:
            u.reengagement_sent_at = datetime.utcnow()
            db.commit()
            sent += 1
            print(f"  sent: [{u.id}] {u.username} <{u.email}>")
        else:
            failed += 1
            print(f"  FAILED (will retry next run): [{u.id}] {u.username} <{u.email}>")

    print(f"\nDone. sent={sent} failed={failed} (failed ones were NOT marked sent — safe to retry)")
finally:
    db.close()
