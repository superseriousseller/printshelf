"""Local-only web UI for the Instruments Index audio pipeline — wraps
ingest_instrument_audio.py, score_instrument_audio.py, and iowa_mis_fetch.py
behind file pickers and buttons instead of CLI flags.

Run:
    python backend/scripts/instruments_admin.py
Opens http://127.0.0.1:8899 in your browser automatically. Binds to
127.0.0.1 only — never reachable from your network, no auth needed.

Reads backend/.env for DATABASE_URL / R2_* (same file+vars as
backend/.env.example). Nothing here is deployed — it never touches
Railway, and objective-score still needs librosa installed locally
(pip install -r backend/scripts/requirements-audio-scoring.txt) but the
page tells you that inline if it's missing rather than crashing.
"""
import html
import os
import sys
import tempfile
import threading
import webbrowser

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_DIR)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

from fastapi import FastAPI, Form, UploadFile, File  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
import uvicorn  # noqa: E402

from models import RegistryEntry, SessionLocal  # noqa: E402
from storage import upload_audio  # noqa: E402

# Sibling scripts, imported for their functions (not their CLI __main__ block).
import ingest_instrument_audio as ingest_lib  # noqa: E402
import score_instrument_audio as score_lib  # noqa: E402
import iowa_mis_fetch as iowa_lib  # noqa: E402
import import_service  # noqa: E402 — reuses the same OG-image scraper print imports use

app = FastAPI()

