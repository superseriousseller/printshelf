"""Tier 2 extension QA — drive the REAL content scripts on live model sites.

Answers the ROADMAP P2 question: prod prints are 291 MakerWorld / 3 Printables /
0 Thingiverse / 0 Cults3D — is that a broken content script or just user
preference? This loads the unpacked extension headed, and for each platform:
  1. opens a listing page, finds a live model link IN-BROWSER (robust to id churn)
  2. navigates to that model page
  3. waits for the injected #printshelf-fab button (proves the content script ran)
  4. clicks it -> real scrape -> save to a throwaway LOCAL server
  5. reads back the created row's title + source_platform

Per-platform verdict: reached model page? FAB injected? saved? scraped a real title?

Needs headed Chromium (real browser dodges the anti-bot that blocks WebFetch).
Run from backend/:  python scripts/extension_qa_scrape.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

EXT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "chrome-extension"))
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# `direct` = a known-good model URL; when set, we go straight there (full page
# load, like a user landing from Google/a shared link) instead of hunting the
# listing. This both hardens the harness and isolates real content-script bugs
# from SPA soft-navigation timing artifacts.
PLATFORMS = [
    {"name": "makerworld", "listing": "https://makerworld.com/en/popular", "link": 'a[href*="/models/"]'},
    {"name": "printables", "listing": "https://www.printables.com/model", "link": 'a[href*="/model/"]',
     "direct": "https://www.printables.com/model/1782379-ultimate-weekly-pill-organizer-dispenser-gravity-c"},
    {"name": "thingiverse", "listing": "https://www.thingiverse.com/", "link": 'a[href*="/thing:"]',
     "direct": "https://www.thingiverse.com/thing:7391415"},
    {"name": "cults3d", "listing": "https://cults3d.com/en", "link": 'a[href*="/3d-model/"]'},
]


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _wait_http(url, timeout=25.0):
    import urllib.request
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2); return True
        except Exception:
            time.sleep(0.4)
    return False


def main():
    port = _free_port()
    db_path = tempfile.mktemp(suffix="_extqa2.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["SECRET_KEY"] = "x" * 32
    env = {**os.environ, "ADMIN_USERNAME": "extqa"}
    subprocess.run(["../venv/bin/alembic", "upgrade", "head"], cwd=BACKEND_DIR, env=env, check=True, capture_output=True)
    sys.path.insert(0, BACKEND_DIR)
    from models import SessionLocal, User, Print, generate_api_key
    db = SessionLocal(); api_key = generate_api_key()
    db.add(User(username="extqa", email="e@t.local", password_hash="x", api_key=api_key)); db.commit(); db.close()

    server = subprocess.Popen(
        ["../venv/bin/uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=BACKEND_DIR, env=env)
    api_base = f"http://127.0.0.1:{port}"
    tmp_dirs = []
    results = []
    try:
        if not _wait_http(f"{api_base}/"):
            print("FAIL — local server did not start"); return 1

        # temp extension copy with the local test port allowed (see extension_qa.py)
        ext_copy = tempfile.mkdtemp(suffix="_extqa2_ext"); tmp_dirs.append(ext_copy)
        shutil.rmtree(ext_copy); shutil.copytree(EXT_DIR, ext_copy)
        mpath = os.path.join(ext_copy, "manifest.json")
        man = json.load(open(mpath)); man.setdefault("host_permissions", []).append(f"http://127.0.0.1:{port}/*")
        json.dump(man, open(mpath, "w"))

        from playwright.sync_api import sync_playwright
        user_data = tempfile.mkdtemp(suffix="_extqa2_profile"); tmp_dirs.append(user_data)
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=user_data, headless=False,
                args=[f"--disable-extensions-except={ext_copy}", f"--load-extension={ext_copy}"])
            # configure the extension (storage is shared with content scripts)
            sw = None
            for _ in range(50):
                if ctx.service_workers:
                    sw = ctx.service_workers[0]; break
                try:
                    sw = ctx.wait_for_event("serviceworker", timeout=1000); break
                except Exception:
                    time.sleep(0.2)
            if sw:
                sw.evaluate("""async ([b,k])=>{await new Promise(r=>chrome.storage.sync.set({apiBase:b,apiKey:k},r));}""",
                            [api_base, api_key])

            for plat in PLATFORMS:
                r = {"platform": plat["name"], "model_url": None, "fab": False, "saved": False, "title": None, "note": ""}
                page = ctx.new_page()
                try:
                    href = plat.get("direct")
                    if href:
                        r["note"] = "(direct model load) "
                    else:
                        page.goto(plat["listing"], wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(3500)  # let SPA hydrate
                        # nudge lazy-loaded grids, then wait for a model link to appear
                        try:
                            page.mouse.wheel(0, 2500); page.wait_for_timeout(1500)
                        except Exception:
                            pass
                        try:
                            page.wait_for_selector(plat["link"], timeout=8000)
                            el = page.query_selector(plat["link"])
                            if el:
                                href = el.get_attribute("href")
                        except Exception:
                            pass
                    if not href:
                        r["note"] = "no model link found on listing (blocked or DOM changed)"
                        results.append(r); page.close(); continue
                    if href.startswith("/"):
                        from urllib.parse import urljoin
                        href = urljoin(plat["listing"], href)
                    r["model_url"] = href
                    page.goto(href, wait_until="domcontentloaded", timeout=30000)
                    # let the model page's real content (h1/JSON-LD) render BEFORE
                    # clicking — the content script scrapes on click, so clicking too
                    # early makes it fall back to document.title/canonical.
                    # Wait until a REAL title source exists (JSON-LD name / og:title /
                    # non-empty h1) so we don't scrape the un-hydrated SPA shell and
                    # falsely blame the content script. Mirrors a real user's timing.
                    try:
                        page.wait_for_function(
                            """() => {
                                const og = document.querySelector('meta[property=\\"og:title\\"]');
                                if (og && og.content && og.content.trim()) return true;
                                for (const s of document.querySelectorAll('script[type=\\"application/ld+json\\"]')) {
                                    try { const j = JSON.parse(s.textContent); if (JSON.stringify(j).includes('\\"name\\"')) return true; } catch(e){}
                                }
                                const h1 = document.querySelector('h1');
                                return !!(h1 && h1.textContent && h1.textContent.trim().length > 3);
                            }""",
                            timeout=15000,
                        )
                    except Exception:
                        r["note"] = "(title source never hydrated in-harness) "
                    page.wait_for_timeout(1500)
                    # wait for the injected FAB
                    try:
                        page.wait_for_selector("#printshelf-fab [data-btn]", timeout=20000)
                        r["fab"] = True
                    except Exception:
                        r["note"] = "FAB never injected (content script did not run / broke)"
                        results.append(r); page.close(); continue
                    # count prints before, click, then look for a new row
                    before = _count(plat["name"])
                    page.click("#printshelf-fab [data-btn]")
                    for _ in range(40):
                        page.wait_for_timeout(500)
                        if _count(plat["name"]) > before:
                            r["saved"] = True; break
                    r["title"] = _latest_title(plat["name"])
                    if not r["saved"] and not r["note"]:
                        r["note"] = "FAB clicked but no row saved (scrape/save failed — check toast)"
                except Exception as e:
                    r["note"] = f"page error: {type(e).__name__}: {str(e)[:120]}"
                results.append(r)
                page.close()
            ctx.close()
    finally:
        server.terminate()
        try: server.wait(timeout=5)
        except Exception: server.kill()
        try: os.remove(db_path)
        except Exception: pass
        for d in tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)

    print("\n===== TIER 2 SCRAPER RESULTS =====")
    for r in results:
        verdict = "OK" if (r["fab"] and r["saved"] and r["title"] and r["title"] != "Untitled print") else "PROBLEM"
        print(f"[{verdict}] {r['platform']}: fab={r['fab']} saved={r['saved']} title={r['title']!r}")
        if r["note"]:
            print(f"        note: {r['note']}")
        if r["model_url"]:
            print(f"        url: {r['model_url']}")
    return 0


def _count(platform):
    from models import SessionLocal, Print
    db = SessionLocal()
    try:
        return db.query(Print).filter(Print.source_platform == platform).count()
    finally:
        db.close()


def _latest_title(platform):
    from models import SessionLocal, Print
    db = SessionLocal()
    try:
        p = db.query(Print).filter(Print.source_platform == platform).order_by(Print.created_at.desc()).first()
        return p.title if p else None
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
