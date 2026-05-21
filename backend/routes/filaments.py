"""Filaments CRUD + status updates.

Free tier: 10 filaments. Status enforced via the FilamentStatus enum at the
DB layer (column is a String for migration flexibility; we validate here).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user
from limits import enforce_filament_limit
from models import Filament, FilamentStatus, User, get_db

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


class FilamentCreate(BaseModel):
    brand: str = Field(min_length=1, max_length=100)
    material: str = Field(min_length=1, max_length=50)
    color_name: Optional[str] = Field(default=None, max_length=100)
    color_hex: Optional[str] = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    diameter: float = 1.75
    status: str = "own"
    source_url: Optional[str] = Field(default=None, max_length=1000)
    price_at_save: Optional[float] = None
    notes: Optional[str] = None


class FilamentUpdate(BaseModel):
    brand: Optional[str] = Field(default=None, max_length=100)
    material: Optional[str] = Field(default=None, max_length=50)
    color_name: Optional[str] = Field(default=None, max_length=100)
    color_hex: Optional[str] = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    diameter: Optional[float] = None
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
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    q = db.query(Filament).filter(Filament.user_id == user.id)
    if status_filter:
        _validate_status(status_filter)
        q = q.filter(Filament.status == status_filter)
    if material:
        q = q.filter(Filament.material == material)
    q = q.order_by(Filament.created_at.desc())
    total = q.count()
    items = q.offset(offset).limit(limit).all()
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
        diameter=body.diameter,
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
