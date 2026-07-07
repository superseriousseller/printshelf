"""Prints CRUD + queue workflow.

The core log entry. Supports:
  * Direct create as a finished print (queued=false, default)
  * Add-to-queue create (POST /api/prints/queue, queued=true)
  * Queue → printed transition (POST /api/prints/{id}/printed)
  * Multi-material via filament_ids JSON array

Free-tier cap (50) counts ALL prints — queued + completed — so a user
can't game the limit by parking everything in the queue.
"""
import logging
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from affiliate import is_allowed_link_domain
from auth import get_current_user
from limits import enforce_filament_limit, enforce_print_limit
from models import (
    Filament,
    Print,
    PrintLink,
    PrintStatus,
    Printer,
    SourcePlatform,
    User,
    VALID_PRINT_CATEGORIES,
    get_db,
)

router = APIRouter(prefix="/api/prints", tags=["prints"])
logger = logging.getLogger(__name__)

VALID_PRINT_STATUSES = {s.value for s in PrintStatus}
VALID_PLATFORMS = {p.value for p in SourcePlatform}


class PrintLinkItem(BaseModel):
    label: str = Field(max_length=200)
    url: str = Field(max_length=2000)


class PrintCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    designer: Optional[str] = Field(default=None, max_length=200)
    source_platform: str = "manual"
    source_url: Optional[str] = Field(default=None, max_length=1000)
    thumbnail_url: Optional[str] = Field(default=None, max_length=1000)
    photo_url: Optional[str] = Field(default=None, max_length=1000)
    printer_id: Optional[int] = None
    filament_ids: List[int] = Field(default_factory=list)
    status: str = "printed"
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    notes: Optional[str] = None
    queued: bool = False
    is_public: bool = True
    print_date: Optional[date] = None
    video_url: Optional[str] = Field(default=None, max_length=1000)
    links: List[PrintLinkItem] = Field(default_factory=list)
    category: Optional[str] = None
    layer_height: Optional[float] = Field(default=None, ge=0, le=2)
    infill_pct: Optional[int] = Field(default=None, ge=0, le=100)
    supports: Optional[bool] = None
    print_time_mins: Optional[int] = Field(default=None, ge=0)
    filament_used_g: Optional[float] = Field(default=None, ge=0)


class PrintUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    designer: Optional[str] = Field(default=None, max_length=200)
    source_platform: Optional[str] = None
    source_url: Optional[str] = Field(default=None, max_length=1000)
    thumbnail_url: Optional[str] = Field(default=None, max_length=1000)
    photo_url: Optional[str] = Field(default=None, max_length=1000)
    printer_id: Optional[int] = None
    filament_ids: Optional[List[int]] = None
    status: Optional[str] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    notes: Optional[str] = None
    queued: Optional[bool] = None
    is_public: Optional[bool] = None
    print_date: Optional[date] = None
    video_url: Optional[str] = Field(default=None, max_length=1000)
    links: Optional[List[PrintLinkItem]] = None
    focal_x: Optional[float] = Field(default=None, ge=0, le=100)
    focal_y: Optional[float] = Field(default=None, ge=0, le=100)
    category: Optional[str] = None


def _save_links(db: Session, print_id: int, user_id: int, links: List[PrintLinkItem]) -> None:
    db.query(PrintLink).filter(PrintLink.print_id == print_id).delete()
    for i, lk in enumerate(links[:5]):
        url = lk.url.strip()
        if not is_allowed_link_domain(url):
            raise HTTPException(
                status_code=400,
                detail=f"Link URL not from a supported store: {url}. "
                       "Supported: Amazon, Bambu Lab, Polymaker, Anycubic, MatterHackers, SUNLU, FlashForge.",
            )
        db.add(PrintLink(print_id=print_id, user_id=user_id, label=lk.label.strip(), url=url, sort_order=i))
    db.commit()


def _own_or_404(db: Session, user: User, print_id: int) -> Print:
    p = db.query(Print).filter(Print.id == print_id, Print.user_id == user.id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Print not found")
    return p


def _validate_refs(
    db: Session,
    user: User,
    printer_id: Optional[int],
    filament_ids: Optional[List[int]],
) -> None:
    """Ensure printer / filaments referenced actually belong to this user."""
    if printer_id is not None:
        owned = db.query(Printer.id).filter(
            Printer.id == printer_id, Printer.user_id == user.id
        ).first()
        if owned is None:
            raise HTTPException(status_code=400, detail=f"Printer {printer_id} not owned by user")
    if filament_ids:
        rows = db.query(Filament.id).filter(
            Filament.user_id == user.id, Filament.id.in_(filament_ids)
        ).all()
        owned_ids = {r[0] for r in rows}
        missing = [fid for fid in filament_ids if fid not in owned_ids]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Filaments not owned by user: {missing}",
            )


