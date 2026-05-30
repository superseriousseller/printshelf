"""Simple in-memory per-IP rate limiter. No external deps, no Redis."""
import time
from collections import defaultdict
from threading import Lock

_store: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


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
