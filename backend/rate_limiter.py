"""Simple in-memory per-IP rate limiter. No external deps, no Redis."""
import time
from collections import defaultdict
from threading import Lock

from fastapi import Request

_store: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def client_ip(request: Request) -> str:
    """Real client IP — reads X-Forwarded-For first (Railway proxy)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check(ip: str, action: str, max_attempts: int = 5, window_secs: int = 60) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = time.monotonic()
    key = f"{action}:{ip}"
    with _lock:
        recent = [t for t in _store[key] if now - t < window_secs]
        if len(recent) >= max_attempts:
            _store[key] = recent
            return False
        recent.append(now)
        _store[key] = recent
        return True
