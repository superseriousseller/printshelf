"""URL import endpoint.

POST /api/import-url with { url } → returns model metadata extracted
from the source platform's OG tags. Caches results so the same URL
never hits the source twice. JWT or API-key auth (used by the Chrome
extension and the web dashboard's import button).
"""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user
from import_service import ImportError_, extract
from models import ImportCache, User, get_db

router = APIRouter(prefix="/api", tags=["imports"])
logger = logging.getLogger(__name__)

CACHE_TTL = timedelta(days=14)


class ImportRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


def _wire_response(result: dict, cached: bool) -> dict:
    """Normalize both cached and fresh paths to the camelCase wire format
    used by every other PrintShelf API endpoint."""
    return {
        "platform": result.get("platform"),
        "title": result.get("title"),
        "designer": result.get("designer"),
        "thumbnailUrl": result.get("thumbnail_url"),
        "sourceUrl": result.get("source_url"),
        "cached": cached,
    }


@router.post("/import-url")
def import_url(
    body: ImportRequest,
    user: User = Depends(get_current_user),  # noqa: ARG001 — auth required, user unused
    db: Session = Depends(get_db),
) -> dict:
    url = body.url.strip()

    # Cache hit — return what we extracted last time
    row = db.query(ImportCache).filter(ImportCache.source_url == url).first()
    if row and (datetime.utcnow() - row.fetched_at) < CACHE_TTL:
        return _wire_response({
            "platform": row.platform,
            "title": row.title,
            "designer": row.designer,
            "thumbnail_url": row.thumbnail_url,
            "source_url": row.source_url,
        }, cached=True)

    try:
        result = extract(url)
    except ImportError_ as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("import failed for %s", url)
        raise HTTPException(status_code=500, detail="Import failed")

    # Upsert into cache
    if row is None:
        row = ImportCache(source_url=url)
        db.add(row)
    row.platform = result["platform"]
    row.title = result["title"]
    row.designer = result.get("designer")
    row.thumbnail_url = result.get("thumbnail_url")
    row.raw_metadata = result
    row.fetched_at = datetime.utcnow()
    db.commit()

    return _wire_response(result, cached=False)
