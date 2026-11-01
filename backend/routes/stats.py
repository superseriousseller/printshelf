"""External growth-stats endpoint — pulled by other projects (Cam's growth
dashboard) to track PrintShelf alongside his other properties. Matches SS
Book Tracker's GET /api/metrics shape/auth exactly (X-Stats-Key header,
STATS_API_KEY env var, HMAC constant-time compare) so one dashboard can
poll every app the same way. No PII — counts and dates only.
"""
import hmac
import os
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

import rate_limiter
from models import AffiliateClick, Print, User, get_db

router = APIRouter(tags=["stats"])

_STATS_KEY = os.environ.get("STATS_API_KEY", "")


def _check_stats_key(request: Request, x_stats_key: str = Header(default="")):
    # Rate-limit check runs before the key check so brute-force attempts
    # against the key still get throttled (mirrors SS Book Tracker's
    # /api/metrics — see that project's main.py for the same ordering).
    if not rate_limiter.check(rate_limiter.client_ip(request), "stats_api", max_attempts=60, window_secs=60):
        raise HTTPException(status_code=429, detail="Too many requests")
    if not _STATS_KEY or not hmac.compare_digest(x_stats_key, _STATS_KEY):
        raise HTTPException(status_code=403, detail="Forbidden")


def _compute_stats(db: Session, now: datetime) -> dict:
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    total_users = db.query(func.count(User.id)).scalar()
    new_this_week = db.query(func.count(User.id)).filter(User.created_at >= week_ago).scalar()
    new_this_month = db.query(func.count(User.id)).filter(User.created_at >= month_ago).scalar()
    verified_users = db.query(func.count(User.id)).filter(User.email_verified == True).scalar()  # noqa: E712
    paid_users = db.query(func.count(User.id)).filter(User.tier == "pro").scalar()

    active_this_week = (
        db.query(func.count(func.distinct(Print.user_id)))
        .filter(Print.created_at >= week_ago)
        .scalar()
    )
    prints_logged_this_week = db.query(func.count(Print.id)).filter(Print.created_at >= week_ago).scalar()
    # "Activated" = logged at least one print, ever (queued or printed — the
    # same bar used elsewhere in this project's own growth notes).
    activated_users = db.query(func.count(func.distinct(Print.user_id))).scalar()

    # Grouped in Python, not via a DB-side date-trunc function — same
    # portability call as the trending-sort query elsewhere in this app
    # (Postgres/SQLite date functions aren't guaranteed to agree).
    recent_signups = db.query(User.created_at).filter(User.created_at >= month_ago).all()
    per_day = defaultdict(int)
    for (created_at,) in recent_signups:
        per_day[created_at.date().isoformat()] += 1
    signups_per_day = [{"date": d, "count": c} for d, c in sorted(per_day.items())]

    # --- Affiliate clicks (monetized-link taps through the /buy redirector) ---
    # Real counts from the affiliate_clicks table. last7 vs prev7 give a trend;
    # byStore7d + a 14-day daily series feed the growth dashboard's detail view.
    two_week_ago = now - timedelta(days=14)
    clicks_total = db.query(func.count(AffiliateClick.id)).scalar() or 0
    clicks_7d = db.query(func.count(AffiliateClick.id)).filter(
        AffiliateClick.clicked_at >= week_ago
    ).scalar() or 0
    clicks_prev7 = db.query(func.count(AffiliateClick.id)).filter(
        AffiliateClick.clicked_at >= two_week_ago,
        AffiliateClick.clicked_at < week_ago,
    ).scalar() or 0
    clicks_30d = db.query(func.count(AffiliateClick.id)).filter(
        AffiliateClick.clicked_at >= month_ago
    ).scalar() or 0
    by_store_7d = (
        db.query(AffiliateClick.store, func.count(AffiliateClick.id).label("cnt"))
        .filter(AffiliateClick.clicked_at >= week_ago)
        .group_by(AffiliateClick.store)
        .order_by(func.count(AffiliateClick.id).desc())
        .all()
    )
    clicks_by_store_7d = [
        {"store": (s or "other"), "count": c} for s, c in by_store_7d
    ]
    # 14-day daily series (grouped in Python for Postgres/SQLite portability,
    # same call as signups_per_day above).
    recent_clicks = db.query(AffiliateClick.clicked_at).filter(
        AffiliateClick.clicked_at >= two_week_ago
    ).all()
    clicks_per_day_map = defaultdict(int)
    for (clicked_at,) in recent_clicks:
        clicks_per_day_map[clicked_at.date().isoformat()] += 1
    clicks_per_day = [
        {"date": d, "count": c} for d, c in sorted(clicks_per_day_map.items())
    ]

    return {
        "totalUsers": total_users,
        "newUsersThisWeek": new_this_week,
        "newUsersThisMonth": new_this_month,
        "activeUsersThisWeek": active_this_week,
        "printsLoggedThisWeek": prints_logged_this_week,
        "activatedUsers": activated_users,
        "verifiedUsers": verified_users,
        "paidUsers": paid_users,
        "usersByTier": {"free": total_users - paid_users, "pro": paid_users},
        "signupsPerDay": signups_per_day,
        "affiliateClicks": {
            "last7": clicks_7d,
            "prev7": clicks_prev7,
            "last30": clicks_30d,
            "total": clicks_total,
            "byStore7d": clicks_by_store_7d,
            "perDay": clicks_per_day,
        },
    }


@router.get("/api/metrics")
def get_metrics(db: Session = Depends(get_db), _=Depends(_check_stats_key)):
    return _compute_stats(db, datetime.utcnow())
