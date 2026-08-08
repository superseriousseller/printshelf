"""
Tesla Fleet API support routes (personal use — Cam's own vehicle only).

Two inert, non-user-facing endpoints required by Tesla to register a
third-party Fleet API application on the printshelf.app domain:

  1. GET /.well-known/appspecific/com.tesla.3p.public-key.pem
       Serves the app's PUBLIC key so Tesla can verify domain ownership
       and validate signed vehicle commands. A public key is meant to be
       public — this exposes nothing sensitive. The matching PRIVATE key
       never leaves the Tess assistant machine.

  2. GET /tesla/callback
       OAuth redirect target. Captures the one-time authorization `code`
       and shows it for copy-back to Tess (which holds the client secret
       and performs the token exchange). Not linked anywhere; does nothing
       for a normal visitor.

Neither route touches PrintShelf data, users, auth, or the database.
"""
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, HTMLResponse

router = APIRouter(tags=["tesla"])

# App public key (EC prime256v1). Safe to serve publicly — it's a public key.
_TESLA_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEB5xI2IvUL0m4gicqFpdG1bIBZuyk
+MsHgZqLw8vvz+Cv5MtBC3plysZImGg0Pjrv1Kgz5tqcgAixCFKG2JPV5A==
-----END PUBLIC KEY-----
"""


@router.get(
    "/.well-known/appspecific/com.tesla.3p.public-key.pem",
    response_class=PlainTextResponse,
    include_in_schema=False,
)
async def tesla_public_key():
    return PlainTextResponse(
        content=_TESLA_PUBLIC_KEY_PEM,
        media_type="application/x-pem-file",
    )


@router.get("/tesla/callback", response_class=HTMLResponse, include_in_schema=False)
async def tesla_callback(request: Request):
    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    error = request.query_params.get("error", "")

    if error:
        body = f"<h2>Tesla authorization error</h2><p>{error}</p>"
    elif code:
        body = (
            "<h2>Tesla authorization received</h2>"
            "<p>Copy this code back into Tess to finish linking your car:</p>"
            f"<textarea readonly style='width:100%;height:6em;font-size:16px'>{code}</textarea>"
            f"<p style='color:#888'>state: {state}</p>"
        )
    else:
        body = "<h2>Tesla callback</h2><p>No authorization code present.</p>"

    html = (
        "<!doctype html><html><head><meta name='viewport' "
        "content='width=device-width,initial-scale=1'>"
        "<title>Tesla auth</title></head>"
        f"<body style='font-family:system-ui;max-width:640px;margin:40px auto;padding:0 16px'>{body}</body></html>"
    )
    return HTMLResponse(content=html)
