"""Server-rendered public profile pages.

The viral surface — /@{username} renders a print wall that's SEO-indexable
and shareable. No auth required; only `is_public=True` prints are shown.
Legacy /u/{username} routes 301-redirect to the new canonical URLs.
"""
import os
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from limits import enforce_print_limit
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from affiliate import apply_affiliate, filament_buy_url
from auth import filament_preview_enabled, get_current_user_web_optional, instruments_index_enabled
from email_service import send_follow_notification
from import_service import platform_display_name
from models import Collection, CollectionPrint, Filament, Follow, Like, Print, PrintLink, Printer, User, get_db, PRINT_CATEGORY_LABELS
from sqlalchemy import func

router = APIRouter(tags=["profile"])

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_BACKEND_DIR, "templates"))
# base.html topbar has a gated "Preview" link → this instance renders public profile pages.
templates.env.globals["filament_preview_enabled"] = filament_preview_enabled
templates.env.globals["source_display_name"] = platform_display_name
templates.env.globals["instruments_index_enabled"] = instruments_index_enabled


def _calc_print_cost(filament_used_g: float, filaments: list) -> float | None:
    """Return estimated material cost in USD, or None if data is insufficient."""
    if not filament_used_g or not filaments:
        return None
    priced = [f for f in filaments if f.price_at_save and f.spool_weight_g]
    if not priced:
        return None
    cost_per_g = sum(f.price_at_save / f.spool_weight_g for f in priced) / len(priced)
    return round(filament_used_g * cost_per_g, 2)


def _stats_for(db: Session, user: User) -> dict:
    """Aggregate over the user's PUBLIC prints only — same scope as what's rendered."""
    from sqlalchemy import func
    q = db.query(Print).filter(Print.user_id == user.id, Print.is_public == True, Print.queued == False)  # noqa: E712
    total = q.count()
    if total == 0:
        return {"total": 0, "success_pct": 0, "favorite_material": None, "filament_used_g": None, "print_time_mins": None}

    success = q.filter(Print.status == "printed").count()
    success_pct = round((success / total) * 100)

    agg = db.query(
        func.sum(Print.filament_used_g),
        func.sum(Print.print_time_mins),
    ).filter(Print.user_id == user.id, Print.is_public == True, Print.queued == False).one()  # noqa: E712
    filament_used_g = round(agg[0]) if agg[0] else None
    print_time_mins = int(agg[1]) if agg[1] else None

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

    return {
        "total": total,
        "success_pct": success_pct,
        "favorite_material": favorite_material,
        "filament_used_g": filament_used_g,
        "print_time_mins": print_time_mins,
    }


def _collection_cards(db: Session, owner_id: int, visible_only: bool) -> list:
    """[{collection, count, cover}] for a user's non-empty collections.

    visible_only=True (a visitor) counts/covers only public, non-queued prints and
    drops collections with nothing visible; the owner sees all their collections.
    """
    cols = db.query(Collection).filter(Collection.user_id == owner_id).order_by(Collection.created_at.desc()).all()
    cards = []
    for c in cols:
        pids = [r.print_id for r in db.query(CollectionPrint.print_id).filter(CollectionPrint.collection_id == c.id).all()]
        cover, count = None, 0
        if pids:
            q = db.query(Print).filter(Print.id.in_(pids), Print.user_id == owner_id)
            if visible_only:
                q = q.filter(Print.is_public == True, Print.queued == False)  # noqa: E712
            members = q.order_by(Print.created_at.desc()).all()
            count = len(members)
            for p in members:
                img = p.photo_url or p.thumbnail_url
                if img:
                    cover = {"img": img, "fx": p.focal_x or 50, "fy": p.focal_y or 50}
                    break
        if count == 0:
            continue
        cards.append({"c": c, "count": count, "cover": cover})
    return cards


@router.get("/u/{username}")
def legacy_profile_redirect(username: str):
    return RedirectResponse(url=f"/@{username}", status_code=301)


@router.get("/u/{username}/prints/{print_id}")
def legacy_print_detail_redirect(username: str, print_id: int):
    return RedirectResponse(url=f"/@{username}/prints/{print_id}", status_code=301)


