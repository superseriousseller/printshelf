"""Photo storage backend.

Two modes, picked by env vars:

  R2 mode (production)   — when R2_* env vars are set, uploads go to the
                           Cloudflare R2 bucket via boto3's S3 client.
                           Public URL is `{R2_PUBLIC_URL_BASE}/{filename}`.

  Local mode (dev)       — when R2 isn't configured, uploads land in
                           `<repo>/uploads/photos/` and are served from
                           `/uploads/photos/{filename}` by the FastAPI
                           static mount in main.py.

Image pipeline (both modes):
  1. Validate as image via Pillow.
  2. Strip EXIF (removes GPS + camera metadata).
  3. Resize to max 1600px on the longest side, preserving aspect.
  4. Re-encode: JPEG q=85 for opaque images, PNG for transparent.
  5. Filename = SHA-256(processed bytes) + extension → deterministic dedup.
"""
import hashlib
import io
import logging
import os
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB raw upload cap
MAX_DIMENSION = 1600                  # longest-side cap after resize
JPEG_QUALITY = 85
ACCEPTED_INPUT_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF"}


class UploadError(Exception):
    """Raised for invalid uploads — message is safe to return to client."""


def _r2_configured() -> bool:
    return all(
        os.environ.get(k)
        for k in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_ENDPOINT")
    )


_r2_client = None


def _get_r2_client():
    global _r2_client
    if _r2_client is not None:
        return _r2_client
    import boto3
    from botocore.config import Config
    _r2_client = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        # R2 ignores region but boto3 requires one.
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )
    return _r2_client


def _process_image(raw: bytes) -> tuple[bytes, str]:
    """Validate, sanitize, and re-encode the image.

    Returns (processed_bytes, file_extension).
    Raises UploadError on invalid input.
    """
    if len(raw) > MAX_UPLOAD_BYTES:
        raise UploadError(f"File too large (max {MAX_UPLOAD_BYTES // 1024 // 1024}MB)")
    if len(raw) == 0:
        raise UploadError("Empty file")

    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()  # cheap structural check; consumes the image
    except (UnidentifiedImageError, OSError) as e:
        raise UploadError("Not a valid image") from e

    if img.format not in ACCEPTED_INPUT_FORMATS:
        raise UploadError(f"Unsupported image format: {img.format}")

    # Re-open (verify() consumes); EXIF transpose to honor camera orientation.
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)

    # Decide output format: PNG only if image has actual transparency, else JPEG.
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    out_format = "PNG" if has_alpha else "JPEG"
    ext = ".png" if out_format == "PNG" else ".jpg"

    # Convert mode for JPEG output
    if out_format == "JPEG" and img.mode != "RGB":
        img = img.convert("RGB")

    # Resize to max 1600px on longest side (preserves aspect)
    if max(img.size) > MAX_DIMENSION:
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)

    # Re-encode without EXIF
    buf = io.BytesIO()
    if out_format == "JPEG":
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    else:
        img.save(buf, format="PNG", optimize=True)

    return buf.getvalue(), ext


def _local_uploads_dir() -> str:
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(os.path.dirname(backend_dir), "uploads", "photos")
    os.makedirs(out, exist_ok=True)
    return out


def upload_image(raw: bytes, *, prefix: str = "p") -> str:
    """Process and store an image. Returns the public URL.

    `prefix` distinguishes subdirectories (e.g. "p" for print photos,
    "a" for avatars) so we can later evolve storage policy per type.
    """
    processed, ext = _process_image(raw)
    digest = hashlib.sha256(processed).hexdigest()
    filename = f"{prefix}/{digest[:2]}/{digest}{ext}"
    content_type = "image/jpeg" if ext == ".jpg" else "image/png"

    if _r2_configured():
        client = _get_r2_client()
        bucket = os.environ["R2_BUCKET"]
        client.put_object(
            Bucket=bucket,
            Key=filename,
            Body=processed,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )
        base = os.environ.get("R2_PUBLIC_URL_BASE", "").rstrip("/")
        if not base:
            raise UploadError("R2_PUBLIC_URL_BASE not configured")
        return f"{base}/{filename}"

    # Local fallback for dev
    local_dir = _local_uploads_dir()
    target = os.path.join(local_dir, filename)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as f:
        f.write(processed)
    return f"/uploads/photos/{filename}"


def storage_mode() -> str:
    return "r2" if _r2_configured() else "local"
