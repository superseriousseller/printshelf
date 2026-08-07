"""Automated Chrome-extension QA harness (Tier 1).

Loads the UNPACKED extension in a real Chromium via Playwright — behaviorally
identical to the published extension — points it at a throwaway local PrintShelf
server, invokes the extension's real create path, and asserts the row lands with
`created_via='extension'` (proving the X-PrintShelf-Client header travels the
whole way: extension binary -> server resolver -> DB).

This does NOT scrape real store pages (that's Tier 2 / ROADMAP P2, which needs
live MakerWorld/Printables/etc DOM). It exercises addPrint() directly in the
extension's service worker — the exact function the injected button triggers.

Run (from backend/):  python scripts/extension_qa.py
Exit code 0 = pass, 1 = fail. Prints a clear PASS/FAIL line.
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


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _wait_http(url: str, timeout: float = 25.0) -> bool:
    import urllib.request
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.4)
    return False


def main() -> int:
    port = _free_port()
    db_path = tempfile.mktemp(suffix="_extqa.db")
    db_url = f"sqlite:///{db_path}"
    # Set in the PARENT env too so this process's own models.SessionLocal (seed +
    # assert) hits the same temp DB the subprocesses migrate/serve — not the dev DB.
    os.environ["DATABASE_URL"] = db_url
    os.environ["SECRET_KEY"] = "x" * 32
    env = {**os.environ, "DATABASE_URL": db_url, "SECRET_KEY": "x" * 32, "ADMIN_USERNAME": "extqa"}

    # 1) migrate + seed a user with a known API key
    subprocess.run(["../venv/bin/alembic", "upgrade", "head"], cwd=BACKEND_DIR, env=env, check=True,
                   capture_output=True)
    sys.path.insert(0, BACKEND_DIR)
    from models import SessionLocal, User, generate_api_key  # noqa: E402
    db = SessionLocal()
    api_key = generate_api_key()
    u = User(username="extqa", email="extqa@test.local", password_hash="x", api_key=api_key)
    db.add(u); db.commit(); db.close()

    # 2) boot the real app locally
    server = subprocess.Popen(
        ["../venv/bin/uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=BACKEND_DIR, env=env,
    )
    api_base = f"http://127.0.0.1:{port}"
    ok = _wait_http(f"{api_base}/", timeout=25)
    result = 1
    tmp_dirs: list = []
    try:
        if not ok:
            print("FAIL — local server did not come up")
            return 1

        # 3) load the UNPACKED extension in a real Chromium.
        #    MV3 only lets the service worker fetch hosts in host_permissions, and
        #    the shipped manifest only whitelists local port 8765 (held here by the
        #    wiki server). So load a temp COPY with the test port added — the real
        #    artifact is untouched; only the local host allowlist differs, which is
        #    orthogonal to the header behavior under test.
        ext_copy = tempfile.mkdtemp(suffix="_extqa_ext")
        tmp_dirs.append(ext_copy)
        shutil.rmtree(ext_copy)
        shutil.copytree(EXT_DIR, ext_copy)
        mpath = os.path.join(ext_copy, "manifest.json")
        with open(mpath) as fh:
            man = json.load(fh)
        man.setdefault("host_permissions", []).append(f"http://127.0.0.1:{port}/*")
        with open(mpath, "w") as fh:
            json.dump(man, fh)

        from playwright.sync_api import sync_playwright
        user_data = tempfile.mkdtemp(suffix="_extqa_profile")
        tmp_dirs.append(user_data)
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=user_data,
                headless=False,  # extensions require a headed context
                args=[f"--disable-extensions-except={ext_copy}", f"--load-extension={ext_copy}"],
            )
            # get the extension's service worker (MV3 background)
            sw = None
            for _ in range(50):
                sws = ctx.service_workers
                if sws:
                    sw = sws[0]; break
                try:
                    sw = ctx.wait_for_event("serviceworker", timeout=1000); break
                except Exception:
                    time.sleep(0.2)
            if sw is None:
                print("FAIL — extension service worker never started")
                ctx.close(); return 1

            # 4) configure the extension to hit our local server, then run the REAL create path
            sw.evaluate(
                """async ([apiBase, apiKey]) => {
                    await new Promise(r => chrome.storage.sync.set({apiBase, apiKey}, r));
                }""",
                [api_base, api_key],
            )
            res = sw.evaluate(
                """async () => await addPrint({
                    title: "ExtQA Benchy",
                    sourcePlatform: "makerworld",
                    sourceUrl: "https://makerworld.com/models/extqa-1",
                })""",
            )
            ctx.close()
        print("extension addPrint() returned:", res)

        # 5) assert the row landed as created_via='extension'
        from models import SessionLocal as SL, Print  # noqa: E402
        db2 = SL()
        p = db2.query(Print).filter(Print.title == "ExtQA Benchy").first()
        got = p.created_via if p else None
        db2.close()
        if got == "extension":
            print(f"PASS — unpacked extension created a print with created_via={got!r}")
            result = 0
        else:
            print(f"FAIL — expected created_via='extension', got {got!r} (print found: {p is not None})")
            result = 1
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()
        try:
            os.remove(db_path)
        except Exception:
            pass
        for d in tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)
    return result


if __name__ == "__main__":
    sys.exit(main())
