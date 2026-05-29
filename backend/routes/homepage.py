"""Public homepage at /.

Server-rendered marketing page with a real visual hook: a gallery of
the most recent public prints across all users. Empty at fresh-launch;
fills out as people sign up and log prints.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import get_current_user_web_optional
from sqlalchemy import or_

from models import Print, User, get_db

router = APIRouter(tags=["homepage"])

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_BACKEND_DIR, "templates"))

FEATURED_LIMIT = 6


@router.get("/", response_class=HTMLResponse)
def homepage(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    # Pull the most recent public, non-queued prints with photos.
    # Joined so we can render the maker's username under each card.
    rows = (
        db.query(Print, User.username, User.display_name)
        .join(User, Print.user_id == User.id)
        .filter(
            Print.is_public == True,  # noqa: E712
            Print.queued == False,    # noqa: E712
        )
        .order_by(Print.created_at.desc())
        .limit(FEATURED_LIMIT)
        .all()
    )
    featured = [
        {
            "title": p.title,
            "designer": p.designer,
            "thumbnail": p.photo_url or p.thumbnail_url,
            "rating": p.rating,
            "username": uname,
            "maker": display_name or uname,
            "status": p.status,
        }
        for p, uname, display_name in rows
        if p.photo_url or p.thumbnail_url  # require an image — visual hook only
    ]

    return templates.TemplateResponse(
        request,
        "homepage.html",
        {
            "current_user": current_user,
            "featured": featured,
        },
    )


@router.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    query = (q or "").strip()
    users, prints, users_by_id = [], [], {}

    if query:
        pattern = f"%{query}%"
        users = (
            db.query(User)
            .filter(or_(User.username.ilike(pattern), User.display_name.ilike(pattern)))
            .order_by(User.username)
            .limit(10)
            .all()
        )
        print_rows = (
            db.query(Print, User.username)
            .join(User, Print.user_id == User.id)
            .filter(
                Print.is_public == True,   # noqa: E712
                Print.queued == False,     # noqa: E712
                or_(Print.title.ilike(pattern), Print.designer.ilike(pattern)),
            )
            .order_by(Print.created_at.desc())
            .limit(24)
            .all()
        )
        prints = [{"print": p, "username": uname} for p, uname in print_rows]

    return templates.TemplateResponse(
        request,
        "search.html",
        {"current_user": current_user, "q": query, "users": users, "prints": prints},
    )


@router.get("/privacy", response_class=HTMLResponse)
def privacy_policy(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    """Privacy policy page. Linked from the Chrome Web Store listing and
    from the extension's options page. Kept terse and accurate — the
    Council flagged that an over-researched GDPR/CCPA draft is a rabbit
    hole for a solo product at this stage."""
    return templates.TemplateResponse(
        request, "privacy.html", {"current_user": current_user},
    )
