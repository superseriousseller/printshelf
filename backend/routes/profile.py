"""Server-rendered public profile pages.

The viral surface — /u/{username} renders a print wall that's SEO-indexable
and shareable. No auth required; only `is_public=True` prints are shown.
"""
import os
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import get_current_user_web_optional
from models import Filament, Print, Printer, User, get_db

router = APIRouter(tags=["profile"])

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_BACKEND_DIR, "templates"))


def _stats_for(db: Session, user: User) -> dict:
    """Aggregate over the user's PUBLIC prints only — same scope as what's rendered."""
    q = db.query(Print).filter(Print.user_id == user.id, Print.is_public == True, Print.queued == False)  # noqa: E712
    total = q.count()
    if total == 0:
        return {"total": 0, "success_pct": 0, "favorite_material": None}

    success = q.filter(Print.status == "printed").count()
    success_pct = round((success / total) * 100)

    # Favorite material = most-referenced filament material across this user's public prints
    favorite_material = None
    rows = q.all()
    if rows:
        from models import Filament  # local to avoid import-time issues
        fil_ids = [fid for p in rows for fid in (p.filament_ids or [])]
        if fil_ids:
            counter = Counter(fil_ids)
            ranked_ids = [fid for fid, _ in counter.most_common()]
            mats = db.query(Filament.material).filter(Filament.id.in_(ranked_ids)).all()
            mat_counts = Counter(m for (m,) in mats)
            if mat_counts:
                favorite_material = mat_counts.most_common(1)[0][0]

    return {"total": total, "success_pct": success_pct, "favorite_material": favorite_material}


@router.get("/u/{username}", response_class=HTMLResponse)
def public_profile(
    request: Request,
    username: str,
    db: Session = Depends(get_db),
    material: Optional[str] = None,
    status: Optional[str] = None,
    rating: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        return templates.TemplateResponse(
            request,
            "404_user.html",
            {"username": username, "current_user": current_user},
            status_code=404,
        )

    q = db.query(Print).filter(
        Print.user_id == user.id,
        Print.is_public == True,  # noqa: E712
        Print.queued == False,    # noqa: E712
    )
    if status in {"printed", "failed", "partial"}:
        q = q.filter(Print.status == status)
    if rating is not None:
        try:
            r = int(rating)
            if 1 <= r <= 5:
                q = q.filter(Print.rating >= r)
        except (TypeError, ValueError):
            pass

    rows = q.order_by(Print.created_at.desc()).limit(200).all()

    # Filter by material AFTER pulling — material lives on Filament, joined via Print.filament_ids JSON
    materials_present = set()
    if rows:
        from models import Filament
        fil_ids = {fid for p in rows for fid in (p.filament_ids or [])}
        if fil_ids:
            for fid, mat in db.query(Filament.id, Filament.material).filter(Filament.id.in_(fil_ids)).all():
                materials_present.add(mat)
        if material:
            keep = []
            mat_by_id = {}
            if fil_ids:
                for fid, mat in db.query(Filament.id, Filament.material).filter(Filament.id.in_(fil_ids)).all():
                    mat_by_id[fid] = mat
            for p in rows:
                if any(mat_by_id.get(fid) == material for fid in (p.filament_ids or [])):
                    keep.append(p)
            rows = keep

    first_photo = None
    for p in rows:
        if p.photo_url or p.thumbnail_url:
            first_photo = p.photo_url or p.thumbnail_url
            break

    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "user": user,
            "prints": rows,
            "stats": _stats_for(db, user),
            "materials_present": sorted(materials_present),
            "active": {"material": material, "status": status, "rating": str(rating) if rating else None},
            "first_photo": first_photo,
            "app_url": os.environ.get("APP_URL", "https://printshelf.app"),
            "current_user": current_user,
        },
    )


@router.get("/u/{username}/prints/{print_id}", response_class=HTMLResponse)
def public_print_detail(
    request: Request,
    username: str,
    print_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        return templates.TemplateResponse(
            request, "404_user.html",
            {"username": username, "current_user": current_user},
            status_code=404,
        )
    p = db.query(Print).filter(
        Print.id == print_id,
        Print.user_id == user.id,
        Print.is_public == True,   # noqa: E712
        Print.queued == False,     # noqa: E712
    ).first()
    if p is None:
        return RedirectResponse(f"/u/{username}", status_code=303)

    filaments = []
    if p.filament_ids:
        filaments = db.query(Filament).filter(
            Filament.id.in_(p.filament_ids), Filament.user_id == user.id
        ).all()

    printer = None
    if p.printer_id:
        printer = db.query(Printer).filter(
            Printer.id == p.printer_id, Printer.user_id == user.id
        ).first()

    return templates.TemplateResponse(
        request,
        "print_detail.html",
        {
            "user": user,
            "print_": p,
            "filaments": filaments,
            "printer": printer,
            "current_user": current_user,
            "app_url": os.environ.get("APP_URL", "https://printshelf.app"),
        },
    )
