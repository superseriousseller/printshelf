"""Photo + audio storage backend.

Two modes, picked by env vars:

  R2 mode (production)   — when R2_* env vars are set, uploads go to the
                           Cloudflare R2 bucket via boto3's S3 client.
                           Public URL is `{R2_PUBLIC_URL_BASE}/{filename}`.

  Local mode (dev)       — when R2 isn't configured, uploads land in
                           `<repo>/uploads/photos/` (or `uploads/audio/`) and
                           are served from `/uploads/photos/{filename}` (or
                           `/uploads/audio/{filename}`) by the FastAPI static
                           mounts in main.py.

Image pipeline (both modes):
  1. Validate as image via Pillow.
  2. Strip EXIF (removes GPS + camera metadata).
  3. Resize to max 1600px on the longest side, preserving aspect.
  4. Re-encode: JPEG q=85 for opaque images, PNG for transparent.
  5. Filename = SHA-256(processed bytes) + extension → deterministic dedup.

Audio pipeline (upload_audio): no processing here — the caller (currently
only ingest_instrument_audio.py) already normalized/encoded the bytes via
ffmpeg before calling this. Just a raw-bytes store with the same SHA-256
dedup. Deliberately no "kind" (printed/real) in the prefix or filename —
the Instruments Index blind A/B toggle depends on the URL itself not
leaking which clip is which.
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

MAX_AUDIO_UPLOAD_BYTES = 5 * 1024 * 1024  # 5MB — short clips, generous ceiling


class UploadError(Exception):
    """Raised for invalid uploads — message is safe to return to client."""


_R2_REQUIRED_ENV = (
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
    "R2_ENDPOINT",
    "R2_PUBLIC_URL_BASE",
)


def _r2_configured() -> bool:
    """All 5 R2 vars must be set — missing R2_PUBLIC_URL_BASE silently put
    objects in R2 with no way to serve them. Treat as all-or-nothing."""
    missing = [k for k in _R2_REQUIRED_ENV if not os.environ.get(k)]
    if missing and any(os.environ.get(k) for k in _R2_REQUIRED_ENV):
        # Partial config — log loudly so it's obvious in Railway logs.
        logger.warning("R2 partially configured; missing env vars: %s — falling back to local", missing)
    return not missing


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


def _local_audio_dir() -> str:
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(os.path.dirname(backend_dir), "uploads", "audio")
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
        # All 5 vars verified by _r2_configured(); safe to access directly.
        base = os.environ["R2_PUBLIC_URL_BASE"].rstrip("/")
        client = _get_r2_client()
        client.put_object(
            Bucket=os.environ["R2_BUCKET"],
            Key=filename,
            Body=processed,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )
        return f"{base}/{filename}"

    # Local fallback for dev
    local_dir = _local_uploads_dir()
    target = os.path.join(local_dir, filename)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as f:
        f.write(processed)
    return f"/uploads/photos/{filename}"


def upload_audio(raw: bytes, *, prefix: str = "instr-audio") -> str:
    """Store an already-encoded MP3 clip. Returns the public URL.

    No processing — callers must hand this finished bytes (see module
    docstring). `prefix` should be a generic bucket name shared by every
    clip kind (never "printed"/"real") so the URL alone can't answer a
    blind A/B guess.
    """
    if len(raw) > MAX_AUDIO_UPLOAD_BYTES:
        raise UploadError(f"File too large (max {MAX_AUDIO_UPLOAD_BYTES // 1024 // 1024}MB)")
    if len(raw) == 0:
        raise UploadError("Empty file")

    digest = hashlib.sha256(raw).hexdigest()
    filename = f"{prefix}/{digest[:2]}/{digest}.mp3"

    if _r2_configured():
        base = os.environ["R2_PUBLIC_URL_BASE"].rstrip("/")
        client = _get_r2_client()
        client.put_object(
            Bucket=os.environ["R2_BUCKET"],
            Key=filename,
            Body=raw,
            ContentType="audio/mpeg",
            CacheControl="public, max-age=31536000, immutable",
        )
        return f"{base}/{filename}"

    local_dir = _local_audio_dir()
    target = os.path.join(local_dir, filename)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as f:
        f.write(raw)
    return f"/uploads/audio/{filename}"


def delete_image(url: str) -> None:
    """Best-effort deletion of an image from R2. Logs errors but never raises."""
    if not url or not _r2_configured():
        return
    base = os.environ.get("R2_PUBLIC_URL_BASE", "").rstrip("/")
    if not base or not url.startswith(base + "/"):
        return
    key = url[len(base) + 1:]
    try:
        _get_r2_client().delete_object(Bucket=os.environ["R2_BUCKET"], Key=key)
    except Exception:
        logger.exception("Failed to delete R2 object %s", key)


def storage_mode() -> str:
    return "r2" if _r2_configured() else "local"
