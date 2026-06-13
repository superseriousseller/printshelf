"""Filaments CRUD + status updates.

Free tier: 10 filaments. Status enforced via the FilamentStatus enum at the
DB layer (column is a String for migration flexibility; we validate here).
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user
from filament_import_service import extract as extract_filament_url
from import_service import ImportError_
from limits import enforce_filament_limit
from models import Filament, FilamentStatus, User, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/filaments", tags=["filaments"])

VALID_STATUSES = {s.value for s in FilamentStatus}


def _validate_status(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {sorted(VALID_STATUSES)}",
        )
    return value


VALID_HEX_SOURCES = {"scraped", "guessed"}


class FilamentCreate(BaseModel):
    brand: str = Field(min_length=1, max_length=100)
    material: str = Field(min_length=1, max_length=50)
    color_name: Optional[str] = Field(default=None, max_length=100)
    color_hex: Optional[str] = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    color_hex_source: Optional[str] = Field(default=None, max_length=10)
    diameter: float = 1.75
    finish: Optional[str] = Field(default=None, max_length=100)
    status: str = "own"
    source_url: Optional[str] = Field(default=None, max_length=1000)
    price_at_save: Optional[float] = None
    notes: Optional[str] = None


class FilamentUpdate(BaseModel):
    brand: Optional[str] = Field(default=None, max_length=100)
    material: Optional[str] = Field(default=None, max_length=50)
    color_name: Optional[str] = Field(default=None, max_length=100)
    color_hex: Optional[str] = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    color_hex_source: Optional[str] = Field(default=None, max_length=10)
    diameter: Optional[float] = None
    finish: Optional[str] = Field(default=None, max_length=100)
    status: Optional[str] = None
    source_url: Optional[str] = Field(default=None, max_length=1000)
    price_at_save: Optional[float] = None
    notes: Optional[str] = None


def _own_or_404(db: Session, user: User, filament_id: int) -> Filament:
    f = db.query(Filament).filter(Filament.id == filament_id, Filament.user_id == user.id).first()
    if f is None:
        raise HTTPException(status_code=404, detail="Filament not found")
    return f


def _normalize_hex(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value if value.startswith("#") else f"#{value}"


@router.get("")
def list_filaments(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    material: Optional[str] = None,
    q: Optional[str] = Query(default=None, description="Search across brand, material, color name, and finish"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    query = db.query(Filament).filter(Filament.user_id == user.id)
    if status_filter:
        _validate_status(status_filter)
        query = query.filter(Filament.status == status_filter)
    if material:
        query = query.filter(Filament.material == material)
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            Filament.brand.ilike(term)
            | Filament.material.ilike(term)
            | Filament.color_name.ilike(term)
            | Filament.finish.ilike(term)
        )
    query = query.order_by(Filament.created_at.desc())
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return {"items": [f.to_dict() for f in items], "total": total, "limit": limit, "offset": offset}


@router.post("", status_code=201)
def create_filament(
    body: FilamentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    enforce_filament_limit(db, user)
    _validate_status(body.status)
    f = Filament(
        user_id=user.id,
        brand=body.brand.strip(),
        material=body.material.strip(),
        color_name=body.color_name,
        color_hex=_normalize_hex(body.color_hex),
        color_hex_source=body.color_hex_source if body.color_hex_source in VALID_HEX_SOURCES else None,
        diameter=body.diameter,
        finish=body.finish,
        status=body.status,
        source_url=body.source_url,
        price_at_save=body.price_at_save,
        notes=body.notes,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f.to_dict()


@router.get("/{filament_id}")
def get_filament(
    filament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _own_or_404(db, user, filament_id).to_dict()


@router.patch("/{filament_id}")
def update_filament(
    filament_id: int,
    body: FilamentUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    f = _own_or_404(db, user, filament_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data:
        _validate_status(data["status"])
    if "color_hex" in data:
        data["color_hex"] = _normalize_hex(data["color_hex"])
    for k, v in data.items():
        if isinstance(v, str):
            v = v.strip()
        setattr(f, k, v)
    db.commit()
    db.refresh(f)
    return f.to_dict()


@router.delete("/{filament_id}", status_code=204)
def delete_filament(
    filament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    f = _own_or_404(db, user, filament_id)
    db.delete(f)
    db.commit()


class FilamentImportRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


@router.post("/import-url")
def import_filament_url(
    body: FilamentImportRequest,
    user: User = Depends(get_current_user),  # noqa: ARG001 — auth required, user unused
) -> dict:
    """Scrape a filament product page and return structured metadata.

    Used by the Chrome extension when DOM extraction misses fields, and
    available as a public JSON API. No caching for v1 — filament URL
    scrapes are infrequent and the model-page ImportCache table has a
    different shape.
    """
    url = body.url.strip()
    try:
        result = extract_filament_url(url)
    except ImportError_ as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("filament import-url failed for %s", url)
        raise HTTPException(status_code=500, detail="Import failed")
    return {
        "store": result.get("store"),
        "brand": result.get("brand"),
        "material": result.get("material"),
        "colorName": result.get("color_name"),
        "price": result.get("price"),
        "sourceUrl": result.get("source_url"),
        "thumbnailUrl": result.get("thumbnail_url"),
        "title": result.get("title"),
        "partial": bool(result.get("partial")),
    }