@router.get("/@{username}", response_class=HTMLResponse)
def public_profile(
    request: Request,
    username: str,
    db: Session = Depends(get_db),
    material: Optional[str] = None,
    status: Optional[str] = None,
    rating: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    user = db.query(User).filter(func.lower(User.username) == username.lower()).first()
    if user is None:
        return templates.TemplateResponse(
            request,
            "404_user.html",
            {"username": username, "current_user": current_user},
            status_code=404,
        )
    if user.username != username:
        return RedirectResponse(url=f"/@{user.username}", status_code=301)

    # Count the visit — skip if the owner is viewing their own shelf
    if current_user is None or current_user.id != user.id:
        db.query(User).filter(User.id == user.id).update(
            {"profile_views": User.profile_views + 1}
        )
        db.commit()

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

    rows = q.order_by(Print.print_date.desc().nullslast(), Print.created_at.desc()).limit(200).all()

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

    all_fil_ids = {fid for p in rows for fid in (p.filament_ids or [])}
    fil_meta = {}
    if all_fil_ids:
        for f in db.query(Filament).filter(Filament.id.in_(all_fil_ids), Filament.user_id == user.id).all():
            fil_meta[f.id] = f

    printers = db.query(Printer).filter(Printer.user_id == user.id).order_by(Printer.created_at).all()

    # Public collections with a cover + visible count (only show ones a visitor can
    # actually see — i.e. with ≥1 public, non-queued print, unless the owner is viewing).
    viewer_is_owner = current_user is not None and current_user.id == user.id
    collections = _collection_cards(db, user.id, visible_only=not viewer_is_owner)

    follower_count = db.query(Follow).filter(Follow.following_id == user.id).count()
    following_count = db.query(Follow).filter(Follow.follower_id == user.id).count()
    is_following = (
        current_user is not None
        and current_user.id != user.id
        and db.query(Follow).filter(
            Follow.follower_id == current_user.id, Follow.following_id == user.id
        ).first() is not None
    )

    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "user": user,
            "prints": rows,
            "fil_meta": fil_meta,
            "printers": printers,
            "stats": _stats_for(db, user),
            "materials_present": sorted(materials_present),
            "active": {"material": material, "status": status, "rating": str(rating) if rating else None},
            "first_photo": first_photo,
            "app_url": os.environ.get("APP_URL", "https://printshelf.app"),
            "current_user": current_user,
            "follower_count": follower_count,
            "following_count": following_count,
            "is_following": is_following,
            "collections": collections,
            "profile_views": user.profile_views if (current_user and current_user.id == user.id) else None,
        },
    )