def _validate_enums(status: Optional[str], platform: Optional[str], category: Optional[str] = None) -> None:
    if status is not None and status not in VALID_PRINT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {sorted(VALID_PRINT_STATUSES)}",
        )
    if platform is not None and platform not in VALID_PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source_platform. Must be one of: {sorted(VALID_PLATFORMS)}",
        )
    if category is not None and category not in VALID_PRINT_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {sorted(VALID_PRINT_CATEGORIES)}",
        )


def _create_print(db: Session, user: User, body: PrintCreate, *, force_queued: Optional[bool] = None) -> Print:
    enforce_print_limit(db, user)
    _validate_enums(body.status, body.source_platform, body.category)
    _validate_refs(db, user, body.printer_id, body.filament_ids)

    queued = body.queued if force_queued is None else force_queued
    p = Print(
        user_id=user.id,
        title=body.title.strip(),
        designer=body.designer,
        source_platform=body.source_platform,
        source_url=body.source_url,
        thumbnail_url=body.thumbnail_url,
        photo_url=body.photo_url,
        printer_id=body.printer_id,
        filament_ids=body.filament_ids or [],
        status=body.status,
        rating=body.rating,
        notes=body.notes,
        queued=queued,
        is_public=body.is_public,
        print_date=body.print_date,
        video_url=body.video_url,
        category=body.category,
        layer_height=body.layer_height,
        infill_pct=body.infill_pct,
        supports=body.supports,
        print_time_mins=body.print_time_mins,
        filament_used_g=body.filament_used_g,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    if body.links:
        _save_links(db, p.id, user.id, body.links)
    return p


@router.get("")
def list_prints(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    queued: Optional[bool] = None,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    printer_id: Optional[int] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    q = db.query(Print).filter(Print.user_id == user.id)
    if queued is not None:
        q = q.filter(Print.queued == queued)
    if status_filter:
        _validate_enums(status_filter, None)
        q = q.filter(Print.status == status_filter)
    if printer_id is not None:
        q = q.filter(Print.printer_id == printer_id)
    q = q.order_by(Print.created_at.desc())
    total = q.count()
    items = q.offset(offset).limit(limit).all()
    return {"items": [p.to_dict() for p in items], "total": total, "limit": limit, "offset": offset}


@router.post("", status_code=201)
def create_print(
    body: PrintCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    p = _create_print(db, user, body)
    return p.to_dict()


@router.post("/queue", status_code=201)
def queue_print(
    body: PrintCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Convenience endpoint used by the Chrome extension: forces queued=true."""
    p = _create_print(db, user, body, force_queued=True)
    return p.to_dict()


_PRINTER_BRANDS = [
    "Bambu Lab", "Bambulab", "Bambu", "Prusa", "Creality", "Anycubic", "Elegoo",
    "Voron", "Sovol", "FlashForge", "Ultimaker", "Raise3D", "Qidi", "Snapmaker",
    "Artillery", "Kingroon", "Sidewinder",
]


def _split_printer_name(name: str):
    """Best-effort split of a printer string into (brand, model). canonical_brand
    (via the Printer.brand validator) normalizes the brand on write."""
    low = name.lower()
    for b in _PRINTER_BRANDS:
        if low.startswith(b.lower()):
            model = name[len(b):].strip(" -_") or None
            return b, model
    return None, name


class IngestFilament(BaseModel):
    material: str = Field(min_length=1, max_length=50)
    color_name: Optional[str] = Field(default=None, max_length=100)
    color_hex: Optional[str] = Field(default=None, max_length=7)
    brand: Optional[str] = Field(default=None, max_length=100)
    finish: Optional[str] = Field(default=None, max_length=100)


class PrintIngest(BaseModel):
    """Lenient slicer-friendly intake: descriptors instead of DB ids. The server
    matches printer + filaments to the user's library, creating any that are new."""
    title: str = Field(min_length=1, max_length=300)
    printer: Optional[str] = Field(default=None, max_length=150)
    filaments: List[IngestFilament] = Field(default_factory=list)
    layer_height: Optional[float] = Field(default=None, ge=0, le=2)
    infill_pct: Optional[int] = Field(default=None, ge=0, le=100)
    supports: Optional[bool] = None
    print_time_mins: Optional[int] = Field(default=None, ge=0)
    filament_used_g: Optional[float] = Field(default=None, ge=0)
    status: str = "printed"
    queued: bool = False
    is_public: bool = True
    notes: Optional[str] = Field(default=None, max_length=5000)
    source_url: Optional[str] = Field(default=None, max_length=1000)
    photo_url: Optional[str] = Field(default=None, max_length=1000)


def _resolve_printer(db: Session, user: User, printer_str: Optional[str]):
    name = (printer_str or "").strip()
    if not name:
        return None, None
    for pr in db.query(Printer).filter(Printer.user_id == user.id).all():
        combo = " ".join(x for x in [pr.brand, pr.model] if x).strip().lower()
        candidates = {(pr.name or "").lower(), (pr.model or "").lower(), combo}
        if name.lower() in candidates:
            return pr.id, None
    brand, model = _split_printer_name(name)
    pr = Printer(user_id=user.id, name=name, brand=brand, model=model)
    db.add(pr)
    db.commit()
    db.refresh(pr)
    return pr.id, {"type": "printer", "id": pr.id, "name": pr.name}


def _resolve_filament(db: Session, user: User, desc: "IngestFilament", warnings: list):
    mat = desc.material.strip()
    hexv = (desc.color_hex or "").strip() or None
    cname = (desc.color_name or "").strip() or None
    owned = db.query(Filament).filter(Filament.user_id == user.id).all()
    same_mat = [f for f in owned if (f.material or "").lower() == mat.lower()]
    for f in same_mat:
        if hexv and f.color_hex and f.color_hex.lower() == hexv.lower():
            return f.id, None
        if cname and f.color_name and f.color_name.lower() == cname.lower():
            return f.id, None
    # No color signal -> match on material alone rather than spawn a duplicate spool.
    if not hexv and not cname and same_mat:
        return same_mat[0].id, None
    try:
        enforce_filament_limit(db, user)
    except HTTPException:
        warnings.append(
            f"Filament '{mat} {cname or hexv or ''}'".strip()
            + " not created — free-tier filament limit reached."
        )
        return None, None
    f = Filament(
        user_id=user.id, brand=(desc.brand or "Generic"), material=mat,
        color_name=cname, color_hex=hexv, finish=(desc.finish or None), status="own",
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f.id, {"type": "filament", "id": f.id, "label": f"{f.brand} {f.material}"}


@router.post("/ingest", status_code=201)
def ingest_print(
    body: PrintIngest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Slicer post-processing intake. Match-or-create printer + filaments from
    descriptors, then log the print (source_platform='slicer')."""
    warnings: list = []
    created: list = []
    printer_id, pcreated = _resolve_printer(db, user, body.printer)
    if pcreated:
        created.append(pcreated)
    fil_ids: List[int] = []
    for desc in body.filaments:
        fid, fcreated = _resolve_filament(db, user, desc, warnings)
        if fid is not None:
            if fid not in fil_ids:
                fil_ids.append(fid)
            if fcreated:
                created.append(fcreated)
    title = body.title
    designer = None
    thumbnail_url = None
    if body.source_url:
        try:
            from import_service import detect_platform as _detect, extract as _extract
            if _detect(body.source_url) != "manual":
                meta = _extract(body.source_url)
                if meta.get("title"):
                    title = meta["title"]
                designer = meta.get("designer")
                thumbnail_url = meta.get("thumbnail_url")
                logger.info("ingest enriched from %s: title=%r designer=%r",
                            body.source_url, title, designer)
        except Exception:
            logger.info("ingest source enrich failed for %s", body.source_url)

    pc_body = PrintCreate(
        title=title,
        designer=designer,
        thumbnail_url=thumbnail_url,
        source_platform="slicer",
        source_url=body.source_url,
        photo_url=body.photo_url,
        printer_id=printer_id,
        filament_ids=fil_ids,
        status=body.status,
        notes=body.notes,
        queued=body.queued,
        is_public=body.is_public,
        layer_height=body.layer_height,
        infill_pct=body.infill_pct,
        supports=body.supports,
        print_time_mins=body.print_time_mins,
        filament_used_g=body.filament_used_g,
    )
    p = _create_print(db, user, pc_body)
    return {"print": p.to_dict(), "created": created, "warnings": warnings}


@router.get("/{print_id}")
def get_print(
    print_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _own_or_404(db, user, print_id).to_dict()


@router.patch("/{print_id}")
def update_print(
    print_id: int,
    body: PrintUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    p = _own_or_404(db, user, print_id)
    data = body.model_dump(exclude_unset=True)
    links = data.pop("links", None)
    _validate_enums(data.get("status"), data.get("source_platform"), data.get("category"))
    _validate_refs(db, user, data.get("printer_id"), data.get("filament_ids"))
    for k, v in data.items():
        if isinstance(v, str):
            v = v.strip()
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    if links is not None:
        _save_links(db, p.id, user.id, [PrintLinkItem(**lk) for lk in links])
    return p.to_dict()


@router.post("/{print_id}/printed")
def mark_printed(
    print_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Move a queued print to printed status. Idempotent."""
    p = _own_or_404(db, user, print_id)
    p.queued = False
    p.status = "printed"
    if p.print_date is None:
        p.print_date = date.today()
    db.commit()
    db.refresh(p)
    return p.to_dict()


@router.delete("/{print_id}", status_code=204)
def delete_print(
    print_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    p = _own_or_404(db, user, print_id)
    db.delete(p)
    db.commit()
