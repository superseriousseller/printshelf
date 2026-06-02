"""Internal cron endpoints — called by Railway's cron service, not by users.

All routes require X-Cron-Secret matching the CRON_SECRET env var.
Railway cron setup: new Cron service → schedule "0 10 * * *" (10am UTC daily) →
  command: curl -sf -X POST https://printshelf.app/internal/drip
           -H "X-Cron-Secret: $CRON_SECRET"
"""
import logging
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from email_service import send_day2_nudge, send_day7_reminder
from models import Print, User, get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["cron"])

_SECRET = os.environ.get("CRON_SECRET", "")


def _check_secret(x_cron_secret: str = Header(default="")):
    if not _SECRET or x_cron_secret != _SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/drip")
def run_drip(db: Session = Depends(get_db), _=Depends(_check_secret)):
    """Send Day-2 and Day-7 onboarding emails to users who haven't logged a print."""
    now = datetime.utcnow()
    day2_window = (now - timedelta(days=3), now - timedelta(days=2))
    day7_window = (now - timedelta(days=8), now - timedelta(days=7))

    # Users with zero prints (queued or printed — neither counts for engagement)
    users_no_prints = (
        db.query(User.id)
        .outerjoin(Print, Print.user_id == User.id)
        .filter(Print.id.is_(None))
        .subquery()
    )

    # Day-2 candidates: signed up 2–3 days ago, no prints, not yet sent
    day2_users = (
        db.query(User)
        .filter(
            User.id.in_(db.query(users_no_prints.c.id)),
            User.created_at >= day2_window[0],
            User.created_at < day2_window[1],
            User.drip_day2_sent == False,  # noqa: E712
        )
        .all()
    )

    # Day-7 candidates: signed up 7–8 days ago, no prints, not yet sent
    day7_users = (
        db.query(User)
        .filter(
            User.id.in_(db.query(users_no_prints.c.id)),
            User.created_at >= day7_window[0],
            User.created_at < day7_window[1],
            User.drip_day7_sent == False,  # noqa: E712
        )
        .all()
    )

    # Pull recent public prints for Day-7 social proof (shared across all day-7 sends)
    recent_rows = (
        db.query(Print, User.username)
        .join(User, Print.user_id == User.id)
        .filter(
            Print.is_public == True,  # noqa: E712
            Print.queued == False,    # noqa: E712
        )
        .order_by(Print.created_at.desc())
        .limit(10)
        .all()
    )
    recent_prints = [
        {"id": p.id, "title": p.title, "username": uname, "thumbnail": p.photo_url or p.thumbnail_url}
        for p, uname in recent_rows
        if p.photo_url or p.thumbnail_url
    ][:3]

    sent_day2 = sent_day7 = 0
    for user in day2_users:
        ok = send_day2_nudge(user.email, user.username)
        user.drip_day2_sent = True
        if ok:
            sent_day2 += 1
            logger.info("drip/day2 sent to user %s", user.id)

    for user in day7_users:
        ok = send_day7_reminder(user.email, user.username, recent_prints)
        user.drip_day7_sent = True
        if ok:
            sent_day7 += 1
            logger.info("drip/day7 sent to user %s", user.id)

    db.commit()
    logger.info("drip run complete: day2=%d day7=%d", sent_day2, sent_day7)
    return {"day2_sent": sent_day2, "day7_sent": sent_day7}
