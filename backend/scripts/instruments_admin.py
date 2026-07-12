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
import subprocess
import sys
import tempfile
import threading
import webbrowser
from datetime import datetime

import yaml

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)
sys.path.insert(0, _BACKEND_DIR)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

from fastapi import FastAPI, Form, Request, UploadFile, File  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
import uvicorn  # noqa: E402

from models import FilamentPrice, RegistryEntry, SessionLocal  # noqa: E402
from storage import upload_audio  # noqa: E402
from instruments_pricing import compute_costs, staleness_state  # noqa: E402

# Sibling scripts, imported for their functions (not their CLI __main__ block).
import ingest_instrument_audio as ingest_lib  # noqa: E402
import score_instrument_audio as score_lib  # noqa: E402
import iowa_mis_fetch as iowa_lib  # noqa: E402
import seed_instruments as seed_lib  # noqa: E402
import import_service  # noqa: E402 — reuses the same OG-image scraper print imports use

# Everything below this exact line in seed/instruments_overlay.yaml is
# machine-managed — read verbatim as "header", regenerated as YAML on save.
# Must match the marker text written into that file's own header comment
# (see seed/instruments_overlay.yaml) — that's what lets the save path
# preserve the format-documentation comments PyYAML's dumper would
# otherwise silently drop.
_OVERLAY_MARKER = "# ---- machine-managed below this line by instruments_admin.py — hand-edit if you want, the format above still applies ----"
_OVERLAY_PATH = os.path.join(_REPO_ROOT, "seed", "instruments_overlay.yaml")

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


class OverlayWriteError(Exception):
    pass


