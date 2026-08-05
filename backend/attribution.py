"""Silent, invisible signup attribution — no user-facing form, zero UX change.

Referer + UTM params + landing path only exist on the request that first
brings a visitor to the site; the user row isn't created until they submit
signup (password) or complete the Google OAuth callback, possibly minutes,
hours, or days later on a different page entirely. So we capture once, on
the first server-rendered page view of the visit, into a short-lived
HttpOnly cookie (first-touch wins — never overwritten by later pages), and
read it back whenever a user row is actually created.
"""
import os
from urllib.parse import parse_qsl, urlencode

CAPTURE_COOKIE = "signup_attrib"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days — matches the session cookie's window
_PROD = os.environ.get("APP_ENV", "development") in {"production", "staging"}

_UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")

# Skip capture on asset/technical/API paths — these aren't landing pages a real
# visitor "arrived" on, and capturing them would pollute attribution with junk
# (e.g. the Chrome extension's own API polling, or a service-worker fetch).
_SKIP_PREFIXES = ("/static/", "/api/", "/admin")
_SKIP_EXACT = {"/sw.js", "/offline", "/favicon.ico", "/robots.txt", "/sitemap.xml", "/manifest.webmanifest"}


def _should_capture(path: str) -> bool:
    if path in _SKIP_EXACT:
        return False
    return not path.startswith(_SKIP_PREFIXES)


def _capture_from_request(request) -> dict:
    referrer = (request.headers.get("referer") or "")[:500]
    qp = request.query_params
    data = {
        "referrer": referrer,
        "landing_path": str(request.url.path)[:255],
        "querystring": str(request.url.query)[:500],
    }
    for key in _UTM_KEYS:
        data[key] = (qp.get(key) or "")[:200]
    return data


async def capture_attribution_middleware(request, call_next):
    """Sets the first-touch attribution cookie on a visitor's first GET to a
    real page, if it isn't already set. Never overwrites an existing one."""
    response = await call_next(request)
    if (
        request.method == "GET"
        and CAPTURE_COOKIE not in request.cookies
        and _should_capture(request.url.path)
    ):
        data = _capture_from_request(request)
        response.set_cookie(
            CAPTURE_COOKIE, urlencode(data),
            max_age=_COOKIE_MAX_AGE, httponly=True, secure=_PROD, samesite="lax", path="/",
        )
    return response


def read_attribution(request) -> dict:
    """Decode the capture cookie (if present) into the User-column kwargs for
    create_user()/the Google new-account path. Missing/malformed → all-None,
    never raises — direct traffic and pre-existing cookies are both fine."""
    raw = request.cookies.get(CAPTURE_COOKIE, "")
    if not raw:
        return {}
    try:
        parsed = dict(parse_qsl(raw, keep_blank_values=True))
    except Exception:
        return {}
    out = {
        "signup_referrer": parsed.get("referrer") or None,
        "signup_landing_path": parsed.get("landing_path") or None,
        "signup_landing_querystring": parsed.get("querystring") or None,
    }
    for key in _UTM_KEYS:
        out[key] = parsed.get(key) or None
    return out
