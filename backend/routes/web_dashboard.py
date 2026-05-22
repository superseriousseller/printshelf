"""Web dashboard CRUD — server-rendered Jinja UI for printers, filaments, prints.

All endpoints require an authenticated session cookie. No JS framework;
forms POST → server redirects → page re-renders. Photo upload + URL import
are wired in subsequent tasks.
"""
import os
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import get_current_user_web_optional
from limits import enforce_filament_limit, enforce_print_limit
from models import (
    Filament,
    FilamentStatus,
    Print,
    PrintStatus,
    Printer,
    SourcePlatform,
    User,
    get_db,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_BACKEND_DIR, "templates"))


def _require_user(user: Optional[User]) -> Optional[RedirectResponse]:
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return None


def _ctx(user: User, **extra) -> dict:
    return {"current_user": user, "user": user, **extra}


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


def _normalize_hex(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    return v if v.startswith("#") else f"#{v}"


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
        _ctx(user, printers=printers),
    )


@router.get("/printers/new", response_class=HTMLResponse)
def new_printer(
    request: Request,
    user: Optional[User] = Depends(get_current_user_web_optional),
):
    if (r := _require_user(user)) is not None:
        return r
    return templates.TemplateResponse(
        request, "dashboard/printer_form.html",
        _ctx(user, printer=None, errors=[], values={}),
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
            _ctx(user, printer=None, errors=["Name is required."], values={"name": name, "brand": brand, "model": model}),
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
        _ctx(user, printer=p, errors=[], values={"name": p.name, "brand": p.brand or "", "model": p.model or ""}),
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
            _ctx(user, printer=p, errors=["Name is required."], values={"name": name, "brand": brand, "model": model}),
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
        _ctx(user, filaments=filaments, statuses=[s.value for s in FilamentStatus]),
    )


def _filament_form_ctx(user: User, filament: Optional[Filament], errors: list, values: dict) -> dict:
    return _ctx(
        user,
        filament=filament,
        errors=errors,
        values=values,
        statuses=[s.value for s in FilamentStatus],
    )


