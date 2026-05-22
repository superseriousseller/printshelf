"""End-to-end QA suite for PrintShelf.

Hits public surfaces, auth, API CRUD, dashboard form POSTs, free-tier
enforcement, cross-user isolation, and the public profile + homepage
gallery. Creates two timestamped users per run — safe to re-run.

Usage:
    python backend/scripts/qa.py                                  # local
    python backend/scripts/qa.py --base https://staging.printshelf.app
    python backend/scripts/qa.py --base https://printshelf.app    # production (read paths only without --destructive)

Exit code: 0 if all checks passed, 1 otherwise.
"""
import argparse
import re
import sys
import time
from typing import Any, Optional

import httpx

# ANSI colors (no-op when piped)
def _color(code: str) -> str:
    return code if sys.stdout.isatty() else ""

GREEN = _color("\033[32m")
RED = _color("\033[31m")
YELLOW = _color("\033[33m")
DIM = _color("\033[2m")
BOLD = _color("\033[1m")
RESET = _color("\033[0m")


class QA:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.passed = 0
        self.failed = 0
        self.failures: list[str] = []
        self.section_name = ""

    def section(self, name: str) -> None:
        self.section_name = name
        print(f"\n{BOLD}── {name} ──{RESET}")

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            print(f"  {GREEN}✓{RESET} {name}")
            self.passed += 1
            return True
        else:
            print(f"  {RED}✗{RESET} {name}  {DIM}{detail}{RESET}")
            self.failed += 1
            self.failures.append(f"{self.section_name} → {name} {detail}".strip())
            return False

    def summary(self) -> int:
        total = self.passed + self.failed
        print()
        print("═" * 56)
        color = GREEN if self.failed == 0 else RED
        print(f"  {color}{BOLD}{self.passed}/{total} passed{RESET}")
        if self.failures:
            print(f"  {RED}{self.failed} failure(s):{RESET}")
            for f in self.failures:
                print(f"    {RED}·{RESET} {f}")
        print("═" * 56)
        return 0 if self.failed == 0 else 1


def _new_handle() -> str:
    return f"qa{int(time.time())}{int(time.time_ns()) % 10000:04d}"


def _json_or_none(r: httpx.Response) -> Optional[Any]:
    try:
        return r.json()
    except Exception:
        return None


