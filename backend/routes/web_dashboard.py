"""Web dashboard CRUD — server-rendered Jinja UI for printers, filaments, prints.

All endpoints require an authenticated session cookie. No JS framework;
forms POST → server redirects → page re-renders. Photo upload + URL import
are wired in subsequent tasks.
"""
import os
from datetime import date

import httpx
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import nullslast
from sqlalchemy.orm import Session

from auth import SESSION_COOKIE_NAME, get_current_user_web_optional
from limits import enforce_filament_limit, enforce_print_limit
from models import (
    AffiliateClick,
    Filament,
    FilamentStatus,
    Follow,
    Print,
    PrintStatus,
    Printer,
    SourcePlatform,
    User,
    get_db,
)
from email_service import send_feed_notification
from import_service import ImportError_, extract as extract_url
from filament_import_service import extract as extract_filament_url
from affiliate import apply_affiliate
from models import ImportCache
from storage import MAX_UPLOAD_BYTES, UploadError, delete_image, upload_image

_log = logging.getLogger(__name__)
_IMPORT_CACHE_TTL_DAYS = 14

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_BACKEND_DIR, "templates"))


def _require_user(user: Optional[User]) -> Optional[RedirectResponse]:
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return None


def _ctx(user: User, db: Optional[Session] = None, **extra) -> dict:
    base = {"current_user": user, "user": user, **extra}
    if db is not None:
        base["sidebar_prints"] = db.query(Print).filter(Print.user_id == user.id, Print.queued == False).count()  # noqa: E712
        base["sidebar_queue"] = db.query(Print).filter(Print.user_id == user.id, Print.queued == True).count()  # noqa: E712
        base["sidebar_filaments"] = db.query(Filament).filter(Filament.user_id == user.id).count()
    return base


def _parse_int_list(raw: list[str]) -> list[int]:
    out = []
    for v in raw:
        v = (v or "").strip()
        if not v:
            continue
        try:
            out.append(int(v))
        except ValueError:
            continue
    return out


def _parse_date(s: str) -> Optional[date]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _parse_float(s: str) -> Optional[float]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _parse_int(s: str, min_val: Optional[int] = None, max_val: Optional[int] = None) -> Optional[int]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        v = int(s)
        if min_val is not None and v < min_val:
            return None
        if max_val is not None and v > max_val:
            return None
        return v
    except ValueError:
        return None


def _parse_supports(s: str) -> Optional[bool]:
    if s == "yes":
        return True
    if s == "no":
        return False
    return None