@router.get("/filaments/new", response_class=HTMLResponse)
def new_filament(
    request: Request,
    user: Optional[User] = Depends(get_current_user_web_optional),
):
    if (r := _require_user(user)) is not None:
        return r
    return templates.TemplateResponse(
        request, "dashboard/filament_form.html",
        _filament_form_ctx(user, None, [], {"diameter": "1.75", "status": "own"}),
    )


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
    notes: str = Form(""),
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    enforce_filament_limit(db, user)  # raises HTTPException 402 if over cap
    errors = []
    try:
        diameter_f = float(diameter or "1.75")
    except ValueError:
        diameter_f = 1.75
        errors.append("Diameter must be a number.")
    if status not in {s.value for s in FilamentStatus}:
        errors.append("Invalid status.")
    if not brand.strip() or not material.strip():
        errors.append("Brand and material are required.")
    if errors:
        return templates.TemplateResponse(
            request, "dashboard/filament_form.html",
            _filament_form_ctx(user, None, errors, {
                "brand": brand, "material": material, "color_name": color_name,
                "color_hex": color_hex, "diameter": diameter, "status": status,
                "source_url": source_url, "notes": notes,
            }),
            status_code=400,
        )
    f = Filament(
        user_id=user.id, brand=brand.strip(), material=material.strip(),
        color_name=color_name.strip() or None, color_hex=_normalize_hex(color_hex),
        diameter=diameter_f, status=status,
        source_url=source_url.strip() or None, notes=notes.strip() or None,
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
        _filament_form_ctx(user, f, [], {
            "brand": f.brand, "material": f.material,
            "color_name": f.color_name or "", "color_hex": f.color_hex or "",
            "diameter": str(f.diameter), "status": f.status,
            "source_url": f.source_url or "", "notes": f.notes or "",
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


# ============== Prints ==============

@router.get("/prints", response_class=HTMLResponse)
def list_prints(
    request: Request,
    queued: Optional[str] = None,
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
    rows = q.order_by(Print.created_at.desc()).all()
    # Build a lookup for printer + filament names to render in the list
    printer_names = {p.id: p.name for p in db.query(Printer).filter(Printer.user_id == user.id).all()}
    fil_meta = {f.id: f for f in db.query(Filament).filter(Filament.user_id == user.id).all()}
    return templates.TemplateResponse(
        request, "dashboard/prints_list.html",
        _ctx(user, prints=rows, queued_filter=queued_filter,
             printer_names=printer_names, fil_meta=fil_meta),
    )


def _print_form_ctx(user: User, db: Session, p: Optional[Print], errors: list, values: dict) -> dict:
    printers = db.query(Printer).filter(Printer.user_id == user.id).order_by(Printer.name).all()
    filaments = db.query(Filament).filter(Filament.user_id == user.id).order_by(Filament.brand, Filament.material).all()
    return _ctx(
        user, print_=p, errors=errors, values=values,
        printers=printers, filaments=filaments,
        platforms=[p.value for p in SourcePlatform],
        statuses=[s.value for s in PrintStatus],
    )


@router.get("/prints/new", response_class=HTMLResponse)
def new_print(
    request: Request,
    queued: Optional[str] = None,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    defaults = {
        "queued": "1" if queued == "true" else "",
        "status": "printed",
        "source_platform": "manual",
        "is_public": "1",
    }
    return templates.TemplateResponse(
        request, "dashboard/print_form.html",
        _print_form_ctx(user, db, None, [], defaults),
    )


@router.post("/prints")
def create_print(
    request: Request,
    title: str = Form(...),
    designer: str = Form(""),
    source_platform: str = Form("manual"),
    source_url: str = Form(""),
    thumbnail_url: str = Form(""),
    photo_url: str = Form(""),
    printer_id: str = Form(""),
    filament_ids: list[str] = Form(default=[]),
    status: str = Form("printed"),
    rating: str = Form(""),
    notes: str = Form(""),
    print_date: str = Form(""),
    queued: str = Form(""),
    is_public: str = Form(""),
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if (r := _require_user(user)) is not None:
        return r
    enforce_print_limit(db, user)
    errors = []
    if not title.strip():
        errors.append("Title is required.")
    if source_platform not in {p.value for p in SourcePlatform}:
        errors.append("Invalid source platform.")
    if status not in {s.value for s in PrintStatus}:
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

    if errors:
        values = {
            "title": title, "designer": designer, "source_platform": source_platform,
            "source_url": source_url, "thumbnail_url": thumbnail_url, "photo_url": photo_url,
            "printer_id": printer_id, "filament_ids": fil_ids, "status": status,
            "rating": rating, "notes": notes, "print_date": print_date,
            "queued": queued, "is_public": is_public,
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
        photo_url=photo_url.strip() or None,
        printer_id=printer_id_int,
        filament_ids=fil_ids,
        status=status, rating=rating_int,
        notes=notes.strip() or None,
        queued=bool(queued),
        is_public=bool(is_public),
        print_date=_parse_date(print_date),
    )
    db.add(p)
    db.commit()
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
        "status": p.status, "rating": str(p.rating) if p.rating else "",
        "notes": p.notes or "",
        "print_date": p.print_date.isoformat() if p.print_date else "",
        "queued": "1" if p.queued else "",
        "is_public": "1" if p.is_public else "",
    }
    return templates.TemplateResponse(
        request, "dashboard/print_form.html",
        _print_form_ctx(user, db, p, [], values),
    )


@router.post("/prints/{print_id}")
def update_print(
    request: Request,
    print_id: int,
    title: str = Form(...),
    designer: str = Form(""),
    source_platform: str = Form("manual"),
    source_url: str = Form(""),
    thumbnail_url: str = Form(""),
    photo_url: str = Form(""),
    printer_id: str = Form(""),
    filament_ids: list[str] = Form(default=[]),
    status: str = Form("printed"),
    rating: str = Form(""),
    notes: str = Form(""),
    print_date: str = Form(""),
    queued: str = Form(""),
    is_public: str = Form(""),
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

    p.title = title.strip()
    p.designer = designer.strip() or None
    if source_platform in {sp.value for sp in SourcePlatform}:
        p.source_platform = source_platform
    p.source_url = source_url.strip() or None
    p.thumbnail_url = thumbnail_url.strip() or None
    p.photo_url = photo_url.strip() or None
    p.printer_id = printer_id_int
    p.filament_ids = fil_ids
    if status in {s.value for s in PrintStatus}:
        p.status = status
    p.rating = rating_int
    p.notes = notes.strip() or None
    p.print_date = _parse_date(print_date)
    p.queued = bool(queued)
    p.is_public = bool(is_public)
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
