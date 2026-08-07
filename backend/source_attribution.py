"""Source attribution — records WHICH client created a row.

This is a different axis from `Print.source_platform` (which records where the
*model/content* came from — makerworld/printables/etc). `created_via` records
which PrintShelf *client* made the write, so we can see what people actually use
and put effort/marketing where it counts.

Resolution (see `resolve_created_via`):
  1. First-party clients declare themselves with the header
     `X-PrintShelf-Client: <web|extension|shortcut|slicer>`. If present and
     recognized, that wins.
  2. Otherwise infer from auth style: a Bearer/JWT request with no recognized
     client header is an external API consumer  -> "api".
  3. A cookie-session request (the dashboard) with no header -> "web".

Fixed-purpose endpoints (slicer ingest, the iOS Shortcut /share flow) may pass
an explicit literal instead of using the header.
"""
from fastapi import Request

# Canonical client values. Keep in sync with models' created_via comment and the
# admin "By source" breakdown.
WEB = "web"
EXTENSION = "extension"
SHORTCUT = "shortcut"
SLICER = "slicer"
API = "api"
SEED = "seed"
UNKNOWN = "unknown"

# Values a first-party client is allowed to declare via the header. "api"/"seed"/
# "unknown" are assigned server-side, never trusted from a client header.
_DECLARABLE = {WEB, EXTENSION, SHORTCUT, SLICER}
ALL_VALUES = _DECLARABLE | {API, SEED, UNKNOWN}

_HEADER = "x-printshelf-client"


def resolve_created_via(request: Request) -> str:
    """FastAPI dependency: resolve the creating client for the current request."""
    declared = (request.headers.get(_HEADER) or "").strip().lower()
    if declared in _DECLARABLE:
        return declared
    # No/unrecognized declared client — infer from how they authenticated.
    auth = (request.headers.get("authorization") or "").strip().lower()
    if auth.startswith("bearer "):
        return API  # external consumer hitting the API with a key/JWT directly
    return WEB  # cookie-session dashboard request