_IOWA_DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "printshelf-iowa-downloads")


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)} — Instruments Audio Admin</title>
<style>
  body {{ background:#0f1115; color:#e8e8ea; font-family:-apple-system,system-ui,sans-serif; max-width:820px; margin:0 auto; padding:32px 20px 80px; line-height:1.5; }}
  h1 {{ font-size:1.4rem; }} h2 {{ font-size:1.05rem; margin-top:36px; color:#c8c8cc; }}
  a {{ color:#ff6a3d; }} a.back {{ display:inline-block; margin-bottom:16px; }}
  .card {{ background:#171920; border:1px solid #2a2d36; border-radius:10px; padding:16px 18px; margin:12px 0; }}
  .entry-row {{ display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid #23252d; }}
  .entry-row:last-child {{ border-bottom:none; }}
  .badge {{ font-size:0.75rem; padding:2px 8px; border-radius:20px; background:#23252d; color:#a8a8ae; }}
  .badge.yes {{ background:#1f3a2a; color:#7fd99a; }}
  label {{ display:block; margin:14px 0 4px; font-size:0.85rem; color:#a8a8ae; }}
  input[type=text], input[type=file] {{ width:100%; box-sizing:border-box; background:#0f1115; border:1px solid #2a2d36; color:#e8e8ea; border-radius:6px; padding:8px 10px; font-size:0.9rem; }}
  button {{ background:#ff6a3d; color:#0f1115; border:none; border-radius:6px; padding:10px 18px; font-weight:600; cursor:pointer; margin-top:16px; }}
  button.secondary {{ background:#23252d; color:#e8e8ea; }}
  .msg {{ padding:12px 14px; border-radius:8px; margin:16px 0; }}
  .msg.ok {{ background:#1f3a2a; color:#7fd99a; }}
  .msg.err {{ background:#3a1f24; color:#f28b8b; }}
  .file-row {{ display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #23252d; font-size:0.85rem; }}
  audio {{ width:100%; margin-top:6px; }}
</style></head><body>
<h1>Instruments Audio Admin</h1>
{body}
</body></html>""")


def _entry_or_404(db, slug):
    return db.query(RegistryEntry).filter(
        RegistryEntry.vertical == "instruments", RegistryEntry.slug == slug,
    ).first()


@app.get("/", response_class=HTMLResponse)
def index():
    db = SessionLocal()
    entries = (
        db.query(RegistryEntry)
        .filter(RegistryEntry.vertical == "instruments", RegistryEntry.status == "listed")
        .order_by(RegistryEntry.family, RegistryEntry.name)
        .all()
    )
    rows = []
    for e in entries:
        media = e.media or []
        has_printed = any(m.get("kind") == "audio_printed" for m in media)
        has_real = any(m.get("kind") == "audio_real" for m in media)
        audio_badge = '<span class="badge yes">audio ✓</span>' if (has_printed and has_real) else '<span class="badge">no audio</span>'
        score_badge = f'<span class="badge yes">score {e.objective_score}</span>' if e.objective_score is not None else ""
        rows.append(f"""<div class="entry-row">
            <a href="/entry/{html.escape(e.slug)}">{html.escape(e.name)}</a>
            <span>{audio_badge} {score_badge}</span>
        </div>""")
    return _page("Entries", f"""
    <p>Pick an entry to add or replace its audio A/B pair.</p>
    <div class="card">{''.join(rows)}</div>
    """)


@app.get("/entry/{slug}", response_class=HTMLResponse)
def entry_detail(slug: str, msg: str = "", err: str = ""):
    db = SessionLocal()
    entry = _entry_or_404(db, slug)
    if entry is None:
        return _page("Not found", '<p>No such entry.</p><a href="/">&larr; back</a>')

    media = entry.media or []
    printed = next((m for m in media if m.get("kind") == "audio_printed"), None)
    real = next((m for m in media if m.get("kind") == "audio_real"), None)

    thumbnail_url = None
    if entry.source_url:
        try:
            thumbnail_url = import_service.extract(entry.source_url).get("thumbnail_url")
        except Exception:
            pass  # no scrapable image — the Source link below still gets you there

    identity = '<div class="card" style="display:flex;gap:16px;align-items:flex-start">'
    if thumbnail_url:
        identity += f'<img src="{html.escape(thumbnail_url)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()" style="width:120px;height:120px;object-fit:cover;border-radius:8px;flex:none">'
    identity += '<div>'
    if entry.designer:
        identity += f'<p style="margin:0 0 6px;color:#a8a8ae">by {html.escape(entry.designer)} &middot; {html.escape(entry.family or "")}</p>'
    if entry.note:
        identity += f'<p style="margin:0 0 10px;white-space:pre-line;color:#c8c8cc;font-size:0.9rem">{html.escape(entry.note)}</p>'
    links = []
    if entry.source_url:
        links.append(f'<a href="{html.escape(entry.source_url)}" target="_blank" rel="noopener">Source ↗</a>')
    if entry.demo_url:
        links.append(f'<a href="{html.escape(entry.demo_url)}" target="_blank" rel="noopener">Demo ↗</a>')
    identity += " &middot; ".join(links)
    identity += '</div></div>'

    current = ""
    if printed or real:
        current = '<h2>Current clips</h2><div class="card">'
        if printed:
            current += f'<p><strong>Printed</strong> — {html.escape(printed.get("phrase") or "")}</p><audio controls src="{html.escape(printed["url"])}"></audio>'
        if real:
            current += f'<p style="margin-top:14px"><strong>Real</strong> — {html.escape(real.get("source") or "")}</p><audio controls src="{html.escape(real["url"])}"></audio>'
        current += "</div>"

    banner = ""
    if msg:
        banner = f'<div class="msg ok">{html.escape(msg)}</div>'
    if err:
        banner = f'<div class="msg err">{html.escape(err)}</div>'

    score_section = f"""
    <h2>Objective score</h2>
    <div class="card">
        <p>{"Current score: <strong>" + str(entry.objective_score) + "</strong>" if entry.objective_score is not None else "Not computed yet."}</p>
        <form method="post" action="/entry/{html.escape(slug)}/score">
            <button type="submit"{"" if (printed and real) else " disabled"}>Compute objective score</button>
        </form>
        {"<p style='color:#a8a8ae;font-size:0.85rem'>Needs both clips uploaded first.</p>" if not (printed and real) else ""}
    </div>
    """

    iowa_options = "".join(f'<option value="{s}">{s}</option>' for s in sorted(iowa_lib.INSTRUMENT_PAGES))

    return _page(entry.name, f"""
    <a class="back" href="/">&larr; all entries</a>
    <h1>{html.escape(entry.name)}</h1>
    {identity}
    {banner}
    {current}

    <h2>Upload audio A/B pair</h2>
    <div class="card">
        <form method="post" action="/entry/{html.escape(slug)}/upload" enctype="multipart/form-data">
            <label>Printed clip (your recording)</label>
            <input type="file" name="printed" accept="audio/*" required>

            <label>Real clip (one file, or multiple to concatenate — e.g. several Iowa MIS note files)</label>
            <input type="file" name="real" accept="audio/*" multiple required>

            <label>Phrase (what's being played — shown on the card)</label>
            <input type="text" name="phrase" placeholder="C-major scale, one octave" required>

            <label>Real clip source</label>
            <input type="text" name="real_source" placeholder="Cam, same mic/room as printed — or University of Iowa MIS" required>

            <label>Real clip license</label>
            <input type="text" name="real_license" placeholder="Original recording — or Public domain" required>

            <button type="submit">Normalize, upload &amp; save</button>
        </form>
    </div>

    {score_section}

    <h2>Browse University of Iowa MIS (optional — real-clip source)</h2>
    <div class="card">
        <form method="get" action="/entry/{html.escape(slug)}/iowa">
            <label>Instrument</label>
            <select name="instrument">{iowa_options}</select>
            <button type="submit" class="secondary">List files</button>
        </form>
        <p style="color:#a8a8ae;font-size:0.85rem;margin-top:10px">Downloads save locally; pick the downloaded file(s) in the "Real clip" field above.</p>
    </div>
    """)


@app.get("/entry/{slug}/iowa", response_class=HTMLResponse)
def iowa_browse(slug: str, instrument: str):
    try:
        links = iowa_lib.fetch_links(instrument)
    except Exception as e:
        return _page("Iowa MIS", f'<a class="back" href="/entry/{html.escape(slug)}">&larr; back</a><div class="msg err">{html.escape(str(e))}</div>')

    rows = []
    for link in links:
        filename = link.rsplit("/", 1)[-1]
        desc = iowa_lib._describe(filename)
        rows.append(f"""<div class="file-row">
            <span>{html.escape(filename)} <span style="color:#7a7a80">({html.escape(desc)})</span></span>
            <form method="post" action="/entry/{html.escape(slug)}/iowa/download" style="margin:0">
                <input type="hidden" name="instrument" value="{html.escape(instrument)}">
                <input type="hidden" name="link" value="{html.escape(link)}">
                <button type="submit" class="secondary" style="padding:4px 10px;margin:0">Download</button>
            </form>
        </div>""")

    return _page(f"Iowa MIS — {instrument}", f"""
    <a class="back" href="/entry/{html.escape(slug)}">&larr; back to {html.escape(slug)}</a>
    <h2>{len(links)} file(s) for {html.escape(instrument)}</h2>
    <div class="card">{''.join(rows)}</div>
    """)


@app.post("/entry/{slug}/iowa/download", response_class=HTMLResponse)
def iowa_download(slug: str, instrument: str = Form(...), link: str = Form(...)):
    from urllib.parse import quote
    import httpx
    filename = link.rsplit("/", 1)[-1]
    out_dir = os.path.join(_IOWA_DOWNLOAD_DIR, instrument)
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, filename)
    try:
        resp = httpx.get(f"{iowa_lib.BASE}/{quote(link)}", timeout=60.0, follow_redirects=True)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            f.write(resp.content)
    except Exception as e:
        return entry_detail(slug, err=f"Iowa download failed: {e}")
    return entry_detail(slug, msg=f"Downloaded {filename} to {dest} — pick it in the Real clip field above.")


@app.post("/entry/{slug}/upload", response_class=HTMLResponse)
async def upload(
    slug: str,
    printed: UploadFile = File(...),
    real: list[UploadFile] = File(...),
    phrase: str = Form(...),
    real_source: str = Form(...),
    real_license: str = Form(...),
):
    db = SessionLocal()
    entry = _entry_or_404(db, slug)
    if entry is None:
        return _page("Not found", '<p>No such entry.</p><a href="/">&larr; back</a>')

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            printed_path = os.path.join(tmpdir, f"printed-{printed.filename}")
            with open(printed_path, "wb") as f:
                f.write(await printed.read())

            real_paths = []
            for i, uf in enumerate(real):
                p = os.path.join(tmpdir, f"real-{i}-{uf.filename}")
                with open(p, "wb") as f:
                    f.write(await uf.read())
                real_paths.append(p)

            printed_bytes, printed_dur = ingest_lib._prepare_clip(printed_path, tmpdir, "printed", ingest_lib.TARGET_LUFS)
            real_bytes, real_dur = ingest_lib._prepare_clip(",".join(real_paths), tmpdir, "real", ingest_lib.TARGET_LUFS)

        printed_url = upload_audio(printed_bytes)
        real_url = upload_audio(real_bytes)

        from datetime import datetime
        now = datetime.utcnow().isoformat()
        kept = [m for m in (entry.media or []) if m.get("kind") not in ("audio_printed", "audio_real")]
        entry.media = kept + [
            {"kind": "audio_printed", "url": printed_url, "phrase": phrase, "ingested_at": now},
            {"kind": "audio_real", "url": real_url, "phrase": phrase, "source": real_source, "license": real_license, "ingested_at": now},
        ]
        db.commit()
    except Exception as e:
        return entry_detail(slug, err=f"Upload failed: {e}")

    return entry_detail(slug, msg=f"Saved — printed {printed_dur:.1f}s, real {real_dur:.1f}s, both normalized to {ingest_lib.TARGET_LUFS} LUFS.")


@app.post("/entry/{slug}/score", response_class=HTMLResponse)
def compute_score(slug: str):
    try:
        import librosa  # noqa: F401
    except ImportError:
        return entry_detail(slug, err="librosa isn't installed. Run: pip install -r backend/scripts/requirements-audio-scoring.txt")

    db = SessionLocal()
    entry = _entry_or_404(db, slug)
    media = entry.media or []
    printed = next((m for m in media if m.get("kind") == "audio_printed"), None)
    real = next((m for m in media if m.get("kind") == "audio_real"), None)
    if not printed or not real:
        return entry_detail(slug, err="Both clips must be uploaded first.")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            printed_path = os.path.join(tmpdir, "printed.mp3")
            real_path = os.path.join(tmpdir, "real.mp3")
            score_lib._download(printed["url"], printed_path)
            score_lib._download(real["url"], real_path)
            score = score_lib.compute_similarity(printed_path, real_path)
        entry.objective_score = score
        db.commit()
    except Exception as e:
        return entry_detail(slug, err=f"Scoring failed: {e}")

    return entry_detail(slug, msg=f"Objective score: {score}")


def _open_browser():
    webbrowser.open("http://127.0.0.1:8899")


if __name__ == "__main__":
    threading.Timer(1.0, _open_browser).start()
    print("Instruments Audio Admin — http://127.0.0.1:8899 (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=8899, log_level="warning")
