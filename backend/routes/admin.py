"""Admin console — /admin

Gated by ADMIN_USERNAME env var. Set it to your PrintShelf username on Railway.
No separate user model change needed — checked at request time.
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user_web_optional
from models import AffiliateClick, Filament, Follow, Print, Printer, User, get_db

router = APIRouter(tags=["admin"])

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_BACKEND_DIR, "templates"))


def _is_admin(user: Optional[User]) -> bool:
    admin_username = os.environ.get("ADMIN_USERNAME", "").strip()
    return bool(admin_username and user and user.username == admin_username)


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    if not _is_admin(current_user):
        # Authenticated but not admin → home. Unauthenticated → login.
        return RedirectResponse("/" if current_user else "/login", status_code=303)

    now = datetime.utcnow()
    ago_7d = now - timedelta(days=7)
    ago_30d = now - timedelta(days=30)

    # --- Platform totals ---
    total_users = db.query(func.count(User.id)).scalar()
    total_prints = db.query(func.count(Print.id)).filter(Print.queued == False).scalar()  # noqa: E712
    total_queued = db.query(func.count(Print.id)).filter(Print.queued == True).scalar()   # noqa: E712
    total_filaments = db.query(func.count(Filament.id)).scalar()
    total_printers = db.query(func.count(Printer.id)).scalar()
    total_follows = db.query(func.count(Follow.id)).scalar()

    # --- Tier split ---
    free_users = db.query(func.count(User.id)).filter(User.tier == "free").scalar()
    pro_users = db.query(func.count(User.id)).filter(User.tier == "pro").scalar()

    # --- Growth ---
    new_7d = db.query(func.count(User.id)).filter(User.created_at >= ago_7d).scalar()
    new_30d = db.query(func.count(User.id)).filter(User.created_at >= ago_30d).scalar()
    prints_7d = db.query(func.count(Print.id)).filter(
        Print.created_at >= ago_7d, Print.queued == False  # noqa: E712
    ).scalar()
    prints_30d = db.query(func.count(Print.id)).filter(
        Print.created_at >= ago_30d, Print.queued == False  # noqa: E712
    ).scalar()

    # --- Recent signups ---
    recent_users = (
        db.query(User)
        .order_by(User.created_at.desc())
        .limit(25)
        .all()
    )
    # print counts per user (for the table)
    user_print_counts = {
        uid: cnt
        for uid, cnt in db.query(Print.user_id, func.count(Print.id))
        .filter(Print.queued == False)  # noqa: E712
        .group_by(Print.user_id)
        .all()
    }

    # --- Top makers ---
    top_makers = (
        db.query(User, func.count(Print.id).label("print_count"))
        .join(Print, Print.user_id == User.id)
        .filter(Print.queued == False)  # noqa: E712
        .group_by(User.id)
        .order_by(func.count(Print.id).desc())
        .limit(10)
        .all()
    )

    # --- Affiliate clicks ---
    clicks_total = db.query(func.count(AffiliateClick.id)).scalar()
    clicks_30d = db.query(func.count(AffiliateClick.id)).filter(
        AffiliateClick.clicked_at >= ago_30d
    ).scalar()
    clicks_by_store = (
        db.query(AffiliateClick.store, func.count(AffiliateClick.id).label("cnt"))
        .group_by(AffiliateClick.store)
        .order_by(func.count(AffiliateClick.id).desc())
        .all()
    )
    recent_clicks = (
        db.query(AffiliateClick, User.username)
        .outerjoin(User, AffiliateClick.user_id == User.id)
        .order_by(AffiliateClick.clicked_at.desc())
        .limit(20)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "current_user": current_user,
            "now": now,
            # totals
            "total_users": total_users,
            "total_prints": total_prints,
            "total_queued": total_queued,
            "total_filaments": total_filaments,
            "total_printers": total_printers,
            "total_follows": total_follows,
            # tier
            "free_users": free_users,
            "pro_users": pro_users,
            # growth
            "new_7d": new_7d,
            "new_30d": new_30d,
            "prints_7d": prints_7d,
            "prints_30d": prints_30d,
            # tables
            "recent_users": recent_users,
            "user_print_counts": user_print_counts,
            "top_makers": top_makers,
            # affiliate
            "clicks_total": clicks_total,
            "clicks_30d": clicks_30d,
            "clicks_by_store": clicks_by_store,
            "recent_clicks": recent_clicks,
        },
    )