def _normalize_hex(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    return v if v.startswith("#") else f"#{v}"


# ============== Queue redirect ==============

@router.get("/queue")
def queue_redirect():
    return RedirectResponse(url="/dashboard/prints?queued=true", status_code=301)


# ============== Printers ==============

@router.get("/printers", response_class=HTMLResponse)
def list_printers(
    request: Request,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    printers = (
        db.query(Printer).filter(Printer.user_id == user.id)
        .order_by(Printer.created_at.desc()).all()
    )
    return templates.TemplateResponse(
        request, "dashboard/printers_list.html",
        _ctx(user, db=db, printers=printers),
    )


@router.get("/printers/new", response_class=HTMLResponse)
def new_printer(
    request: Request,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    return templates.TemplateResponse(
        request, "dashboard/printer_form.html",
        _ctx(user, db=db, printer=None, errors=[], values={}),
    )


@router.post("/printers")
def create_printer(
    request: Request,
    name: str = Form(...),
    brand: str = Form(""),
    model: str = Form(""),
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    if not name.strip():
        return templates.TemplateResponse(
            request, "dashboard/printer_form.html",
            _ctx(user, db=db, printer=None, errors=["Name is required."], values={"name": name, "brand": brand, "model": model}),
            status_code=400,
        )
    p = Printer(user_id=user.id, name=name.strip(), brand=brand.strip() or None, model=model.strip() or None)
    db.add(p)
    db.commit()
    return RedirectResponse("/dashboard/printers", status_code=303)


@router.get("/printers/{printer_id}/edit", response_class=HTMLResponse)
def edit_printer(
    request: Request,
    printer_id: int,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    p = db.query(Printer).filter(Printer.id == printer_id, Printer.user_id == user.id).first()
    if p is None:
        return RedirectResponse("/dashboard/printers", status_code=303)
    return templates.TemplateResponse(
        request, "dashboard/printer_form.html",
        _ctx(user, db=db, printer=p, errors=[], values={"name": p.name, "brand": p.brand or "", "model": p.model or ""}),
    )


@router.post("/printers/{printer_id}")
def update_printer(
    request: Request,
    printer_id: int,
    name: str = Form(...),
    brand: str = Form(""),
    model: str = Form(""),
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    p = db.query(Printer).filter(Printer.id == printer_id, Printer.user_id == user.id).first()
    if p is None:
        return RedirectResponse("/dashboard/printers", status_code=303)
    if not name.strip():
        return templates.TemplateResponse(
            request, "dashboard/printer_form.html",
            _ctx(user, db=db, printer=p, errors=["Name is required."], values={"name": name, "brand": brand, "model": model}),
            status_code=400,
        )
    p.name = name.strip()
    p.brand = brand.strip() or None
    p.model = model.strip() or None
    db.commit()
    return RedirectResponse("/dashboard/printers", status_code=303)


@router.post("/printers/{printer_id}/delete")
def delete_printer(
    printer_id: int,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    p = db.query(Printer).filter(Printer.id == printer_id, Printer.user_id == user.id).first()
    if p is not None:
        db.delete(p)
        db.commit()
    return RedirectResponse("/dashboard/printers", status_code=303)


# ============== Filaments ==============

@router.get("/filaments", response_class=HTMLResponse)
def list_filaments(
    request: Request,
    cap: Optional[str] = None,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    filaments = (
        db.query(Filament).filter(Filament.user_id == user.id)
        .order_by(Filament.created_at.desc()).all()
    )
    return templates.TemplateResponse(
        request, "dashboard/filaments_list.html",
        _ctx(user, db=db, filaments=filaments, statuses=[s.value for s in FilamentStatus], cap_hit=cap == "1"),
    )


def _filament_form_ctx(user: User, db: Optional[Session], filament: Optional[Filament], errors: list, values: dict) -> dict:
    return _ctx(
        user,
        db=db,
        filament=filament,
        errors=errors,
        values=values,
        statuses=[s.value for s in FilamentStatus],
    )


@router.get("/filaments/new", response_class=HTMLResponse)
def new_filament(
    request: Request,
    import_url: Optional[str] = None,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    defaults: dict = {"diameter": "1.75", "status": "own"}
    import_error: Optional[str] = None
    import_notice: Optional[str] = None
    import_partial: bool = False
    if import_url:
        # Even if scraping fails outright, we still keep the URL the user
        # pasted — they can fill in the rest manually and the Buy link
        # still works.
        defaults["source_url"] = import_url.strip()
        try:
            result = extract_filament_url(import_url.strip())
        except ImportError_ as e:
            import_error = str(e)
            result = None
        except Exception:
            _log.exception("filament import failed for %s", import_url)
            import_error = "Couldn't read that page — paste the fields manually."
            result = None
        if result:
            import_partial = bool(result.get("partial"))
            store = result.get("store") or "manual"
            if store == "manual":
                # Unknown store — OG scraping may have salvaged something, but
                # we have no brand defaults and the user can't expect auto-fill.
                # Show the same yellow notice as the partial case.
                import_partial = True
                import_notice = (
                    "Unknown store — we don't auto-detect brand/material for that site. "
                    "URL saved; fill the fields in manually."
                )
            elif import_partial:
                import_notice = (
                    f"Partial pre-fill from {store} — the page blocked metadata, "
                    f"please double-check the fields below."
                )
            else:
                import_notice = f"Pre-filled from {store}."
            # Don't overwrite defaults with None/empty values.
            for k_src, k_dst in [
                ("brand", "brand"), ("material", "material"),
                ("color_name", "color_name"),
            ]:
                v = result.get(k_src)
                if v:
                    defaults[k_dst] = v
            # Always store the user's pasted URL — never the redirect target.
            # MatterHackers (and others) 302 our scrape to a category/home page
            # when bot detection fires; using `r.url` there would strip the
            # deep product path and break the Buy redirector.
            defaults["source_url"] = import_url.strip()
            if result.get("price") is not None:
                defaults["price_at_save"] = result["price"]
    ctx = _filament_form_ctx(user, db, None, [], defaults)
    ctx["import_error"] = import_error
    ctx["import_notice"] = import_notice
    ctx["import_partial"] = import_partial
    return templates.TemplateResponse(request, "dashboard/filament_form.html", ctx)


@router.post("/filaments")
def create_filament(
    request: Request,
    brand: str = Form(...),
    material: str = Form(...),
    color_name: str = Form(""),
    color_hex: str = Form(""),
    diameter: str = Form("1.75"),
    status: str = Form("own"),
    source_url: str = Form(""),
    price_at_save: str = Form(""),
    notes: str = Form(""),
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    try:
        enforce_filament_limit(db, user)
    except HTTPException as e:
        if e.status_code == 402:
            return RedirectResponse("/dashboard/upgrade", status_code=303)
        raise
    errors = []
    try:
        diameter_f = float(diameter or "1.75")
    except ValueError:
        diameter_f = 1.75
        errors.append("Diameter must be a number.")
    price_f: Optional[float] = None
    if price_at_save.strip():
        try:
            price_f = float(price_at_save.strip())
        except ValueError:
            errors.append("Price must be a number.")
    if status not in {s.value for s in FilamentStatus}:
        errors.append("Invalid status.")
    if not brand.strip() or not material.strip():
        errors.append("Brand and material are required.")
    if errors:
        return templates.TemplateResponse(
            request, "dashboard/filament_form.html",
            _filament_form_ctx(user, db, None, errors, {
                "brand": brand, "material": material, "color_name": color_name,
                "color_hex": color_hex, "diameter": diameter, "status": status,
                "source_url": source_url, "price_at_save": price_at_save, "notes": notes,
            }),
            status_code=400,
        )
    f = Filament(
        user_id=user.id, brand=brand.strip(), material=material.strip(),
        color_name=color_name.strip() or None, color_hex=_normalize_hex(color_hex),
        diameter=diameter_f, status=status,
        source_url=source_url.strip() or None, price_at_save=price_f,
        notes=notes.strip() or None,
    )
    db.add(f)
    db.commit()
    return RedirectResponse("/dashboard/filaments", status_code=303)


@router.get("/filaments/{filament_id}/edit", response_class=HTMLResponse)
def edit_filament(
    request: Request,
    filament_id: int,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    f = db.query(Filament).filter(Filament.id == filament_id, Filament.user_id == user.id).first()
    if f is None:
        return RedirectResponse("/dashboard/filaments", status_code=303)
    return templates.TemplateResponse(
        request, "dashboard/filament_form.html",
        _filament_form_ctx(user, db, f, [], {
            "brand": f.brand, "material": f.material,
            "color_name": f.color_name or "", "color_hex": f.color_hex or "",
            "diameter": str(f.diameter), "status": f.status,
            "source_url": f.source_url or "",
            "price_at_save": f.price_at_save if f.price_at_save is not None else "",
            "notes": f.notes or "",
        }),
    )


@router.post("/filaments/{filament_id}")
def update_filament(
    request: Request,
    filament_id: int,
    brand: str = Form(...),
    material: str = Form(...),
    color_name: str = Form(""),
    color_hex: str = Form(""),
    diameter: str = Form("1.75"),
    status: str = Form("own"),
    source_url: str = Form(""),
    price_at_save: str = Form(""),
    notes: str = Form(""),
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    f = db.query(Filament).filter(Filament.id == filament_id, Filament.user_id == user.id).first()
    if f is None:
        return RedirectResponse("/dashboard/filaments", status_code=303)
    try:
        diameter_f = float(diameter or "1.75")
    except ValueError:
        diameter_f = 1.75
    if status in {s.value for s in FilamentStatus}:
        f.status = status
    f.brand = brand.strip()
    f.material = material.strip()
    f.color_name = color_name.strip() or None
    f.color_hex = _normalize_hex(color_hex)
    f.diameter = diameter_f
    f.source_url = source_url.strip() or None
    if price_at_save.strip():
        try:
            f.price_at_save = float(price_at_save.strip())
        except ValueError:
            pass
    else:
        f.price_at_save = None
    f.notes = notes.strip() or None
    db.commit()
    return RedirectResponse("/dashboard/filaments", status_code=303)


@router.post("/filaments/{filament_id}/delete")
def delete_filament(
    filament_id: int,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    f = db.query(Filament).filter(Filament.id == filament_id, Filament.user_id == user.id).first()
    if f is not None:
        db.delete(f)
        db.commit()
    return RedirectResponse("/dashboard/filaments", status_code=303)


@router.get("/filaments/{filament_id}/buy")
def buy_filament(
    filament_id: int,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    """302 to the filament's source_url with an affiliate tag applied.

    Tags are sourced from env vars per `affiliate.py`; if none is set for
    the store, we redirect to the bare URL. We only honor source_urls
    that belong to the requesting user — no one can use this endpoint to
    bounce traffic through another user's source links.
    """
    if (r := _require_user(user)) is not None:
        return r
    f = db.query(Filament).filter(Filament.id == filament_id, Filament.user_id == user.id).first()
    if f is None or not f.source_url:
        return RedirectResponse("/dashboard/filaments", status_code=303)
    from filament_import_service import detect_store
    store = detect_store(f.source_url)
    target = apply_affiliate(f.source_url)
    db.add(AffiliateClick(user_id=user.id, filament_id=f.id, store=store or None))
    db.commit()
    _log.info("filament buy click filament_id=%s user=%s store=%s target=%s", f.id, user.id, store, target)
    return RedirectResponse(target, status_code=302)


# ============== Prints ==============

@router.get("/prints", response_class=HTMLResponse)
def list_prints(
    request: Request,
    queued: Optional[str] = None,
    search: Optional[str] = None,
    sort: Optional[str] = None,
    cap: Optional[str] = None,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    q = db.query(Print).filter(Print.user_id == user.id)
    queued_filter = None
    if queued == "true":
        q = q.filter(Print.queued == True)  # noqa: E712
        queued_filter = "true"
    elif queued == "false":
        q = q.filter(Print.queued == False)  # noqa: E712
        queued_filter = "false"
    search_val = (search or "").strip()
    if search_val:
        q = q.filter(Print.title.ilike(f"%{search_val}%"))
    sort_map = {
        "oldest": Print.created_at.asc(),
        "title": Print.title.asc(),
        "rating": nullslast(Print.rating.desc()),
        "date": nullslast(Print.print_date.desc()),
    }
    rows = q.order_by(sort_map.get(sort or "", Print.created_at.desc())).all()
    printer_names = {p.id: p.name for p in db.query(Printer).filter(Printer.user_id == user.id).all()}
    fil_meta = {f.id: f for f in db.query(Filament).filter(Filament.user_id == user.id).all()}
    return templates.TemplateResponse(
        request, "dashboard/prints_list.html",
        _ctx(user, db=db, prints=rows, queued_filter=queued_filter,
             printer_names=printer_names, fil_meta=fil_meta,
             search=search_val, sort=sort or "newest", cap_hit=cap == "1"),
    )


def _print_form_ctx(user: User, db: Session, p: Optional[Print], errors: list, values: dict) -> dict:
    printers = db.query(Printer).filter(Printer.user_id == user.id).order_by(Printer.name).all()
    filaments = db.query(Filament).filter(Filament.user_id == user.id).order_by(Filament.brand, Filament.material).all()
    return _ctx(
        user, db=db, print_=p, errors=errors, values=values,
        printers=printers, filaments=filaments,
        platforms=[p.value for p in SourcePlatform],
        statuses=[s.value for s in PrintStatus],
    )


@router.get("/prints/new", response_class=HTMLResponse)
def new_print(
    request: Request,
    queued: Optional[str] = None,
    import_url: Optional[str] = None,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    defaults = {
        "queued": "1" if queued == "true" else "",
        "status": "queued" if queued == "true" else "printed",
        "source_platform": "manual",
        "is_public": "1",
    }
    import_error: Optional[str] = None
    import_notice: Optional[str] = None
    import_partial: bool = False
    if import_url:
        # Check cache first; on miss, scrape.
        from datetime import datetime, timedelta
        row = db.query(ImportCache).filter(ImportCache.source_url == import_url.strip()).first()
        result: Optional[dict] = None
        if row and (datetime.utcnow() - row.fetched_at) < timedelta(days=_IMPORT_CACHE_TTL_DAYS):
            result = {
                "platform": row.platform,
                "title": row.title,
                "designer": row.designer,
                "thumbnail_url": row.thumbnail_url,
                "source_url": row.source_url,
                "partial": (row.raw_metadata or {}).get("partial", False),
            }
        else:
            try:
                result = extract_url(import_url.strip())
                if row is None:
                    row = ImportCache(source_url=import_url.strip())
                    db.add(row)
                row.platform = result["platform"]
                row.title = result["title"]
                row.designer = result.get("designer")
                row.thumbnail_url = result.get("thumbnail_url")
                row.raw_metadata = result
                row.fetched_at = datetime.utcnow()
                db.commit()
            except ImportError_ as e:
                import_error = str(e)
        if result:
            import_partial = bool(result.get("partial"))
            if import_partial:
                import_notice = (
                    f"Title pulled from the URL ({result.get('platform')}) — "
                    f"add a photo and designer manually below."
                )
            else:
                import_notice = f"Pre-filled from {result.get('platform')}."
            defaults.update({
                "title": result.get("title") or "",
                "designer": result.get("designer") or "",
                "source_platform": result.get("platform") or "manual",
                "source_url": import_url.strip(),
                "thumbnail_url": result.get("thumbnail_url") or "",
            })
        else:
            defaults["source_url"] = import_url.strip()

    ctx = _print_form_ctx(user, db, None, [], defaults)
    ctx["import_error"] = import_error
    ctx["import_notice"] = import_notice
    ctx["import_partial"] = import_partial
    return templates.TemplateResponse(request, "dashboard/print_form.html", ctx)


async def _resolve_photo(photo_file: Optional[UploadFile], photo_url: str, existing: str = "") -> tuple[str, list[str]]:
    """Returns (resolved_photo_url, errors). Uploaded file wins over typed URL."""
    errors: list[str] = []
    if photo_file is not None and photo_file.filename:
        raw = await photo_file.read(MAX_UPLOAD_BYTES + 1)
        if len(raw) > MAX_UPLOAD_BYTES:
            errors.append(f"Photo too large (max {MAX_UPLOAD_BYTES // 1024 // 1024}MB).")
            return existing, errors
        try:
            return upload_image(raw, prefix="p"), errors
        except UploadError as e:
            errors.append(f"Photo: {e}")
            return existing, errors
        except Exception as e:
            _log.exception("dashboard photo upload failed")
            errors.append("Photo upload failed.")
            return existing, errors
    if photo_url.strip():
        return photo_url.strip(), errors
    return existing, errors


@router.post("/prints")
async def create_print(
    request: Request,
    title: str = Form(""),
    designer: str = Form(""),
    source_platform: str = Form("manual"),
    source_url: str = Form(""),
    thumbnail_url: str = Form(""),
    photo_url: str = Form(""),
    photo_file: Optional[UploadFile] = File(None),
    printer_id: str = Form(""),
    filament_ids: list[str] = Form(default=[]),
    status: str = Form("printed"),
    rating: str = Form(""),
    notes: str = Form(""),
    print_date: str = Form(""),
    queued: str = Form(""),
    is_public: str = Form(""),
    layer_height: str = Form(""),
    infill_pct: str = Form(""),
    supports: str = Form(""),
    print_time_mins: str = Form(""),
    filament_used_g: str = Form(""),
    video_url: str = Form(""),
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    try:
        enforce_print_limit(db, user)
    except HTTPException as e:
        if e.status_code == 402:
            return RedirectResponse("/dashboard/upgrade", status_code=303)
        raise
    errors: list[str] = []

    # Auto-import: if the user pasted a source URL but skipped the "Pre-fill
    # form" button, fill missing fields from the URL before validating.
    if source_url.strip() and not title.strip():
        try:
            result = extract_url(source_url.strip())
            title = title or (result.get("title") or "")
            designer = designer or (result.get("designer") or "")
            if not thumbnail_url.strip() and result.get("thumbnail_url"):
                thumbnail_url = result["thumbnail_url"]
            if source_platform in ("", "manual") and result.get("platform"):
                source_platform = result["platform"]
            # Stash in import cache for next time
            from datetime import datetime
            row = db.query(ImportCache).filter(ImportCache.source_url == source_url.strip()).first()
            if row is None:
                row = ImportCache(source_url=source_url.strip())
                db.add(row)
            row.platform = result["platform"]
            row.title = result["title"]
            row.designer = result.get("designer")
            row.thumbnail_url = result.get("thumbnail_url")
            row.raw_metadata = result
            row.fetched_at = datetime.utcnow()
            db.commit()
        except ImportError_ as e:
            errors.append(f"Couldn't auto-fill from that URL ({e}). Add a title manually.")

    if not title.strip():
        errors.append("Title is required (or paste a source URL we can pull a title from).")
    if source_platform not in {p.value for p in SourcePlatform}:
        errors.append("Invalid source platform.")
    if status == "queued":
        queued = "1"
        status = "printed"
    if status not in {s.value for s in PrintStatus} - {"queued"}:
        errors.append("Invalid status.")

    rating_int: Optional[int] = None
    if rating.strip():
        try:
            rating_int = int(rating)
            if rating_int < 1 or rating_int > 5:
                errors.append("Rating must be 1-5.")
                rating_int = None
        except ValueError:
            errors.append("Rating must be a number.")

    printer_id_int: Optional[int] = None
    if printer_id.strip():
        try:
            printer_id_int = int(printer_id)
            owned = db.query(Printer.id).filter(Printer.id == printer_id_int, Printer.user_id == user.id).first()
            if not owned:
                errors.append("Printer not found.")
                printer_id_int = None
        except ValueError:
            errors.append("Invalid printer.")

    fil_ids = _parse_int_list(filament_ids)
    if fil_ids:
        rows = db.query(Filament.id).filter(Filament.user_id == user.id, Filament.id.in_(fil_ids)).all()
        owned_ids = {r[0] for r in rows}
        missing = [f for f in fil_ids if f not in owned_ids]
        if missing:
            errors.append(f"Filaments not found: {missing}")

    # Resolve photo: uploaded file wins over typed URL
    resolved_photo_url, photo_errors = await _resolve_photo(photo_file, photo_url, existing="")
    errors.extend(photo_errors)

    layer_height_f = _parse_float(layer_height)
    infill_pct_i = _parse_int(infill_pct, min_val=0, max_val=100)
    supports_b = _parse_supports(supports)
    print_time_i = _parse_int(print_time_mins, min_val=1)
    filament_used_f = _parse_float(filament_used_g)

    if errors:
        values = {
            "title": title, "designer": designer, "source_platform": source_platform,
            "source_url": source_url, "thumbnail_url": thumbnail_url, "photo_url": photo_url,
            "printer_id": printer_id, "filament_ids": fil_ids, "status": status,
            "rating": rating, "notes": notes, "print_date": print_date,
            "queued": queued, "is_public": is_public,
            "layer_height": layer_height, "infill_pct": infill_pct,
            "supports": supports, "print_time_mins": print_time_mins,
            "filament_used_g": filament_used_g, "video_url": video_url,
        }
        return templates.TemplateResponse(
            request, "dashboard/print_form.html",
            _print_form_ctx(user, db, None, errors, values),
            status_code=400,
        )

    p = Print(
        user_id=user.id, title=title.strip(),
        designer=designer.strip() or None,
        source_platform=source_platform,
        source_url=source_url.strip() or None,
        thumbnail_url=thumbnail_url.strip() or None,
        photo_url=resolved_photo_url or None,
        printer_id=printer_id_int,
        filament_ids=fil_ids,
        status=status, rating=rating_int,
        notes=notes.strip() or None,
        queued=bool(queued),
        is_public=bool(is_public),
        print_date=_parse_date(print_date),
        layer_height=layer_height_f,
        infill_pct=infill_pct_i,
        supports=supports_b,
        print_time_mins=print_time_i,
        filament_used_g=filament_used_f,
        video_url=video_url.strip() or None,
    )
    db.add(p)
    db.commit()

    # Notify followers when a public non-queued print is logged
    if p.is_public and not p.queued:
        followers = (
            db.query(User)
            .join(Follow, Follow.follower_id == User.id)
            .filter(Follow.following_id == user.id, User.notify_feed == True, User.unsubscribe_token != None)  # noqa: E712
            .all()
        )
        print_url = f"{os.environ.get('APP_URL', 'https://printshelf.app')}/@{user.username}/prints/{p.id}"
        display = user.display_name or user.username
        for follower in followers:
            send_feed_notification(follower.email, user.username, display, p.title, print_url, follower.unsubscribe_token)

    target = "/dashboard/prints?queued=true" if p.queued else "/dashboard/prints"
    return RedirectResponse(target, status_code=303)


@router.get("/prints/{print_id}/edit", response_class=HTMLResponse)
def edit_print(
    request: Request,
    print_id: int,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    p = db.query(Print).filter(Print.id == print_id, Print.user_id == user.id).first()
    if p is None:
        return RedirectResponse("/dashboard/prints", status_code=303)
    values = {
        "title": p.title, "designer": p.designer or "",
        "source_platform": p.source_platform, "source_url": p.source_url or "",
        "thumbnail_url": p.thumbnail_url or "", "photo_url": p.photo_url or "",
        "printer_id": str(p.printer_id) if p.printer_id else "",
        "filament_ids": p.filament_ids or [],
        "status": "queued" if p.queued else p.status, "rating": str(p.rating) if p.rating else "",
        "notes": p.notes or "",
        "print_date": p.print_date.isoformat() if p.print_date else "",
        "queued": "1" if p.queued else "",
        "is_public": "1" if p.is_public else "",
        "layer_height": str(p.layer_height) if p.layer_height is not None else "",
        "infill_pct": str(p.infill_pct) if p.infill_pct is not None else "",
        "supports": ("yes" if p.supports is True else ("no" if p.supports is False else "")),
        "print_time_mins": str(p.print_time_mins) if p.print_time_mins is not None else "",
        "filament_used_g": str(p.filament_used_g) if p.filament_used_g is not None else "",
        "video_url": p.video_url or "",
    }
    return templates.TemplateResponse(
        request, "dashboard/print_form.html",
        _print_form_ctx(user, db, p, [], values),
    )


@router.post("/prints/{print_id}")
async def update_print(
    request: Request,
    print_id: int,
    title: str = Form(...),
    designer: str = Form(""),
    source_platform: str = Form("manual"),
    source_url: str = Form(""),
    thumbnail_url: str = Form(""),
    photo_url: str = Form(""),
    photo_file: Optional[UploadFile] = File(None),
    printer_id: str = Form(""),
    filament_ids: list[str] = Form(default=[]),
    status: str = Form("printed"),
    rating: str = Form(""),
    notes: str = Form(""),
    print_date: str = Form(""),
    queued: str = Form(""),
    is_public: str = Form(""),
    layer_height: str = Form(""),
    infill_pct: str = Form(""),
    supports: str = Form(""),
    print_time_mins: str = Form(""),
    filament_used_g: str = Form(""),
    video_url: str = Form(""),
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    p = db.query(Print).filter(Print.id == print_id, Print.user_id == user.id).first()
    if p is None:
        return RedirectResponse("/dashboard/prints", status_code=303)

    rating_int: Optional[int] = None
    if rating.strip():
        try:
            rating_int = int(rating)
            if rating_int < 1 or rating_int > 5:
                rating_int = None
        except ValueError:
            pass

    printer_id_int: Optional[int] = None
    if printer_id.strip():
        try:
            printer_id_int = int(printer_id)
            owned = db.query(Printer.id).filter(Printer.id == printer_id_int, Printer.user_id == user.id).first()
            if not owned:
                printer_id_int = None
        except ValueError:
            pass

    fil_ids = _parse_int_list(filament_ids)
    if fil_ids:
        rows = db.query(Filament.id).filter(Filament.user_id == user.id, Filament.id.in_(fil_ids)).all()
        owned_ids = {r[0] for r in rows}
        fil_ids = [f for f in fil_ids if f in owned_ids]

    # Photo: uploaded file replaces existing; otherwise typed URL or keep existing
    resolved_photo_url, photo_errors = await _resolve_photo(photo_file, photo_url, existing=p.photo_url or "")
    if photo_errors:
        values = {
            "title": title, "designer": designer, "source_platform": source_platform,
            "source_url": source_url, "thumbnail_url": thumbnail_url, "photo_url": photo_url,
            "printer_id": printer_id, "filament_ids": fil_ids,
            "status": "queued" if p.queued else p.status,
            "rating": rating, "notes": notes, "print_date": print_date,
            "queued": "1" if p.queued else "", "is_public": "1" if p.is_public else "",
        }
        return templates.TemplateResponse(
            request, "dashboard/print_form.html",
            _print_form_ctx(user, db, p, photo_errors, values),
            status_code=400,
        )

    p.title = title.strip()
    p.designer = designer.strip() or None
    if source_platform in {sp.value for sp in SourcePlatform}:
        p.source_platform = source_platform
    p.source_url = source_url.strip() or None
    p.thumbnail_url = thumbnail_url.strip() or None
    p.photo_url = resolved_photo_url or None
    p.printer_id = printer_id_int
    p.filament_ids = fil_ids
    if status == "queued":
        p.queued = True
    else:
        if status in {s.value for s in PrintStatus} - {"queued"}:
            p.status = status
        p.queued = False
    p.rating = rating_int
    p.notes = notes.strip() or None
    p.print_date = _parse_date(print_date)
    p.is_public = bool(is_public)
    p.layer_height = _parse_float(layer_height)
    p.infill_pct = _parse_int(infill_pct, min_val=0, max_val=100)
    p.supports = _parse_supports(supports)
    p.print_time_mins = _parse_int(print_time_mins, min_val=1)
    p.filament_used_g = _parse_float(filament_used_g)
    p.video_url = video_url.strip() or None
    db.commit()
    return RedirectResponse("/dashboard/prints", status_code=303)


@router.get("/prints/{print_id}/photo", response_class=HTMLResponse)
def photo_upload_form(
    print_id: int,
    request: Request,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    p = db.query(Print).filter(Print.id == print_id, Print.user_id == user.id).first()
    if p is None:
        return RedirectResponse("/dashboard/prints", status_code=303)
    return templates.TemplateResponse(request, "dashboard/photo_upload.html",
        _ctx(user, db=db, print_=p, error=None))


@router.post("/prints/{print_id}/photo")
async def photo_upload_submit(
    print_id: int,
    request: Request,
    photo_file: Optional[UploadFile] = File(None),
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    p = db.query(Print).filter(Print.id == print_id, Print.user_id == user.id).first()
    if p is None:
        return RedirectResponse("/dashboard/prints", status_code=303)

    resolved, errors = await _resolve_photo(photo_file, "", existing=p.photo_url or "")
    if errors:
        return templates.TemplateResponse(request, "dashboard/photo_upload.html",
            _ctx(user, db=db, print_=p, error=errors[0]), status_code=400)

    p.photo_url = resolved or p.photo_url
    db.commit()
    return RedirectResponse("/dashboard/prints", status_code=303)


@router.post("/prints/{print_id}/printed")
def mark_print_done(
    print_id: int,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    p = db.query(Print).filter(Print.id == print_id, Print.user_id == user.id).first()
    if p is not None:
        p.queued = False
        p.status = "printed"
        if p.print_date is None:
            p.print_date = date.today()
        db.commit()
    return RedirectResponse("/dashboard/prints", status_code=303)


@router.post("/prints/{print_id}/delete")
def delete_print(
    print_id: int,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    p = db.query(Print).filter(Print.id == print_id, Print.user_id == user.id).first()
    if p is not None:
        db.delete(p)
        db.commit()
    return RedirectResponse("/dashboard/prints", status_code=303)


# ============== Account settings ==============

_SOCIAL_URL_TEMPLATES = {
    "makerworld":  "https://makerworld.com/en/@{handle}",
    "printables":  "https://www.printables.com/@{handle}",
    "instagram":   "https://www.instagram.com/{handle}",
    "tiktok":      "https://www.tiktok.com/@{handle}",
    "youtube":     "https://www.youtube.com/@{handle}",
    "x":           "https://x.com/{handle}",
    "thingiverse": "https://www.thingiverse.com/{handle}",
}


def _social_to_url(platform: str, value: str) -> str:
    """Accept a bare handle or full URL; always return a full https URL."""
    v = value.strip().rstrip("/")
    if not v:
        return ""
    if v.startswith("https://") or v.startswith("http://"):
        return v
    handle = v.lstrip("@")
    tmpl = _SOCIAL_URL_TEMPLATES.get(platform, "")
    return tmpl.format(handle=handle) if tmpl else v


def _url_to_handle(value: str) -> str:
    """Strip the platform base URL; return just the bare handle (no @)."""
    v = value.strip().rstrip("/")
    if v.startswith("https://") or v.startswith("http://"):
        v = v.split("/")[-1]
    return v.lstrip("@")

@router.get("/account", response_class=HTMLResponse)
def account_settings(
    request: Request,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    s = user.socials or {}
    values = {
        "display_name": user.display_name or "",
        "bio": user.bio or "",
        "avatar_url": user.avatar_url or "",
        **{f"social_{k}": _url_to_handle(s.get(k, "")) for k in _SOCIAL_URL_TEMPLATES},
    }
    return templates.TemplateResponse(
        request, "dashboard/account_form.html",
        _ctx(user, db=db, errors=[], saved=False, values=values),
    )


@router.post("/account", response_class=HTMLResponse)
async def save_account_settings(
    request: Request,
    display_name: str = Form(""),
    bio: str = Form(""),
    avatar_url: str = Form(""),
    avatar_file: Optional[UploadFile] = File(None),
    social_makerworld: str = Form(""),
    social_printables: str = Form(""),
    social_instagram: str = Form(""),
    social_tiktok: str = Form(""),
    social_youtube: str = Form(""),
    social_x: str = Form(""),
    social_thingiverse: str = Form(""),
    current_password: str = Form(""),
    new_password: str = Form(""),
    new_password_confirm: str = Form(""),
    notify_follow: str = Form(""),
    notify_feed: str = Form(""),
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    from auth import hash_password, verify_password
    errors = []
    display_name = display_name.strip()
    bio = bio.strip()
    avatar_url = avatar_url.strip()

    raw_handles = {
        "makerworld": social_makerworld.strip(),
        "printables": social_printables.strip(),
        "instagram": social_instagram.strip(),
        "tiktok": social_tiktok.strip(),
        "youtube": social_youtube.strip(),
        "x": social_x.strip(),
        "thingiverse": social_thingiverse.strip(),
    }

    if len(display_name) > 100:
        errors.append("Display name must be 100 characters or fewer.")
    if avatar_url and not avatar_url.startswith(("http://", "https://")):
        errors.append("Avatar URL must start with http:// or https://")

    # Avatar file upload — takes precedence over URL field if provided
    if avatar_file and avatar_file.filename:
        uploaded_url, upload_errors = await _resolve_photo(avatar_file, "", existing=user.avatar_url or "")
        if upload_errors:
            errors.extend(upload_errors)
        elif uploaded_url:
            avatar_url = uploaded_url

    # Mirror external avatar URLs to our CDN — external URLs (e.g. Google/Discord)
    # change or expire, causing the avatar to disappear. Re-host on our storage once.
    elif avatar_url and not avatar_url.startswith(("https://cdn.printshelf.app", "/uploads/")):
        try:
            resp = httpx.get(avatar_url, follow_redirects=True, timeout=10,
                             headers={"User-Agent": "PrintShelf/1.0"})
            resp.raise_for_status()
            raw = resp.content
            if 0 < len(raw) <= MAX_UPLOAD_BYTES:
                mirrored = upload_image(raw, prefix="av")
                _log.info("avatar mirrored user_id=%s -> %s", user.id, mirrored)
                avatar_url = mirrored
        except Exception as exc:
            _log.warning("avatar mirror failed user_id=%s url=%s err=%s", user.id, avatar_url, exc)

    # Password change — only if any password field is filled
    new_password_hash = None
    if current_password or new_password or new_password_confirm:
        if not current_password:
            errors.append("Enter your current password to change it.")
        elif not verify_password(current_password, user.password_hash):
            errors.append("Current password is incorrect.")
        elif len(new_password) < 8:
            errors.append("New password must be at least 8 characters.")
        elif new_password != new_password_confirm:
            errors.append("New passwords don't match.")
        else:
            new_password_hash = hash_password(new_password)

    # Normalise handles → full URLs for storage
    resolved_socials = {k: _social_to_url(k, v) for k, v in raw_handles.items()}

    values = {
        "display_name": display_name, "bio": bio, "avatar_url": avatar_url,
        **{f"social_{k}": v for k, v in raw_handles.items()},
    }
    if errors:
        return templates.TemplateResponse(
            request, "dashboard/account_form.html",
            _ctx(user, db=db, errors=errors, saved=False, values=values),
            status_code=400,
        )

    user.display_name = display_name or None
    user.bio = bio or None
    user.avatar_url = avatar_url or None
    user.socials = {k: v for k, v in resolved_socials.items() if v} or None
    user.notify_follow = bool(notify_follow)
    user.notify_feed = bool(notify_feed)
    if new_password_hash:
        user.password_hash = new_password_hash
    db.commit()
    _log.info("account settings updated user_id=%s", user.id)
    return templates.TemplateResponse(
        request, "dashboard/account_form.html",
        _ctx(user, db=db, errors=[], saved=True, values=values),
    )


# ============== Feed ==============

@router.get("/feed", response_class=HTMLResponse)
def feed(
    request: Request,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    following_ids = [
        row.following_id
        for row in db.query(Follow.following_id).filter(Follow.follower_id == user.id).all()
    ]
    feed_items = []
    if following_ids:
        rows = (
            db.query(Print, User)
            .join(User, Print.user_id == User.id)
            .filter(
                Print.user_id.in_(following_ids),
                Print.is_public == True,   # noqa: E712
                Print.queued == False,     # noqa: E712
            )
            .order_by(Print.created_at.desc())
            .limit(50)
            .all()
        )
        feed_items = [{"print": p, "user": u} for p, u in rows]
    return templates.TemplateResponse(
        request, "dashboard/feed.html",
        _ctx(user, db=db, section="feed", feed_items=feed_items),
    )


# ============== Account deletion ==============

@router.get("/account/delete", response_class=HTMLResponse)
def delete_account_confirm(
    request: Request,
    user: Optional[User] = Depends(get_current_user_web_optional),
):
    if (r := _require_user(user)) is not None:
        return r
    return templates.TemplateResponse(
        request, "dashboard/delete_account.html",
        {"current_user": user, "user": user},
    )


@router.post("/account/delete")
def delete_account(
    request: Request,
    confirm: str = Form(""),
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    if confirm.strip().upper() != "DELETE":
        return templates.TemplateResponse(
            request, "dashboard/delete_account.html",
            {"current_user": user, "user": user, "error": "Type DELETE to confirm."},
            status_code=422,
        )

    # Delete R2 photos (best-effort)
    prints = db.query(Print).filter(Print.user_id == user.id).all()
    for p in prints:
        if p.photo_url:
            delete_image(p.photo_url)
    if user.avatar_url:
        delete_image(user.avatar_url)

    # Delete all user data
    db.query(Print).filter(Print.user_id == user.id).delete()
    db.query(Filament).filter(Filament.user_id == user.id).delete()
    db.query(Printer).filter(Printer.user_id == user.id).delete()
    db.query(Follow).filter(
        (Follow.follower_id == user.id) | (Follow.following_id == user.id)
    ).delete(synchronize_session=False)
    db.delete(user)
    db.commit()

    response = RedirectResponse("/?deleted=1", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response
