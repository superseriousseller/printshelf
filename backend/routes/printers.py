"""Printers CRUD.

No tier limits on printers — most hobbyists have 1-3, power users 5-6.
Capping that would be hostile.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user
from models import Printer, User, get_db

router = APIRouter(prefix="/api/printers", tags=["printers"])


class PrinterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    brand: Optional[str] = Field(default=None, max_length=50)
    model: Optional[str] = Field(default=None, max_length=100)


class PrinterUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    brand: Optional[str] = Field(default=None, max_length=50)
    model: Optional[str] = Field(default=None, max_length=100)


def _own_or_404(db: Session, user: User, printer_id: int) -> Printer:
    p = db.query(Printer).filter(Printer.id == printer_id, Printer.user_id == user.id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Printer not found")
    return p


@router.get("")
def list_printers(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    q = db.query(Printer).filter(Printer.user_id == user.id).order_by(Printer.created_at.desc())
    total = q.count()
    items = q.offset(offset).limit(limit).all()
    return {"items": [p.to_dict() for p in items], "total": total, "limit": limit, "offset": offset}


@router.post("", status_code=201)
def create_printer(
    body: PrinterCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    p = Printer(user_id=user.id, name=body.name.strip(), brand=body.brand, model=body.model)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p.to_dict()


@router.get("/{printer_id}")
def get_printer(
    printer_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _own_or_404(db, user, printer_id).to_dict()


@router.patch("/{printer_id}")
def update_printer(
    printer_id: int,
    body: PrinterUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    p = _own_or_404(db, user, printer_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(p, k, v.strip() if isinstance(v, str) else v)
    db.commit()
    db.refresh(p)
    return p.to_dict()


@router.delete("/{printer_id}", status_code=204)
def delete_printer(
    printer_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    p = _own_or_404(db, user, printer_id)
    db.delete(p)
    db.commit()