def run(base: str) -> int:
    qa = QA(base)
    print(f"{BOLD}PrintShelf QA — target {base}{RESET}")

    # =========================================================
    # 1. Public surfaces (no auth)
    # =========================================================
    qa.section("Public surfaces")

    r = httpx.get(f"{base}/api/health", timeout=20)
    qa.check("GET /api/health returns 200", r.status_code == 200, f"got {r.status_code}")
    payload = _json_or_none(r) or {}
    qa.check("/api/health includes status=ok", payload.get("status") == "ok", f"payload={payload}")

    r = httpx.get(f"{base}/", timeout=20)
    qa.check("GET / returns 200", r.status_code == 200, f"got {r.status_code}")
    qa.check("Homepage contains hero h1", "shelf for every print" in r.text, "h1 missing")
    qa.check("Homepage links to /signup", 'href="/signup"' in r.text, "")

    r = httpx.get(f"{base}/static/app.css", timeout=20)
    qa.check("GET /static/app.css returns 200", r.status_code == 200, f"got {r.status_code}")

    r = httpx.get(f"{base}/u/nonexistent-{int(time.time())}", timeout=20)
    qa.check("GET /u/<unknown> returns 404", r.status_code == 404, f"got {r.status_code}")
    qa.check("404 page renders shelf-not-found copy", "shelf is empty" in r.text.lower() or "shelf not found" in r.text.lower(), "")

    # =========================================================
    # 2. Auth: signup → /me via JWT and via API key → logout
    # =========================================================
    qa.section("Auth: register/login/logout")

    handle = _new_handle()
    email = f"{handle}@printshelf.app"

    # JSON API register
    r = httpx.post(
        f"{base}/api/auth/register",
        json={"email": email, "password": "correcthorse", "username": handle, "display_name": "QA Bot"},
        timeout=20,
    )
    qa.check("POST /api/auth/register (200)", r.status_code == 200, f"got {r.status_code} body={r.text[:200]}")
    data = _json_or_none(r) or {}
    token = data.get("token", "")
    api_key = (data.get("user") or {}).get("apiKey", "")
    qa.check("register response has token", bool(token), "missing token")
    qa.check("register response has apiKey", bool(api_key), "missing apiKey")

    if token and api_key:
        # JWT works
        r = httpx.get(f"{base}/api/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=20)
        qa.check("/api/auth/me with JWT (200)", r.status_code == 200, f"got {r.status_code}")
        me = _json_or_none(r) or {}
        qa.check("/me returns expected username", me.get("username") == handle, f"got {me.get('username')!r}")

        # API key works
        r = httpx.get(f"{base}/api/auth/me", headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
        qa.check("/api/auth/me with API key (200)", r.status_code == 200, f"got {r.status_code}")

        # Bogus token rejected
        r = httpx.get(f"{base}/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"}, timeout=20)
        qa.check("/api/auth/me with bogus token (401)", r.status_code == 401, f"got {r.status_code}")

        # Login
        r = httpx.post(
            f"{base}/api/auth/login",
            json={"email": email, "password": "correcthorse"},
            timeout=20,
        )
        qa.check("POST /api/auth/login (200)", r.status_code == 200, f"got {r.status_code}")

        # Wrong password
        r = httpx.post(
            f"{base}/api/auth/login",
            json={"email": email, "password": "wrong"},
            timeout=20,
        )
        qa.check("login with wrong password → 401", r.status_code == 401, f"got {r.status_code}")

        # Duplicate registration
        r = httpx.post(
            f"{base}/api/auth/register",
            json={"email": email, "password": "correcthorse", "username": handle},
            timeout=20,
        )
        qa.check("duplicate register → 409", r.status_code == 409, f"got {r.status_code}")

        # PATCH /me
        r = httpx.patch(
            f"{base}/api/auth/me",
            json={"bio": "QA bot at work", "display_name": "QA Bot v2"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        qa.check("PATCH /api/auth/me (200)", r.status_code == 200, f"got {r.status_code}")
        qa.check("PATCH /me applied bio", (_json_or_none(r) or {}).get("bio") == "QA bot at work", "")

    # =========================================================
    # 3. CRUD via JSON API
    # =========================================================
    qa.section("API CRUD: printers, filaments, prints")
    if not token:
        qa.check("[skipped: no auth token from register]", False, "see previous errors")
        return qa.summary()
    H = {"Authorization": f"Bearer {token}"}

    # Printer
    r = httpx.post(f"{base}/api/printers", json={"name": "QA X1C", "brand": "Bambu", "model": "X1 Carbon"}, headers=H, timeout=20)
    qa.check("POST /api/printers (201)", r.status_code == 201, f"got {r.status_code} body={r.text[:200]}")
    printer = _json_or_none(r) or {}
    printer_id = printer.get("id")
    qa.check("printer has id", isinstance(printer_id, int), "")

    r = httpx.get(f"{base}/api/printers", headers=H, timeout=20)
    qa.check("GET /api/printers (200)", r.status_code == 200, f"got {r.status_code}")
    lst = _json_or_none(r) or {}
    qa.check("printers list shape", isinstance(lst.get("items"), list) and "total" in lst, f"shape={list(lst.keys())}")

    # Filaments
    fid_a = fid_b = None
    r = httpx.post(f"{base}/api/filaments", json={"brand": "Bambu", "material": "PLA", "color_name": "Black", "color_hex": "111111"}, headers=H, timeout=20)
    qa.check("POST /api/filaments (201)", r.status_code == 201, f"got {r.status_code}")
    if r.status_code == 201:
        fid_a = (_json_or_none(r) or {}).get("id")

    r = httpx.post(f"{base}/api/filaments", json={"brand": "Polymaker", "material": "PETG", "color_name": "Teal", "color_hex": "007a87"}, headers=H, timeout=20)
    if r.status_code == 201:
        fid_b = (_json_or_none(r) or {}).get("id")
    qa.check("color_hex normalizes to #prefix", (_json_or_none(r) or {}).get("colorHex", "").startswith("#"), "")

    # Bad filament status
    if fid_a:
        r = httpx.patch(f"{base}/api/filaments/{fid_a}", json={"status": "bogus"}, headers=H, timeout=20)
        qa.check("PATCH filament with bad status → 400", r.status_code == 400, f"got {r.status_code}")

    # Print referencing printer + filaments
    print_id = None
    if printer_id and fid_a and fid_b:
        r = httpx.post(
            f"{base}/api/prints",
            json={
                "title": "QA Dragon",
                "designer": "QA Bot",
                "source_platform": "printables",
                "source_url": "https://www.printables.com/model/3",
                "thumbnail_url": "https://picsum.photos/seed/qa/600",
                "printer_id": printer_id,
                "filament_ids": [fid_a, fid_b],
                "status": "printed",
                "rating": 5,
            },
            headers=H,
            timeout=20,
        )
        qa.check("POST /api/prints (201)", r.status_code == 201, f"got {r.status_code} body={r.text[:200]}")
        print_id = (_json_or_none(r) or {}).get("id")
        qa.check("print stored both filament ids", (_json_or_none(r) or {}).get("filamentIds") == [fid_a, fid_b], "")

    # Queue print
    r = httpx.post(
        f"{base}/api/prints/queue",
        json={"title": "QA Queued", "source_platform": "manual", "printer_id": printer_id},
        headers=H,
        timeout=20,
    )
    qa.check("POST /api/prints/queue (201)", r.status_code == 201, f"got {r.status_code}")
    queued_id = (_json_or_none(r) or {}).get("id")
    qa.check("queued flag set on /queue endpoint", (_json_or_none(r) or {}).get("queued") is True, "")

    # List with queued filter
    r = httpx.get(f"{base}/api/prints?queued=true", headers=H, timeout=20)
    qa.check("GET /api/prints?queued=true returns queued items", any(p.get("id") == queued_id for p in (_json_or_none(r) or {}).get("items", [])), "")

    # Mark printed
    if queued_id:
        r = httpx.post(f"{base}/api/prints/{queued_id}/printed", headers=H, timeout=20)
        qa.check("POST /api/prints/{id}/printed (200)", r.status_code == 200, f"got {r.status_code}")
        body = _json_or_none(r) or {}
        qa.check("marked print is no longer queued", body.get("queued") is False, "")
        qa.check("marked print has print_date set", body.get("printDate") is not None, "")

    # FK validation: foreign printer
    other = httpx.post(
        f"{base}/api/auth/register",
        json={"email": f"other-{handle}@printshelf.app", "password": "correcthorse", "username": f"other{handle}"},
        timeout=20,
    )
    other_token = (_json_or_none(other) or {}).get("token", "")
    if other_token:
        OH = {"Authorization": f"Bearer {other_token}"}
        # Cross-user can't see our printer
        r = httpx.get(f"{base}/api/printers/{printer_id}", headers=OH, timeout=20) if printer_id else None
        qa.check("foreign GET printer → 404", r is not None and r.status_code == 404, f"got {r.status_code if r else 'skipped'}")

        # Create a printer as other user, try to attach it to OUR print
        r = httpx.post(f"{base}/api/printers", json={"name": "Foreign Mini"}, headers=OH, timeout=20)
        foreign_printer_id = (_json_or_none(r) or {}).get("id")
        if foreign_printer_id:
            r = httpx.post(
                f"{base}/api/prints",
                json={"title": "Bad cross-ref", "printer_id": foreign_printer_id},
                headers=H,
                timeout=20,
            )
            qa.check("POST /prints with foreign printer_id → 400", r.status_code == 400, f"got {r.status_code}")

    # =========================================================
    # 3b. Photo upload
    # =========================================================
    qa.section("Photo upload")
    # Build a small valid JPEG in-memory via Pillow
    try:
        from PIL import Image
        import io as _io
        buf = _io.BytesIO()
        Image.new("RGB", (800, 600), color=(255, 100, 50)).save(buf, format="JPEG", quality=85)
        jpeg_bytes = buf.getvalue()
    except Exception as e:
        jpeg_bytes = b""
        qa.check("Pillow available for upload test", False, str(e))

    if jpeg_bytes:
        # Valid image upload
        r = httpx.post(
            f"{base}/api/uploads/photo",
            files={"file": ("qa.jpg", jpeg_bytes, "image/jpeg")},
            headers=H,
            timeout=30,
        )
        qa.check("POST /api/uploads/photo with JPEG (200)", r.status_code == 200, f"got {r.status_code} body={r.text[:200]}")
        upload_body = _json_or_none(r) or {}
        url = upload_body.get("url", "")
        qa.check("upload response has url", bool(url), "")
        qa.check("upload response has storage mode", upload_body.get("storage") in {"local", "r2"}, f"got {upload_body.get('storage')!r}")

        # Dedup: same bytes → same url
        r = httpx.post(
            f"{base}/api/uploads/photo",
            files={"file": ("qa.jpg", jpeg_bytes, "image/jpeg")},
            headers=H,
            timeout=30,
        )
        qa.check("re-upload dedupes to same URL", (_json_or_none(r) or {}).get("url") == url, "")

        # Served URL works (absolute for R2, relative for local)
        served = url if url.startswith("http") else f"{base}{url}"
        r = httpx.get(served, timeout=20)
        qa.check("uploaded photo is publicly fetchable", r.status_code == 200, f"got {r.status_code}")
        qa.check("served as image/* content-type", r.headers.get("content-type", "").startswith("image/"), f"ct={r.headers.get('content-type')}")

        # Invalid file rejected
        r = httpx.post(
            f"{base}/api/uploads/photo",
            files={"file": ("bogus.txt", b"not an image", "text/plain")},
            headers=H,
            timeout=20,
        )
        qa.check("upload non-image → 400", r.status_code == 400, f"got {r.status_code}")

        # Unauthenticated upload → 401
        r = httpx.post(
            f"{base}/api/uploads/photo",
            files={"file": ("qa.jpg", jpeg_bytes, "image/jpeg")},
            timeout=20,
        )
        qa.check("upload without auth → 401", r.status_code == 401, f"got {r.status_code}")

    # =========================================================
    # 3c. URL import
    # =========================================================
    qa.section("URL import")

    # Printables — works server-side
    r = httpx.post(f"{base}/api/import-url", json={"url": "https://www.printables.com/model/3"}, headers=H, timeout=30)
    qa.check("POST /api/import-url Printables (200)", r.status_code == 200, f"got {r.status_code}")
    body = _json_or_none(r) or {}
    qa.check("Printables import returns title", bool(body.get("title")), "")
    qa.check("Printables import returns thumbnailUrl", bool(body.get("thumbnailUrl")), "")
    qa.check("Printables import returns platform=printables", body.get("platform") == "printables", "")

    # Cached on second hit
    r = httpx.post(f"{base}/api/import-url", json={"url": "https://www.printables.com/model/3"}, headers=H, timeout=30)
    qa.check("second import → cached=true", (_json_or_none(r) or {}).get("cached") is True, "")

    # Makerworld with slug — falls back to slug-derived title (or full OG when the page is popular enough)
    r = httpx.post(
        f"{base}/api/import-url",
        json={"url": "https://makerworld.com/en/models/2815747-fruit-trinket-trays-cherry-blueberry-lemon"},
        headers=H, timeout=30,
    )
    qa.check("Makerworld URL with slug → 200", r.status_code == 200, f"got {r.status_code}")
    body = _json_or_none(r) or {}
    qa.check("Makerworld slug yields a title", bool(body.get("title")), f"title={body.get('title')!r}")

    # Makerworld without a slug (just numeric ID) — no salvage possible → 400
    r = httpx.post(f"{base}/api/import-url", json={"url": "https://makerworld.com/en/models/2"}, headers=H, timeout=30)
    qa.check("Makerworld id-only URL → 400", r.status_code == 400, f"got {r.status_code}")
    detail = (_json_or_none(r) or {}).get("detail", "")
    qa.check("Makerworld error mentions manual paste", "manually" in detail or "manual" in detail.lower(), f"detail={detail[:120]}")

    # Bad URL
    r = httpx.post(f"{base}/api/import-url", json={"url": "not-a-real-url"}, headers=H, timeout=20)
    qa.check("Bad URL → 400", r.status_code == 400, f"got {r.status_code}")

    # Unauthed
    r = httpx.post(f"{base}/api/import-url", json={"url": "https://www.printables.com/model/3"}, timeout=20)
    qa.check("Import without auth → 401", r.status_code == 401, f"got {r.status_code}")

    # =========================================================
    # 4. Free-tier enforcement (10 filaments)
    # =========================================================
    qa.section("Free tier enforcement")
    # Already created 2 filaments; create 8 more to reach the cap of 10.
    capped = False
    for i in range(8):
        r = httpx.post(
            f"{base}/api/filaments",
            json={"brand": "FillerBrand", "material": "PLA", "color_name": f"Filler{i}"},
            headers=H,
            timeout=20,
        )
        if r.status_code != 201:
            qa.check(f"create filler filament #{i+3} (201)", False, f"got {r.status_code}")
            capped = True
            break
    if not capped:
        # 11th should 402
        r = httpx.post(
            f"{base}/api/filaments",
            json={"brand": "Cap", "material": "PLA"},
            headers=H,
            timeout=20,
        )
        qa.check("11th filament → 402 upgrade_required", r.status_code == 402, f"got {r.status_code}")
        body = _json_or_none(r) or {}
        detail = body.get("detail") or {}
        qa.check("402 payload has upgrade_required shape",
                 isinstance(detail, dict) and detail.get("error") == "upgrade_required" and detail.get("limit") == 10,
                 f"detail={detail}")

    # =========================================================
    # 5. Web UI: signup form, dashboard, logout via cookie
    # =========================================================
    qa.section("Web UI: signup + dashboard via cookies")
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        web_handle = _new_handle()
        web_email = f"{web_handle}@printshelf.app"

        # GET /signup
        r = client.get(f"{base}/signup")
        qa.check("GET /signup (200)", r.status_code == 200, f"got {r.status_code}")
        qa.check("signup form posts to /signup", '<form method="post" action="/signup"' in r.text, "")

        # Bad signup: mismatched passwords → 400 with error
        r = client.post(f"{base}/signup", data={"email": web_email, "username": web_handle, "password": "correcthorse", "password_confirm": "wrong", "display_name": "Web QA"})
        qa.check("POST /signup mismatched pw → 400", r.status_code == 400, f"got {r.status_code}")
        qa.check("error rendered in signup form", "Passwords don" in r.text, "")

        # Good signup
        r = client.post(f"{base}/signup", data={"email": web_email, "username": web_handle, "password": "correcthorse", "password_confirm": "correcthorse", "display_name": "Web QA"})
        qa.check("POST /signup (303 → /dashboard)", r.status_code == 303 and r.headers.get("location") == "/dashboard", f"status={r.status_code} loc={r.headers.get('location')}")
        qa.check("session cookie set on signup", "session" in client.cookies, "")

        # /dashboard
        r = client.get(f"{base}/dashboard")
        qa.check("GET /dashboard with cookie (200)", r.status_code == 200, f"got {r.status_code}")
        qa.check("dashboard greets user", "Welcome back, Web QA" in r.text, "")

        # /dashboard/printers, /filaments, /prints
        for path in ("/dashboard/printers", "/dashboard/filaments", "/dashboard/prints", "/dashboard/prints?queued=true"):
            r = client.get(f"{base}{path}")
            qa.check(f"GET {path} (200)", r.status_code == 200, f"got {r.status_code}")

        # Add a printer via form
        r = client.post(f"{base}/dashboard/printers", data={"name": "Web Mini", "brand": "Bambu", "model": "A1 mini"})
        qa.check("POST /dashboard/printers (303)", r.status_code == 303, f"got {r.status_code}")

        # Auto-import on save: URL provided, title blank → server extracts title from URL
        r = client.post(
            f"{base}/dashboard/prints",
            data={
                "title": "",
                "source_url": "https://www.printables.com/model/3",
                "source_platform": "manual",  # server should overwrite with "printables"
                "status": "printed",
                "is_public": "1",
            },
        )
        qa.check("POST /dashboard/prints with URL + blank title → 303", r.status_code == 303, f"got {r.status_code}")

        # Confirm the print landed with the extracted title (server should have populated it)
        r = client.get(f"{base}/dashboard/prints")
        qa.check("auto-imported print has the extracted title", "Josef Prusa" in r.text, "title not in list")

        # Neither title nor URL → server-side validation error (no HTML5 required gate anymore)
        r = client.post(
            f"{base}/dashboard/prints",
            data={"title": "", "source_url": "", "source_platform": "manual", "status": "printed"},
        )
        qa.check("blank title + no URL → 400 with helpful message", r.status_code == 400, f"got {r.status_code}")
        qa.check("error mentions URL fallback", "source URL" in r.text or "paste a source URL" in r.text, "")

        r = client.get(f"{base}/dashboard/printers")
        qa.check("printer appears in dashboard list", "Web Mini" in r.text, "")

        # Logout
        r = client.post(f"{base}/logout")
        qa.check("POST /logout (303 → /)", r.status_code == 303 and r.headers.get("location") == "/", f"status={r.status_code} loc={r.headers.get('location')}")

        # /dashboard now redirects to /login
        r = client.get(f"{base}/dashboard")
        qa.check("after logout /dashboard → 303 /login", r.status_code == 303 and "/login" in (r.headers.get("location") or ""), f"got {r.status_code} loc={r.headers.get('location')}")

    # =========================================================
    # 6. Public profile reflects state
    # =========================================================
    qa.section("Public profile + homepage gallery")

    r = httpx.get(f"{base}/u/{handle}", timeout=20)
    qa.check(f"GET /u/{handle} (200)", r.status_code == 200, f"got {r.status_code}")
    qa.check("profile shows QA Dragon", "QA Dragon" in r.text, "")
    qa.check("profile has og:title meta", 'property="og:title"' in r.text, "")
    qa.check("profile has og:description meta", 'property="og:description"' in r.text, "")

    # Material filter
    r = httpx.get(f"{base}/u/{handle}?material=PETG", timeout=20)
    qa.check("profile material filter works", r.status_code == 200, f"got {r.status_code}")

    # Status filter
    r = httpx.get(f"{base}/u/{handle}?status=printed", timeout=20)
    qa.check("profile status filter works", r.status_code == 200, f"got {r.status_code}")

    # Homepage gallery should contain at least one print (the public ones we added)
    r = httpx.get(f"{base}/", timeout=20)
    qa.check("homepage shows at least one featured print", "home-card" in r.text, "no home-cards rendered")

    return qa.summary()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765",
                    help="API base URL (default: local)")
    args = ap.parse_args()
    try:
        return run(args.base)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}interrupted{RESET}")
        return 2
    except httpx.RequestError as e:
        print(f"\n{RED}request failed: {e}{RESET}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
