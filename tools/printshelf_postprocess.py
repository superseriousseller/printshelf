#!/usr/bin/env python3
"""PrintShelf slicer post-processing script.

Add this in your slicer as a Post-processing Script:
  - Bambu Studio / OrcaSlicer: enable the Advanced toggle, then
    Print Settings -> Others -> Post-processing Scripts.
  - PrusaSlicer: Expert mode -> Print Settings -> Output options.

Paste (edit the path to where you saved this file):

    /usr/bin/python3 "/path/to/printshelf_postprocess.py"

It runs during slicing (Bambu Studio shows a "Security Warning" that a
post-processing script will run -- expected; click Execute). It reads the sliced
G-code header (filament, colors, print time, layer height, infill, supports,
printer) and logs the print to your PrintShelf account via the API. It never
modifies the G-code and always exits 0, so it can't break your slicing/printing.

Stdlib only — no pip installs. Works with Python 3.8+.

Grab a ready-to-use copy with your key already filled in from:
    PrintShelf -> Dashboard -> Connect your slicer
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Config — the download from "Connect your slicer" fills API_KEY/BASE_URL in.
# You can also set PRINTSHELF_API_KEY / PRINTSHELF_BASE_URL as env vars.
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("PRINTSHELF_API_KEY", "__PRINTSHELF_API_KEY__")
BASE_URL = os.environ.get("PRINTSHELF_BASE_URL", "__PRINTSHELF_BASE_URL__").rstrip("/")

# Sentinel for "still the un-personalized template." Assembled from two pieces so
# the download's replacement of the placeholder above never rewrites THIS line too.
_UNCONFIGURED_KEY = "__PRINTSHELF" + "_API_KEY__"

# Diagnostic: when True, also write every SLIC3R_* env var + argv to a dump file
# so we can see exactly what the slicer passes. Set False once you're set up.
DEBUG = True
DEBUG_PATH = os.path.join(os.path.expanduser("~"), "printshelf_debug.log")

IS_PUBLIC = False      # False = private (review & publish later); True = straight to your public profile
QUEUED = False         # True = add to your queue instead of logging as printed
STATUS = "printed"     # printed | printing | failed | partial (what to log the print as)
TIMEOUT = 10           # seconds for the API call

LOG_PATH = os.path.join(os.path.expanduser("~"), "printshelf_postprocess.log")


def log(msg):
    try:
        with open(LOG_PATH, "a") as fh:
            fh.write(msg.rstrip() + "\n")
    except Exception:
        pass
    sys.stderr.write("[printshelf] " + msg.rstrip() + "\n")


def read_comments(path):
    """Return the raw text of the G-code (header + trailing config block)."""
    with open(path, "r", errors="ignore") as fh:
        return fh.read()


def grab(text, *patterns):
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).strip().strip('"')
    return None


def split_list(val):
    if not val:
        return []
    return [x.strip().strip('"') for x in re.split(r"[;,]", val) if x.strip()]


def parse_time_to_mins(val):
    """'1h 6m 27s' / '2d 3h' / '45m' -> integer minutes."""
    if not val:
        return None
    total = 0.0
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([dhms])", val, re.IGNORECASE):
        num = float(num)
        unit = unit.lower()
        total += num * {"d": 1440, "h": 60, "m": 1, "s": 1 / 60.0}[unit]
    return int(round(total)) if total else None


FINISH_WORDS = ["Silk", "Matte", "Glow", "Wood", "Marble", "Sparkle", "Metal",
                "Carbon", "CF", "Luminous", "Translucent", "Transparent", "Satin"]


def detect_finish(settings_id):
    if not settings_id:
        return None
    for w in FINISH_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", settings_id, re.IGNORECASE):
            return "Carbon Fiber" if w.upper() == "CF" else w
    return None


def dump_debug(path):
    """Write argv + SLIC3R_PP_OUTPUT_NAME + all SLIC3R_* env vars to DEBUG_PATH."""
    try:
        out = ["=== PrintShelf post-process debug ==="]
        out.append("argv                  = %r" % (sys.argv,))
        out.append("gcode basename        = %s" % os.path.basename(path or ""))
        out.append("SLIC3R_PP_OUTPUT_NAME = %s" % os.environ.get("SLIC3R_PP_OUTPUT_NAME", "<unset>"))
        out.append("SLIC3R_PP_HOST        = %s" % os.environ.get("SLIC3R_PP_HOST", "<unset>"))
        out.append("--- all SLIC3R_* env vars (values truncated to 200 chars) ---")
        for k in sorted(os.environ):
            if k.upper().startswith("SLIC3R"):
                v = os.environ[k].replace("\n", "\\n")
                if len(v) > 200:
                    v = v[:200] + " …(%d chars)" % len(os.environ[k])
                out.append("%s = %s" % (k, v))
        out.append("--- gcode header lines (usage / time / model) ---")
        try:
            with open(path, errors="ignore") as gh:
                for ln in gh:
                    if len(ln) < 200 and re.search(
                            r"filament used|total filament|filament weight|printing time|model printing|^; model",
                            ln, re.IGNORECASE):
                        out.append(ln.rstrip())
        except Exception:
            pass
        # The gcode lives INSIDE the slicer's unpacked 3MF project dir. Its siblings
        # (3D/3dmodel.model, Metadata/*.config, plate_*.png) usually hold the real
        # model title, designer, MakerWorld design id, and a thumbnail render.
        try:
            proj = os.path.dirname(os.path.dirname(os.path.abspath(path)))
            out.append("--- project dir listing: %s ---" % proj)
            for root, _dirs, files in os.walk(proj):
                for fn in sorted(files):
                    fp = os.path.join(root, fn)
                    try:
                        sz = os.path.getsize(fp)
                    except OSError:
                        sz = -1
                    out.append("  %s (%d bytes)" % (os.path.relpath(fp, proj), sz))
            for rel in ("3D/3dmodel.model", "Metadata/model_settings.config",
                        "Metadata/slice_info.config", "Metadata/project_settings.config"):
                fp = os.path.join(proj, rel)
                if os.path.exists(fp):
                    try:
                        txt = open(fp, errors="ignore").read()
                        out.append("--- %s (first 2500 chars) ---" % rel)
                        out.append(txt[:2500])
                    except Exception:
                        pass
        except Exception:
            pass
        with open(DEBUG_PATH, "w") as fh:
            fh.write("\n".join(out) + "\n")
        log("debug env dumped to %s" % DEBUG_PATH)
    except Exception as e:
        log("debug dump failed: %s" % e)


def _clean_model_name(raw):
    """Turn a source filename / object name into a human title.
    e.g. 'kazoo_mw(2).3mf' -> 'Kazoo', 'kazoo.stl_5' -> 'Kazoo'."""
    name = os.path.basename(raw or "")
    name = re.sub(r"\.stl_\d+$", "", name, flags=re.IGNORECASE)                # 'kazoo.stl_5'
    name = re.sub(r"\.(3mf|stl|obj|step|stp|gcode|gco|g|bgcode)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*\(\d+\)$", "", name)                                   # drop '(2)' download suffix
    name = re.sub(r"[ _-]*(mw|makerworld)$", "", name, flags=re.IGNORECASE)     # drop MakerWorld export marker
    name = re.sub(r"[ _-]*plate[ _-]*\d+$", "", name, flags=re.IGNORECASE)      # drop '_plate_1'
    name = name.replace("_", " ").strip()
    if not name or re.fullmatch(r"[\d.\s]+", name):                            # reject junk like '.23792.0'
        return None
    return name[0].upper() + name[1:]


def derive_title(gcode_path):
    """Bambu hands us a temp gcode ('.23792.1.gcode') with no model name, but the
    gcode sits in an unpacked project dir. Recover the real name from:
      1) origin.txt — the source file the user opened (e.g. '.../kazoo_mw(2).3mf')
      2) the project .3mf's Metadata/model_settings.config object name
    Returns None if neither yields a usable name (caller uses a dated fallback)."""
    proj = os.path.dirname(os.path.dirname(os.path.abspath(gcode_path)))
    try:
        with open(os.path.join(proj, "origin.txt"), errors="ignore") as fh:
            t = _clean_model_name(fh.read().strip())
            if t:
                return t
    except Exception:
        pass
    try:
        import zipfile
        zp = os.path.join(proj, ".3mf")
        if os.path.exists(zp):
            with zipfile.ZipFile(zp) as z:
                data = z.read("Metadata/model_settings.config").decode("utf-8", "ignore")
                m = re.search(r'key="name"\s+value="([^"]+)"', data)
                if m:
                    t = _clean_model_name(m.group(1))
                    if t:
                        return t
    except Exception:
        pass
    return None


def _env(key):
    return os.environ.get("SLIC3R_" + key)


def _env_semi_list(key):
    """Slicer config string-lists are ';'-separated and sometimes quoted."""
    v = _env(key)
    if not v:
        return []
    return [x.strip().strip('"').strip() for x in v.split(";") if x.strip()]


def _used_grams_from_gcode(text):
    """Per-filament grams from the gcode header ('; filament used [g] = a,b,c').
    Returns a list of floats, or [] if not found. Used to keep only slots that printed."""
    m = re.search(r"^;\s*filament used \[g\]\s*[:=]\s*([\d.,\s]+)$", text, re.IGNORECASE | re.MULTILINE)
    if not m:
        return []
    return [float(x) for x in re.findall(r"[\d.]+", m.group(1))]


def build_payload(path):
    text = read_comments(path)

    # Filament identity comes from the clean SLIC3R_* env vars when present
    # (Bambu passes them as ';'-separated per-slot lists); fall back to gcode comments.
    types = _env_semi_list("FILAMENT_TYPE") or split_list(grab(text, r"^;\s*filament_type\s*[:=]\s*(.+)$"))
    colors = _env_semi_list("FILAMENT_COLOUR") or split_list(grab(text, r"^;\s*filament_colour\s*[:=]\s*(.+)$",
                             r"^;\s*filament_color\s*[:=]\s*(.+)$", r"^;\s*extruder_colour\s*[:=]\s*(.+)$"))
    vendors = _env_semi_list("FILAMENT_VENDOR") or split_list(grab(text, r"^;\s*filament_vendor\s*[:=]\s*(.+)$"))
    settings_ids = _env_semi_list("FILAMENT_SETTINGS_ID") or split_list(grab(text, r"^;\s*filament_settings_id\s*[:=]\s*(.+)$"))

    # Keep only slots that actually printed (per-slot grams > 0), if the gcode tells us.
    used = _used_grams_from_gcode(text)

    filaments = []
    seen = set()
    for i, mat in enumerate(types):
        if used and i < len(used) and used[i] <= 0:
            continue  # this AMS slot wasn't used in this print
        sid = settings_ids[i] if i < len(settings_ids) else None
        vendor = vendors[i] if i < len(vendors) else None
        if not vendor and sid:
            vendor = sid.split()[0]  # e.g. "Bambu PLA Basic ..." -> "Bambu"
        hexv = colors[i] if i < len(colors) else None
        if hexv and not hexv.startswith("#"):
            hexv = None
        key = (mat.lower(), (hexv or "").lower(), (vendor or "").lower())
        if key in seen:
            continue  # collapse identical spools
        seen.add(key)
        filaments.append({
            "material": mat,
            "color_hex": hexv,
            "brand": (vendor or None),
            "finish": detect_finish(sid),
        })

    layer = _env("LAYER_HEIGHT") or grab(text, r"^;\s*layer_height\s*[:=]\s*([\d.]+)")
    infill = _env("SPARSE_INFILL_DENSITY") or grab(text, r"^;\s*sparse_infill_density\s*[:=]\s*([\d.]+)",
                  r"^;\s*fill_density\s*[:=]\s*([\d.]+)")
    supports_raw = _env("ENABLE_SUPPORT") or grab(text, r"^;\s*enable_support\s*[:=]\s*(\S+)",
                        r"^;\s*support_material\s*[:=]\s*(\S+)")
    time_raw = grab(text,
                    r"estimated printing time.*?[:=]\s*([^;\n]+)",
                    r"model printing time\s*[:=]\s*([^;\n]+)",
                    r"total estimated time\s*[:=]\s*([^;\n]+)")
    used_raw = grab(text,
                    r"total filament used \[g\]\s*[:=]\s*([\d.,\s]+)",
                    r"filament used \[g\]\s*[:=]\s*([\d.,\s]+)",
                    r"total filament weight \[g\]\s*[:=]\s*([\d.,\s]+)")
    printer = _env("PRINTER_MODEL") or grab(text, r"^;\s*printer_model\s*[:=]\s*(.+)$",
                   r"^;\s*printer_settings_id\s*[:=]\s*(.+)$")

    used_g = None
    if used_raw:
        nums = [float(x) for x in re.findall(r"[\d.]+", used_raw)]
        if nums:
            used_g = round(sum(nums), 2)

    supports = None
    if supports_raw is not None:
        supports = supports_raw.strip().lower() in {"1", "true", "yes", "on"}

    title = derive_title(path)
    if not title:
        title = (printer + " · " if printer else "Print · ") + time.strftime("%b %d, %I:%M%p")

    return {
        "title": title,
        "printer": printer,
        "filaments": [f for f in filaments if f.get("material")],
        "layer_height": float(layer) if layer else None,
        "infill_pct": int(round(float(str(infill).rstrip("%")))) if infill else None,
        "supports": supports,
        "print_time_mins": parse_time_to_mins(time_raw),
        "filament_used_g": used_g,
        "status": STATUS,
        "queued": QUEUED,
        "is_public": IS_PUBLIC,
    }


def find_image(gcode_path):
    """Find a cover image in the slicer's project dir next to the gcode.
    Prefers the model's own pictures (MakerWorld gallery), falls back to the
    rendered plate thumbnail (present for any Bambu slice)."""
    proj = os.path.dirname(os.path.dirname(os.path.abspath(gcode_path)))
    picdir = os.path.join(proj, "Auxiliaries", "Model Pictures")
    cands = []
    if os.path.isdir(picdir):
        for fn in os.listdir(picdir):
            if fn.lower().endswith((".webp", ".png", ".jpg", ".jpeg")):
                cands.append(os.path.join(picdir, fn))
    if cands:
        return max(cands, key=lambda f: os.path.getsize(f))  # largest = main cover
    for rel in ("Metadata/plate_1.png", "Metadata/plate_no_light_1.png", "Metadata/top_1.png"):
        fp = os.path.join(proj, rel)
        if os.path.exists(fp):
            return fp
    return None


def upload_image(img_path):
    """Multipart-upload the image to /api/uploads/photo; return its CDN URL."""
    with open(img_path, "rb") as fh:
        data = fh.read()
    fname = os.path.basename(img_path)
    ext = fname.lower().rsplit(".", 1)[-1]
    ctype = {"png": "image/png", "webp": "image/webp", "jpg": "image/jpeg",
             "jpeg": "image/jpeg"}.get(ext, "application/octet-stream")
    boundary = "----printshelfBoundaryZ9x7Kq2LpR"
    body = b"".join([
        ("--%s\r\n" % boundary).encode(),
        ('Content-Disposition: form-data; name="file"; filename="%s"\r\n' % fname).encode(),
        ("Content-Type: %s\r\n\r\n" % ctype).encode(),
        data,
        ("\r\n--%s--\r\n" % boundary).encode(),
    ])
    req = urllib.request.Request(
        BASE_URL + "/api/uploads/photo", data=body, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                 "Authorization": "Bearer " + API_KEY})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8")).get("url")


def post(payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + "/api/prints/ingest", data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + API_KEY},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    if len(sys.argv) < 2:
        log("no G-code path passed; nothing to do")
        return
    if DEBUG:
        dump_debug(sys.argv[1])
    if not API_KEY or API_KEY == _UNCONFIGURED_KEY:
        log("API key not configured — set PRINTSHELF_API_KEY or download the "
            "pre-filled script from PrintShelf -> Connect your slicer")
        return
    path = sys.argv[1]
    try:
        payload = build_payload(path)
        try:
            img = find_image(path)
            if img:
                url = upload_image(img)
                if url:
                    payload["photo_url"] = url
        except Exception as e:
            log("image upload skipped (%s: %s)" % (type(e).__name__, e))
        result = post(payload)
        warns = result.get("warnings") or []
        log("logged '%s' (%s filament(s)%s%s)" % (
            payload["title"], len(payload["filaments"]),
            ", +image" if payload.get("photo_url") else "",
            "; " + "; ".join(warns) if warns else ""))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:300]
        log("API %s: %s" % (e.code, body))
    except Exception as e:  # never break the slicer
        log("skipped (%s: %s)" % (type(e).__name__, e))


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)  # always succeed so the slicer never errors
