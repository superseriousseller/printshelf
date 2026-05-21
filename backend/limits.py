"""Free-tier enforcement.

Centralized so the same upgrade-required response shape is returned everywhere.
Logs every cap-hit (Task #9) so we can decide when Stripe is worth building.
"""
import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import (
    FREE_TIER_FILAMENT_LIMIT,
    FREE_TIER_PRINT_LIMIT,
    Filament,
    Print,
    User,
)

logger = logging.getLogger(__name__)


def _is_pro(user: User) -> bool:
    return (user.tier or "free") == "pro"


def _raise_upgrade_required(resource: str, limit: int, current: int, user: User) -> None:
    logger.info(
        "cap_hit user_id=%s resource=%s limit=%s current=%s",
        user.id, resource, limit, current,
    )
    raise HTTPException(
        status_code=402,
        detail={
            "error": "upgrade_required",
            "resource": resource,
            "limit": limit,
            "current": current,
        },
    )


def enforce_print_limit(db: Session, user: User) -> None:
    if _is_pro(user):
        return
    current = db.query(Print).filter(Print.user_id == user.id).count()
    if current >= FREE_TIER_PRINT_LIMIT:
        _raise_upgrade_required("prints", FREE_TIER_PRINT_LIMIT, current, user)


def enforce_filament_limit(db: Session, user: User) -> None:
    if _is_pro(user):
        return
    current = db.query(Filament).filter(Filament.user_id == user.id).count()
    if current >= FREE_TIER_FILAMENT_LIMIT:
        _raise_upgrade_required("filaments", FREE_TIER_FILAMENT_LIMIT, current, user)