@router.get("/@{username}/prints/{print_ref}", response_class=HTMLResponse)
def public_print_detail(
    request: Request,
    username: str,
    print_ref: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    # URL is `{id}-{slug}` (slug decorative); old `{id}` links still resolve.
    try:
        print_id = int(print_ref.split("-", 1)[0])
    except (ValueError, AttributeError):
        return RedirectResponse(f"/@{username}", status_code=303)

    user = db.query(User).filter(func.lower(User.username) == username.lower()).first()
    if user is None:
        return templates.TemplateResponse(
            request, "404_user.html",
            {"username": username, "current_user": current_user},
            status_code=404,
        )
    if user.username != username:
        return RedirectResponse(url=f"/@{user.username}/prints/{print_ref}", status_code=301)
    p = db.query(Print).filter(
        Print.id == print_id,
        Print.user_id == user.id,
        Print.is_public == True,   # noqa: E712
        Print.queued == False,     # noqa: E712
    ).first()
    if p is None:
        return RedirectResponse(f"/@{username}", status_code=303)

    # Canonicalize: bare ID or stale slug → 301 to the current `{id}-{slug}`.
    if print_ref != p.url_id:
        return RedirectResponse(url=f"/@{user.username}/prints/{p.url_id}", status_code=301)

    # Count the view — skip if the owner is viewing their own print.
    is_owner = current_user is not None and current_user.id == user.id
    if not is_owner:
        db.query(Print).filter(Print.id == p.id).update(
            {"view_count": Print.view_count + 1}
        )
        db.commit()
        p.view_count = (p.view_count or 0) + 1

    # Has the current (non-owner) viewer liked this print?
    liked = False
    if current_user is not None and not is_owner:
        liked = db.query(Like).filter(
            Like.user_id == current_user.id, Like.print_id == p.id
        ).first() is not None

    # Owner-only: the user's collections, flagged with which contain this print.
    owner_collections = []
    if is_owner:
        in_ids = {r.collection_id for r in db.query(CollectionPrint.collection_id).filter(CollectionPrint.print_id == p.id).all()}
        owner_collections = [
            {"id": c.id, "name": c.name, "checked": c.id in in_ids}
            for c in db.query(Collection).filter(Collection.user_id == user.id).order_by(Collection.created_at.desc()).all()
        ]

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

    # --- Related prints by filament (same brand + material, other users) ---
    related_by_filament = []
    filament_label = None
    for fil in filaments:
        if not (fil.brand and fil.material):
            continue
        other_fil_ids = {
            r.id for r in db.query(Filament.id).filter(
                Filament.brand == fil.brand,
                Filament.material == fil.material,
                Filament.user_id != user.id,
            ).all()
        }
        if not other_fil_ids:
            continue
        candidates = db.query(Print).filter(
            Print.is_public == True,   # noqa: E712
            Print.queued == False,     # noqa: E712
            Print.user_id != user.id,
        ).order_by(Print.created_at.desc()).limit(300).all()
        related_by_filament = [
            c for c in candidates
            if any(fid in other_fil_ids for fid in (c.filament_ids or []))
        ][:6]
        if related_by_filament:
            filament_label = f"{fil.brand} {fil.material}"
            break

    # --- Related prints by printer (same brand + model, other users) ---
    related_by_printer = []
    printer_label = None
    if printer and printer.brand and printer.model:
        other_printer_ids = [
            r.id for r in db.query(Printer.id).filter(
                Printer.brand == printer.brand,
                Printer.model == printer.model,
                Printer.user_id != user.id,
            ).all()
        ]
        if other_printer_ids:
            related_by_printer = db.query(Print).filter(
                Print.printer_id.in_(other_printer_ids),
                Print.is_public == True,   # noqa: E712
                Print.queued == False,     # noqa: E712
            ).order_by(Print.created_at.desc()).limit(6).all()
            printer_label = f"{printer.brand} {printer.model}"

    # Username lookup for related print cards
    related_user_ids = {rp.user_id for rp in related_by_filament + related_by_printer}
    users_by_id = {}
    if related_user_ids:
        users_by_id = {
            u.id: u for u in db.query(User).filter(User.id.in_(related_user_ids)).all()
        }

    print_cost = _calc_print_cost(p.filament_used_g, filaments)

    filaments_ctx = []
    for f in filaments:
        price_per_kg = round(f.price_at_save / f.spool_weight_g * 1000, 2) if (f.price_at_save and f.spool_weight_g) else None
        # Buy chip routes through the tracked redirector, not the raw affiliate
        # URL — the print-detail page is the highest-traffic Buy surface, so an
        # untracked <a href> here was the reason /admin saw near-zero clicks.
        has_buy = filament_buy_url(
            brand=f.brand, material=f.material, color=f.color_name or "",
            finish=f.finish or "", source_url=f.source_url or "",
        ) is not None
        buy_url = f"/@{user.username}/prints/{p.url_id}/buy?fid={f.id}" if has_buy else None
        filaments_ctx.append({"f": f, "price_per_kg": price_per_kg, "buy_url": buy_url})

    raw_links = db.query(PrintLink).filter(PrintLink.print_id == p.id).order_by(PrintLink.sort_order).all()
    links_ctx = [
        {"label": lk.label, "url": f"/@{user.username}/prints/{p.url_id}/goto?lid={lk.id}"}
        for lk in raw_links
    ]

    return templates.TemplateResponse(
        request,
        "print_detail.html",
        {
            "user": user,
            "print_": p,
            "category_label": PRINT_CATEGORY_LABELS.get(p.category),
            "filaments": filaments,
            "filaments_ctx": filaments_ctx,
            "links_ctx": links_ctx,
            "printer": printer,
            "print_cost": print_cost,
            "related_by_filament": related_by_filament,
            "filament_label": filament_label,
            "related_by_printer": related_by_printer,
            "printer_label": printer_label,
            "users_by_id": users_by_id,
            "current_user": current_user,
            "is_owner": is_owner,
            "liked": liked,
            "owner_collections": owner_collections,
            "app_url": os.environ.get("APP_URL", "https://printshelf.app"),
        },
    )


def _detail_print_or_none(db: Session, username: str, print_ref: str) -> Optional[Print]:
    """Resolve the public, non-queued print a detail-page redirector is acting
    on. Same visibility rule as public_print_detail — only reachable there."""
    try:
        print_id = int(print_ref.split("-", 1)[0])
    except (ValueError, AttributeError):
        return None
    return (
        db.query(Print)
        .join(User, Print.user_id == User.id)
        .filter(
            Print.id == print_id,
            func.lower(User.username) == username.lower(),
            Print.is_public == True,   # noqa: E712
            Print.queued == False,     # noqa: E712
        )
        .first()
    )


@router.get("/@{username}/prints/{print_ref}/buy")
def print_detail_buy(
    username: str,
    print_ref: str,
    fid: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    """Tracked Buy redirect for the filament chip on a print's public detail
    page — the highest-traffic Buy surface, previously untracked."""
    from filament_import_service import detect_store
    from models import AffiliateClick

    fallback = RedirectResponse(f"/@{username}/prints/{print_ref}", status_code=303)
    p = _detail_print_or_none(db, username, print_ref)
    if p is None or fid not in (p.filament_ids or []):
        return fallback
    f = db.query(Filament).filter(Filament.id == fid).first()
    if f is None:
        return fallback
    target = filament_buy_url(
        brand=f.brand, material=f.material, color=f.color_name or "",
        finish=f.finish or "", source_url=f.source_url or "",
    )
    if not target:
        return fallback
    store = detect_store(target)
    db.add(AffiliateClick(
        user_id=(current_user.id if current_user else None),
        filament_id=f.id, store=store or None, surface="print_detail_filament",
    ))
    db.commit()
    return RedirectResponse(target, status_code=302)


@router.get("/@{username}/prints/{print_ref}/goto")
def print_detail_link_goto(
    username: str,
    print_ref: str,
    lid: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    """Tracked redirect for a print's 'Goes great with' link chip — previously
    linked straight to the affiliate URL with no click logged."""
    from filament_import_service import detect_store
    from models import AffiliateClick

    fallback = RedirectResponse(f"/@{username}/prints/{print_ref}", status_code=303)
    p = _detail_print_or_none(db, username, print_ref)
    if p is None:
        return fallback
    lk = db.query(PrintLink).filter(PrintLink.id == lid, PrintLink.print_id == p.id).first()
    if lk is None:
        return fallback
    target = apply_affiliate(lk.url)
    store = detect_store(target)
    db.add(AffiliateClick(
        user_id=(current_user.id if current_user else None),
        filament_id=None, store=store or None, surface="print_detail_link",
    ))
    db.commit()
    return RedirectResponse(target, status_code=302)


@router.post("/@{username}/follow")
def follow_user(
    username: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    if current_user is None:
        return RedirectResponse("/login", status_code=303)
    target = db.query(User).filter(func.lower(User.username) == username.lower()).first()
    if target and target.id != current_user.id:
        exists = db.query(Follow).filter(
            Follow.follower_id == current_user.id, Follow.following_id == target.id
        ).first()
        if not exists:
            db.add(Follow(follower_id=current_user.id, following_id=target.id))
            db.commit()
            if target.notify_follow and target.email and target.unsubscribe_token:
                send_follow_notification(
                    target.email,
                    current_user.username,
                    current_user.display_name or current_user.username,
                    target.unsubscribe_token,
                )
    return RedirectResponse(url=f"/@{username}", status_code=303)


@router.post("/@{username}/unfollow")
def unfollow_user(
    username: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    if current_user is None:
        return RedirectResponse("/login", status_code=303)
    target = db.query(User).filter(func.lower(User.username) == username.lower()).first()
    if target:
        db.query(Follow).filter(
            Follow.follower_id == current_user.id, Follow.following_id == target.id
        ).delete()
        db.commit()
    return RedirectResponse(url=f"/@{username}", status_code=303)


@router.post("/@{username}/prints/{print_id}/queue")
def queue_print(
    username: str,
    print_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    """Add someone else's print to the current user's queue."""
    if current_user is None:
        return RedirectResponse(f"/login?next=/@{username}/prints/{print_id}", status_code=303)

    source = db.query(Print).filter(
        Print.id == print_id,
        Print.user_id == db.query(User.id).filter(func.lower(User.username) == username.lower()).scalar_subquery(),
        Print.is_public == True,   # noqa: E712
        Print.queued == False,     # noqa: E712
    ).first()
    if source is None:
        return RedirectResponse(f"/@{username}/prints/{print_id}", status_code=303)

    # Don't queue your own print
    if source.user_id == current_user.id:
        return RedirectResponse(f"/@{username}/prints/{print_id}", status_code=303)

    # Free-tier cap check
    from fastapi import HTTPException
    try:
        enforce_print_limit(db, current_user)
    except HTTPException:
        return RedirectResponse("/dashboard/prints?queued=true&cap=1", status_code=303)

    queued = Print(
        user_id=current_user.id,
        title=source.title,
        designer=source.designer,
        source_platform=source.source_platform,
        source_url=source.source_url,
        thumbnail_url=source.thumbnail_url,
        status="queued",
        queued=True,
        is_public=False,
    )
    db.add(queued)
    db.commit()
    return RedirectResponse("/dashboard/prints?queued=true", status_code=303)


@router.post("/@{username}/prints/{print_id}/rate")
def rate_print(
    username: str,
    print_id: int,
    request: Request,
    rating: int = Form(...),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    """Owner sets/clears the star rating from the public detail page.

    Session-cookie auth (the API PATCH is Bearer-only). rating 1-5 sets it;
    0 clears it. JS posts here via fetch (gets a 204); no-JS falls back to a
    full redirect back to the detail page.
    """
    detail_url = f"/@{username}/prints/{print_id}"
    is_fetch = request.headers.get("x-requested-with") == "fetch"

    def _done(ok: bool = True):
        if is_fetch:
            return Response(status_code=204 if ok else 403)
        return RedirectResponse(detail_url, status_code=303)

    if current_user is None:
        if is_fetch:
            return Response(status_code=401)
        return RedirectResponse(f"/login?next={detail_url}", status_code=303)

    p = db.query(Print).filter(Print.id == print_id, Print.user_id == current_user.id).first()
    if p is None or rating < 0 or rating > 5:
        return _done(ok=False)

    p.rating = rating or None
    db.commit()
    return _done()


def _toggle_like(
    username: str,
    print_id: int,
    request: Request,
    db: Session,
    current_user: Optional[User],
    *,
    want_liked: bool,
):
    """Shared like/unlike handler. Mirrors /rate's auth + fetch/no-JS pattern.

    Non-owners only (you can't like your own print). JS posts here via fetch
    (X-Requested-With: fetch) and gets JSON {liked, count}; no-JS falls back to
    a full redirect to the detail page. like_count is recomputed from the likes
    table on every toggle so the denormalized counter can't drift.
    """
    detail_url = f"/@{username}/prints/{print_id}"
    is_fetch = request.headers.get("x-requested-with") == "fetch"

    def _json(p):
        return JSONResponse({"liked": want_liked, "count": p.like_count})

    def _fail(status: int):
        if is_fetch:
            return Response(status_code=status)
        if status == 401:
            return RedirectResponse(f"/login?next={detail_url}", status_code=303)
        return RedirectResponse(detail_url, status_code=303)

    if current_user is None:
        return _fail(401)

    user = db.query(User).filter(func.lower(User.username) == username.lower()).first()
    if user is None:
        return _fail(404)

    p = db.query(Print).filter(
        Print.id == print_id,
        Print.user_id == user.id,
        Print.is_public == True,   # noqa: E712
        Print.queued == False,     # noqa: E712
    ).first()
    # Can't like a missing print or your own print.
    if p is None or p.user_id == current_user.id:
        return _fail(403)

    existing = db.query(Like).filter(
        Like.user_id == current_user.id, Like.print_id == p.id
    ).first()
    if want_liked and existing is None:
        db.add(Like(user_id=current_user.id, print_id=p.id))
    elif not want_liked and existing is not None:
        db.delete(existing)
    db.flush()

    # Recompute from source of truth — no drift even on double-clicks/races.
    p.like_count = db.query(Like).filter(Like.print_id == p.id).count()
    db.commit()

    if is_fetch:
        return _json(p)
    return RedirectResponse(detail_url, status_code=303)


@router.post("/@{username}/prints/{print_id}/like")
def like_print(
    username: str,
    print_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    return _toggle_like(username, print_id, request, db, current_user, want_liked=True)


@router.post("/@{username}/prints/{print_id}/unlike")
def unlike_print(
    username: str,
    print_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    return _toggle_like(username, print_id, request, db, current_user, want_liked=False)


@router.post("/@{username}/prints/{print_id}/collections")
def set_print_collections(
    username: str,
    print_id: int,
    collection_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    """Owner-only: sync which of the owner's collections contain this print to the
    checked set (session-cookie auth, like /rate). No-JS form submit → redirect back."""
    detail_url = f"/@{username}/prints/{print_id}"
    if current_user is None:
        return RedirectResponse(f"/login?next={detail_url}", status_code=303)
    p = db.query(Print).filter(Print.id == print_id, Print.user_id == current_user.id).first()
    if p is None:
        return RedirectResponse(detail_url, status_code=303)
    # Constrain to the user's own collections so a crafted id can't touch others'.
    own_ids = {c.id for c in db.query(Collection.id).filter(Collection.user_id == current_user.id).all()}
    checked = set(collection_ids) & own_ids
    existing = {
        r.collection_id for r in db.query(CollectionPrint.collection_id).filter(CollectionPrint.print_id == p.id).all()
    } & own_ids
    for cid in checked - existing:
        db.add(CollectionPrint(collection_id=cid, print_id=p.id))
    to_remove = existing - checked
    if to_remove:
        db.query(CollectionPrint).filter(
            CollectionPrint.print_id == p.id, CollectionPrint.collection_id.in_(to_remove)
        ).delete(synchronize_session=False)
    db.commit()
    return RedirectResponse(detail_url, status_code=303)


@router.get("/@{username}/collections/{collection_ref}", response_class=HTMLResponse)
def public_collection(
    request: Request,
    username: str,
    collection_ref: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    try:
        collection_id = int(collection_ref.split("-", 1)[0])
    except (ValueError, AttributeError):
        return RedirectResponse(f"/@{username}", status_code=303)

    user = db.query(User).filter(func.lower(User.username) == username.lower()).first()
    if user is None:
        return templates.TemplateResponse(
            request, "404_user.html",
            {"username": username, "current_user": current_user},
            status_code=404,
        )
    if user.username != username:
        return RedirectResponse(url=f"/@{user.username}/collections/{collection_ref}", status_code=301)

    c = db.query(Collection).filter(Collection.id == collection_id, Collection.user_id == user.id).first()
    if c is None:
        return RedirectResponse(f"/@{username}", status_code=303)
    if collection_ref != c.url_id:
        return RedirectResponse(url=f"/@{user.username}/collections/{c.url_id}", status_code=301)

    is_owner = current_user is not None and current_user.id == user.id
    pids = [r.print_id for r in db.query(CollectionPrint.print_id).filter(CollectionPrint.collection_id == c.id).order_by(CollectionPrint.created_at.desc()).all()]
    prints, fil_meta = [], {}
    if pids:
        q = db.query(Print).filter(Print.id.in_(pids), Print.user_id == user.id)
        if not is_owner:
            q = q.filter(Print.is_public == True, Print.queued == False)  # noqa: E712
        prints = q.order_by(Print.created_at.desc()).all()
        all_fil_ids = {fid for p in prints for fid in (p.filament_ids or [])}
        if all_fil_ids:
            fil_meta = {f.id: f for f in db.query(Filament).filter(Filament.id.in_(all_fil_ids), Filament.user_id == user.id).all()}

    return templates.TemplateResponse(
        request,
        "collection_public.html",
        {
            "user": user,
            "collection": c,
            "prints": prints,
            "fil_meta": fil_meta,
            "is_owner": is_owner,
            "current_user": current_user,
            "app_url": os.environ.get("APP_URL", "https://printshelf.app"),
        },
    )
