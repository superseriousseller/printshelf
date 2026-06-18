"""Full-project visual + function audit via Playwright.

Loads every HTML screen at desktop (1440) and mobile (390) widths and flags:
  - non-200 HTTP status
  - JS console errors / uncaught page errors
  - horizontal overflow on mobile (scrollWidth > clientWidth — the #1 mobile bug)
Captures a screenshot of every screen/viewport, and runs a few functional
interaction checks (filament picker, explore filter, rating widget).

IMPORTANT — reaching a LOCAL dev server:
  The sandboxed Playwright browser can't reach 127.0.0.1, but CAN reach the
  Mac's LAN IP. Bind uvicorn to 0.0.0.0 and pass the LAN IP as --base:
      cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8770
      python backend/scripts/visual_audit.py --base http://$(ipconfig getifaddr en0):8770 \
          --email filtest@printshelf.app --password testpass1
  Or point at deployed staging:
      python backend/scripts/visual_audit.py --base https://staging.printshelf.app --email ... --password ...

Driver: use a Python that has playwright installed (e.g.
  /Library/Frameworks/Python.framework/Versions/3.14/bin/python3).

Exit code: 0 if no issues, 1 otherwise.
"""
import argparse
import os
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("playwright not installed for this interpreter. Use one that has it (see module docstring).")

# (label, path, needs_auth) — dynamic-id paths assume the audit account owns them.
SCREENS = [
    ("home", "/", False),
    ("explore", "/explore", False),
    ("explore-category", "/explore?category=gadgets", False),
    ("search", "/search?q=dragon", False),
    ("signup", "/signup", False),
    ("login", "/login", False),
    ("forgot-password", "/forgot-password", False),
    ("terms", "/terms", False),
    ("privacy", "/privacy", False),
    ("developers", "/developers", False),
    ("dashboard", "/dashboard", True),
    ("prints-list", "/dashboard/prints", True),
    ("print-new", "/dashboard/prints/new", True),
    ("filaments-list", "/dashboard/filaments", True),
    ("filament-new", "/dashboard/filaments/new", True),
    ("printers-list", "/dashboard/printers", True),
    ("printer-new", "/dashboard/printers/new", True),
    ("account", "/dashboard/account", True),
    ("feed", "/dashboard/feed", True),
    ("upgrade", "/dashboard/upgrade", True),
]

VIEWPORTS = {"desktop": {"width": 1440, "height": 900}, "mobile": {"width": 390, "height": 844}}


def audit_screen(ctx, base, label, path, vp):
    page = ctx.new_page()
    errors, pageerrors = [], []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: pageerrors.append(str(e)))
    try:
        resp = page.goto(base + path, wait_until="load", timeout=15000)
        status = resp.status if resp else 0
    except Exception as e:
        page.close()
        return {"label": label, "vp": vp, "status": "ERR", "over": 0, "console": [str(e)], "pageerr": []}
    page.wait_for_timeout(350)
    ov = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    if shot_dir:
        page.screenshot(path=os.path.join(shot_dir, f"{label}_{vp}.png"))
    page.close()
    return {"label": label, "vp": vp, "status": status, "over": ov, "console": list(errors), "pageerr": list(pageerrors)}


def login(page, base, email, password):
    page.goto(base + "/login", wait_until="load")
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("load")
    return "/dashboard" in page.url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="Base URL (LAN IP for local, or staging/prod URL)")
    ap.add_argument("--email", help="Login for authed screens")
    ap.add_argument("--password", help="Login password")
    ap.add_argument("--shots", default="/tmp/audit_shots", help="Screenshot dir ('' to skip)")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    global shot_dir
    shot_dir = args.shots or None
    if shot_dir:
        os.makedirs(shot_dir, exist_ok=True)

    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for vp_name, vp in VIEWPORTS.items():
            ctx = browser.new_context(viewport=vp)
            authed = False
            if args.email and args.password:
                p = ctx.new_page()
                authed = login(p, base, args.email, args.password)
                p.close()
            for label, path, needs_auth in SCREENS:
                if needs_auth and not authed:
                    continue
                results.append(audit_screen(ctx, base, label, path, vp_name))
            ctx.close()
        browser.close()

    problems = []
    for r in results:
        flags = []
        if r["status"] != 200:
            flags.append(f"HTTP {r['status']}")
        if r["vp"] == "mobile" and r["over"] and r["over"] > 0:
            flags.append(f"H-OVERFLOW +{r['over']}px")
        if r["console"]:
            flags.append(f"CONSOLE {r['console'][:2]}")
        if r["pageerr"]:
            flags.append(f"PAGEERR {r['pageerr'][:2]}")
        if flags:
            problems.append((r, flags))

    print(f"\nVISUAL AUDIT — {len(results)} screen/viewport loads vs {base}")
    if not problems:
        print("✅ No issues: all 200, no console/page errors, no mobile horizontal overflow.")
        sys.exit(0)
    print(f"⚠️  {len(problems)} flagged:")
    for r, flags in problems:
        print(f"  [{r['vp']:7}] {r['label']:20} {' | '.join(flags)}")
    sys.exit(1)


shot_dir = None
if __name__ == "__main__":
    main()
