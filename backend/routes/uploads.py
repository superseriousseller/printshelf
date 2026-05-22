"""Photo upload endpoint.

POST /api/uploads/photo — multipart upload. Accepts JWT or per-user
API key on the Bearer header (same auth path as other API endpoints).
Returns {url} pointing at the public CDN URL.
"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from auth import get_current_user
from models import User, get_db
from storage import MAX_UPLOAD_BYTES, UploadError, storage_mode, upload_image

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
logger = logging.getLogger(__name__)


@router.post("/photo")
async def upload_photo(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),  # noqa: ARG001 — keep DI signature uniform
) -> dict:
    # Read with a hard cap so a 4GB upload doesn't OOM the worker.
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_UPLOAD_BYTES // 1024 // 1024}MB)",
        )

    try:
        url = upload_image(raw, prefix="p")
    except UploadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("upload failed for user %s", user.id)
        raise HTTPException(status_code=500, detail="Upload failed")

    return {"url": url, "storage": storage_mode()}