def _read_overlay_header_and_data():
    """Split the overlay file into (header_text_including_marker, data_dict).
    Missing marker (e.g. someone hand-restored an old copy) -> whole file
    becomes header, data starts empty, marker gets appended back on write."""
    if not os.path.exists(_OVERLAY_PATH):
        return _OVERLAY_MARKER, {}
    with open(_OVERLAY_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    if _OVERLAY_MARKER in content:
        header, _, data_text = content.partition(_OVERLAY_MARKER)
        header = header.rstrip("\n") + "\n" + _OVERLAY_MARKER
    else:
        header = content.rstrip("\n") + "\n\n" + _OVERLAY_MARKER
        data_text = ""
    data = yaml.safe_load(data_text) or {}
    return header, data


def _write_overlay(header: str, data: dict) -> None:
    """Atomic + self-verifying: write to a temp file, re-parse it, confirm
    the parsed data matches what we intended, only then replace the real
    file. A malformed write to the source of truth every entry's pricing
    depends on is the one failure mode this must never have."""
    dumped = yaml.safe_dump(data, sort_keys=True, default_flow_style=False, allow_unicode=True)
    new_content = header.rstrip("\n") + "\n\n" + dumped
    tmp_path = _OVERLAY_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    with open(tmp_path, "r", encoding="utf-8") as f:
        written = f.read()
    _, _, written_data_text = written.partition(_OVERLAY_MARKER)
    reparsed = yaml.safe_load(written_data_text) or {}
    if reparsed != data:
        os.remove(tmp_path)
        raise OverlayWriteError("YAML round-trip verification failed — refusing to write")
    os.replace(tmp_path, _OVERLAY_PATH)


def _maybe_commit_overlay(slug: str, summary: str) -> str:
    """Best-effort, local-only commit of just the overlay file — never
    pushes, never blocks the save if it fails (dirty worktree, no git, etc).
    Opt-in per save (the caller only invokes this when the form's checkbox
    is ticked), so it never surprises anyone mid-testing."""
    try:
        subprocess.run(
            ["git", "add", "seed/instruments_overlay.yaml"],
            cwd=_REPO_ROOT, check=True, capture_output=True, timeout=10,
        )
        result = subprocess.run(
            ["git", "commit", "-m", f"pricing({slug}): {summary}"],
            cwd=_REPO_ROOT, capture_output=True, timeout=10, text=True,
        )
        if result.returncode != 0:
            return f"(git commit skipped: {result.stdout.strip() or result.stderr.strip()})"
        return "committed locally (not pushed)."
    except Exception as e:
        return f"(git commit skipped: {e})"


MAX_FILAMENT_ROWS = 4
MAX_FULFILLMENT_ROWS = 3


def _parse_positive_float(value: str, field_name: str) -> float:
    try:
        f = float(value)
    except ValueError:
        raise ValueError(f"{field_name}: {value!r} isn't a number")
    if f <= 0:
        raise ValueError(f"{field_name}: must be positive")
    return f


def _validate_url(value: str, field_name: str) -> str:
    if not (value.startswith("http://") or value.startswith("https://")):
        raise ValueError(f"{field_name}: must start with http:// or https://")
    return value


def _build_overlay_entry(form, bom_items: list, now_iso: str) -> dict:
    """Rebuilds the whole overlay block for one slug from submitted form
    fields — not an incremental merge, so removing a row and re-saving
    actually removes it rather than leaving a stale row behind. Raises
    ValueError with a form-facing message on any bad input."""
    entry = {}

    filament_usage = []
    for i in range(1, MAX_FILAMENT_ROWS + 1):
        material = (form.get(f"fu_material_{i}") or "").strip()
        grams_raw = (form.get(f"fu_grams_{i}") or "").strip()
        if not material and not grams_raw:
            continue
        if not material or not grams_raw:
            raise ValueError(f"Filament row {i}: material and grams are both required together")
        filament_usage.append({"material": material, "grams": _parse_positive_float(grams_raw, f"Filament row {i} grams")})
    if filament_usage:
        entry["filament_usage"] = filament_usage

    fidelity_axis = (form.get("fidelity_axis") or "").strip()
    if fidelity_axis:
        entry["fidelity_axis"] = int(fidelity_axis)
    effort_print_load = (form.get("effort_print_load") or "").strip()
    if effort_print_load:
        entry["effort_print_load"] = effort_print_load
    effort_assembly_skill = (form.get("effort_assembly_skill") or "").strip()
    if effort_assembly_skill:
        entry["effort_assembly_skill"] = int(effort_assembly_skill)

    bom_fulfillments = []
    for bom_idx, bom_item in enumerate(bom_items):
        fulfillments = []
        for i in range(1, MAX_FULFILLMENT_ROWS + 1):
            vendor = (form.get(f"bom_{bom_idx}_vendor_{i}") or "").strip()
            url_raw = (form.get(f"bom_{bom_idx}_url_{i}") or "").strip()
            price_raw = (form.get(f"bom_{bom_idx}_price_{i}") or "").strip()
            if not (vendor or url_raw or price_raw):
                continue
            label = f"{bom_item['spec'][:40]} fulfillment {i}"
            if not (vendor and url_raw and price_raw):
                raise ValueError(f"{label}: vendor, URL, and price are all required together")
            fulfillments.append({
                "vendor": vendor,
                "url": _validate_url(url_raw, f"{label} URL"),
                "price": _parse_positive_float(price_raw, f"{label} price"),
                "currency": (form.get(f"bom_{bom_idx}_currency_{i}") or "USD").strip() or "USD",
                "checked_at": now_iso,
            })
        if fulfillments:
            bom_fulfillments.append({"spec": bom_item["spec"], "fulfillments": fulfillments})
    if bom_fulfillments:
        entry["bom_fulfillments"] = bom_fulfillments

    for field in ("retail_budget", "retail_premium"):
        price_raw = (form.get(f"{field}_price") or "").strip()
        url_raw = (form.get(f"{field}_url") or "").strip()
        if not price_raw and not url_raw:
            continue
        label = field.replace("_", " ").title()
        if not (price_raw and url_raw):
            raise ValueError(f"{label}: price and URL are both required together")
        entry[field] = {
            "price": _parse_positive_float(price_raw, f"{label} price"),
            "url": _validate_url(url_raw, f"{label} URL"),
            "checked_at": now_iso,
        }

    return entry


def _prefill(overlay_entry: dict, bom_items: list) -> dict:
    """Flat dict of form-field-name -> value, for populating the edit form
    from whatever's already saved for this slug."""
    values = {}
    for i, row in enumerate(overlay_entry.get("filament_usage", [])[:MAX_FILAMENT_ROWS], start=1):
        values[f"fu_material_{i}"] = row.get("material", "")
        values[f"fu_grams_{i}"] = row.get("grams", "")

    values["fidelity_axis"] = overlay_entry.get("fidelity_axis", "")
    values["effort_print_load"] = overlay_entry.get("effort_print_load", "")
    values["effort_assembly_skill"] = overlay_entry.get("effort_assembly_skill", "")

    by_spec = {bf.get("spec"): bf for bf in overlay_entry.get("bom_fulfillments", [])}
    for bom_idx, bom_item in enumerate(bom_items):
        bf = by_spec.get(bom_item["spec"])
        if not bf:
            continue
        for i, f in enumerate(bf.get("fulfillments", [])[:MAX_FULFILLMENT_ROWS], start=1):
            values[f"bom_{bom_idx}_vendor_{i}"] = f.get("vendor", "")
            values[f"bom_{bom_idx}_url_{i}"] = f.get("url", "")
            values[f"bom_{bom_idx}_price_{i}"] = f.get("price", "")
            values[f"bom_{bom_idx}_currency_{i}"] = f.get("currency", "USD")

    for field in ("retail_budget", "retail_premium"):
        block = overlay_entry.get(field) or {}
        values[f"{field}_price"] = block.get("price", "")
        values[f"{field}_url"] = block.get("url", "")

    return values


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
        pricing_badge = '<span class="badge yes">pricing ✓</span>' if e.filament_usage else '<span class="badge">no pricing</span>'
        rows.append(f"""<div class="entry-row">
            <a href="/entry/{html.escape(e.slug)}">{html.escape(e.name)}</a>
            <span>{audio_badge} {pricing_badge} {score_badge}</span>
        </div>""")
    return _page("Entries", f"""
    <p>Pick an entry to add or replace its audio A/B pair, or edit its pricing/BOM/retail data.
    <a href="/prices">Manage filament $/kg prices</a></p>
    <div class="card">{''.join(rows)}</div>
    """)


@app.get("/prices", response_class=HTMLResponse)
def prices_page(msg: str = "", err: str = ""):
    db = SessionLocal()
    rows = db.query(FilamentPrice).order_by(FilamentPrice.material).all()
    banner = f'<div class="msg ok">{html.escape(msg)}</div>' if msg else (f'<div class="msg err">{html.escape(err)}</div>' if err else "")
    existing_rows = "".join(
        f'<div class="file-row"><span>{html.escape(p.material)}</span><span>${p.price_per_kg:.2f}/kg</span></div>'
        for p in rows
    ) or '<p style="color:#7a7a80">No prices set yet — costs show "pending verification" until a material used in filament_usage has a price here.</p>'
    return _page("Filament prices", f"""
    <a class="back" href="/">&larr; all entries</a>
    <h1>Filament $/kg prices</h1>
    <p style="color:#a8a8ae">Global lookup, not per-entry — compute_costs() reads this table by material name (must match filament_usage's "material" string exactly).</p>
    {banner}
    <div class="card">{existing_rows}</div>
    <h2>Add / update a price</h2>
    <div class="card">
        <form method="post" action="/prices/save">
            <label>Material (must match filament_usage entries exactly, e.g. "PLA")</label>
            <input type="text" name="material" required>
            <label>Price per kg (USD)</label>
            <input type="text" name="price_per_kg" placeholder="18.99" required>
            <button type="submit">Save</button>
        </form>
    </div>
    """)


@app.post("/prices/save", response_class=HTMLResponse)
def prices_save(material: str = Form(...), price_per_kg: str = Form(...)):
    material = material.strip()
    try:
        price = _parse_positive_float(price_per_kg.strip(), "Price per kg")
    except ValueError as e:
        return prices_page(err=str(e))

    db = SessionLocal()
    row = db.query(FilamentPrice).filter(FilamentPrice.material == material).first()
    if row:
        row.price_per_kg = price
        row.updated_at = datetime.utcnow()
    else:
        db.add(FilamentPrice(material=material, price_per_kg=price, updated_at=datetime.utcnow()))
    db.commit()
    return prices_page(msg=f"Saved {material} = ${price:.2f}/kg")


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
    <p><a href="/entry/{html.escape(slug)}/pricing">Edit pricing / BOM / retail &amp; fidelity-effort &rarr;</a></p>
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


def _cost_summary_html(entry, db) -> str:
    price_table = {p.material: p.price_per_kg for p in db.query(FilamentPrice).all()}
    cost = compute_costs(entry, price_table)
    if cost["spool"] is None:
        return '<p class="msg err" style="margin-top:0">Cost: pending verification — either no filament_usage yet, or a material used isn\'t in <a href="/prices">the $/kg price table</a>.</p>'
    if cost["build"] is None:
        return f'<p class="msg err" style="margin-top:0">Spool: ${cost["spool"]:.2f} — Cost: source needed (a BOM item has no usable fulfillment yet).</p>'
    lo, hi = cost["build"]
    build_str = f"${lo:.2f}" if round(lo) == round(hi) else f"${lo:.2f}–${hi:.2f}"
    play_str = ""
    if cost["play"] is not None:
        plo, phi = cost["play"]
        play_str = f' &middot; Play-ready {("$%.2f" % plo) if round(plo) == round(phi) else f"${plo:.2f}–${phi:.2f}"}'
    return f'<p class="msg ok" style="margin-top:0">Spool ${cost["spool"]:.2f} &middot; Build {build_str}{play_str}</p>'


def entry_pricing_page(slug: str, msg: str = "", err: str = ""):
    db = SessionLocal()
    entry = _entry_or_404(db, slug)
    if entry is None:
        return _page("Not found", '<p>No such entry.</p><a href="/">&larr; back</a>')

    bom_items = entry.bom or []
    header, overlay_data = _read_overlay_header_and_data()
    overlay_entry = overlay_data.get(slug, {})
    values = _prefill(overlay_entry, bom_items)

    banner = f'<div class="msg ok">{html.escape(msg)}</div>' if msg else (f'<div class="msg err">{html.escape(err)}</div>' if err else "")

    v = lambda k: html.escape(str(values.get(k, "")))  # noqa: E731

    filament_rows = "".join(f"""
        <div style="display:flex;gap:10px;margin-bottom:6px">
            <input type="text" name="fu_material_{i}" value="{v(f'fu_material_{i}')}" placeholder="Material, e.g. PLA" style="flex:2">
            <input type="text" name="fu_grams_{i}" value="{v(f'fu_grams_{i}')}" placeholder="Grams" style="flex:1">
        </div>""" for i in range(1, MAX_FILAMENT_ROWS + 1))

    bom_sections = ""
    if bom_items:
        for bom_idx, item in enumerate(bom_items):
            rows = "".join(f"""
                <div style="display:flex;gap:8px;margin-bottom:6px">
                    <input type="text" name="bom_{bom_idx}_vendor_{i}" value="{v(f'bom_{bom_idx}_vendor_{i}')}" placeholder="Vendor" style="flex:1">
                    <input type="text" name="bom_{bom_idx}_url_{i}" value="{v(f'bom_{bom_idx}_url_{i}')}" placeholder="https://..." style="flex:2">
                    <input type="text" name="bom_{bom_idx}_price_{i}" value="{v(f'bom_{bom_idx}_price_{i}')}" placeholder="Price" style="flex:1">
                    <input type="text" name="bom_{bom_idx}_currency_{i}" value="{v(f'bom_{bom_idx}_currency_{i}') or 'USD'}" placeholder="USD" style="flex:0 0 60px">
                </div>""" for i in range(1, MAX_FULFILLMENT_ROWS + 1))
            bom_sections += f"""
            <p style="margin:14px 0 6px;color:#c8c8cc">{html.escape(item.get('spec', ''))}</p>
            {rows}"""
    else:
        bom_sections = '<p style="color:#7a7a80">Fully printed — no BOM parts to source for this entry.</p>'

    fidelity_opts = "".join(f'<option value="{n}" {"selected" if str(values.get("fidelity_axis")) == str(n) else ""}>{n}</option>' for n in range(0, 6))
    effort_load_opts = "".join(f'<option value="{o}" {"selected" if values.get("effort_print_load") == o else ""}>{o}</option>' for o in ("", "S", "M", "L", "XL"))
    effort_skill_opts = "".join(f'<option value="{n}" {"selected" if str(values.get("effort_assembly_skill")) == str(n) else ""}>{n}</option>' for n in range(1, 6))

    return _page(f"{entry.name} — pricing", f"""
    <a class="back" href="/entry/{html.escape(slug)}">&larr; {html.escape(entry.name)}</a>
    <h1>{html.escape(entry.name)} — pricing / BOM / retail</h1>
    {banner}
    {_cost_summary_html(entry, db)}

    <form method="post" action="/entry/{html.escape(slug)}/pricing/save">
        <h2>Filament usage</h2>
        <div class="card">
            {filament_rows}
            <p style="color:#7a7a80;font-size:0.8rem;margin:6px 0 0">Material name must exactly match a row in <a href="/prices">the $/kg price table</a>.</p>
        </div>

        <h2>Fidelity &amp; effort</h2>
        <div class="card">
            <label>Sound fidelity (0-5, how close it sounds to the real instrument)</label>
            <select name="fidelity_axis"><option value="">&mdash;</option>{fidelity_opts}</select>
            <label>Print load (S/M/L/XL)</label>
            <select name="effort_print_load">{effort_load_opts}</select>
            <label>Assembly skill (1-5)</label>
            <select name="effort_assembly_skill"><option value="">&mdash;</option>{effort_skill_opts}</select>
        </div>

        <h2>BOM fulfillments</h2>
        <div class="card">{bom_sections}</div>

        <h2>Retail comparison</h2>
        <div class="card">
            <label>Budget option</label>
            <div style="display:flex;gap:10px">
                <input type="text" name="retail_budget_price" value="{v('retail_budget_price')}" placeholder="Price" style="flex:1">
                <input type="text" name="retail_budget_url" value="{v('retail_budget_url')}" placeholder="https://..." style="flex:2">
            </div>
            <label style="margin-top:14px">Premium option</label>
            <div style="display:flex;gap:10px">
                <input type="text" name="retail_premium_price" value="{v('retail_premium_price')}" placeholder="Price" style="flex:1">
                <input type="text" name="retail_premium_url" value="{v('retail_premium_url')}" placeholder="https://..." style="flex:2">
            </div>
        </div>

        <div class="card">
            <label style="display:flex;align-items:center;gap:8px;margin:0"><input type="checkbox" name="auto_commit" style="width:auto"> Also commit seed/instruments_overlay.yaml to git (local only, never pushed)</label>
        </div>

        <button type="submit">Save &amp; apply</button>
    </form>
    """)


@app.get("/entry/{slug}/pricing", response_class=HTMLResponse)
def entry_pricing_get(slug: str):
    return entry_pricing_page(slug)


@app.post("/entry/{slug}/pricing/save", response_class=HTMLResponse)
async def entry_pricing_save(slug: str, request: Request):
    db = SessionLocal()
    entry = _entry_or_404(db, slug)
    if entry is None:
        return _page("Not found", '<p>No such entry.</p><a href="/">&larr; back</a>')

    form = await request.form()
    bom_items = entry.bom or []
    now_iso = datetime.utcnow().isoformat()

    try:
        new_entry_block = _build_overlay_entry(form, bom_items, now_iso)
    except ValueError as e:
        return entry_pricing_page(slug, err=str(e))

    header, overlay_data = _read_overlay_header_and_data()
    if new_entry_block:
        overlay_data[slug] = new_entry_block
    else:
        overlay_data.pop(slug, None)  # everything cleared -> remove the block entirely

    try:
        _write_overlay(header, overlay_data)
    except OverlayWriteError as e:
        return entry_pricing_page(slug, err=f"Save failed, nothing was written: {e}")

    try:
        seed_lib.run(dry_run=False)
    except Exception as e:
        return entry_pricing_page(slug, err=f"Saved to the overlay file, but reseeding failed: {e}")

    commit_note = ""
    if form.get("auto_commit"):
        commit_note = " " + _maybe_commit_overlay(slug, f"{entry.name} — filament/BOM/retail update")

    return entry_pricing_page(slug, msg=f"Saved and applied.{commit_note}")


def _open_browser():
    webbrowser.open("http://127.0.0.1:8899")


if __name__ == "__main__":
    threading.Timer(1.0, _open_browser).start()
    print("Instruments Audio Admin — http://127.0.0.1:8899 (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=8899, log_level="warning")
