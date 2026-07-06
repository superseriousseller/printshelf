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
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Config — the download from "Connect your slicer" fills API_KEY/BASE_URL in.
# You can also set PRINTSHELF_API_KEY / PRINTSHELF_BASE_URL as env vars.
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("PRINTSHELF_API_KEY", "__PRINTSHELF_API_KEY__")
BASE_URL = os.environ.get("PRINTSHELF_BASE_URL", "__PRINTSHELF_BASE_URL__").rstrip("/")

IS_PUBLIC = True       # show auto-logged prints on your public profile
QUEUED = False         # True = add to your queue instead of logging as printed
STATUS = "printed"     # printed | printing | failed | partial
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


def build_payload(path):
    text = read_comments(path)

    types = split_list(grab(text, r"^;\s*filament_type\s*[:=]\s*(.+)$"))
    colors = split_list(grab(text, r"^;\s*filament_colour\s*[:=]\s*(.+)$",
                             r"^;\s*filament_color\s*[:=]\s*(.+)$",
                             r"^;\s*extruder_colour\s*[:=]\s*(.+)$"))
    settings_ids = split_list(grab(text, r"^;\s*filament_settings_id\s*[:=]\s*(.+)$"))
    vendor = grab(text, r"^;\s*filament_vendor\s*[:=]\s*(.+)$")

    filaments = []
    for i, mat in enumerate(types):
        sid = settings_ids[i] if i < len(settings_ids) else (settings_ids[0] if settings_ids else None)
        brand = vendor
        if not brand and sid:
            brand = sid.split()[0]  # e.g. "Bambu PLA Basic ..." -> "Bambu"
        hexv = colors[i] if i < len(colors) else None
        if hexv and not hexv.startswith("#"):
            hexv = None
        filaments.append({
            "material": mat,
            "color_hex": hexv,
            "brand": brand,
            "finish": detect_finish(sid),
        })

    layer = grab(text, r"^;\s*layer_height\s*[:=]\s*([\d.]+)")
    infill = grab(text, r"^;\s*sparse_infill_density\s*[:=]\s*([\d.]+)",
                  r"^;\s*fill_density\s*[:=]\s*([\d.]+)")
    supports_raw = grab(text, r"^;\s*enable_support\s*[:=]\s*(\S+)",
                        r"^;\s*support_material\s*[:=]\s*(\S+)")
    time_raw = grab(text,
                    r"estimated printing time.*?[:=]\s*([^;\n]+)",
                    r"model printing time\s*[:=]\s*([^;\n]+)",
                    r"total estimated time\s*[:=]\s*([^;\n]+)")
    used_raw = grab(text,
                    r"total filament used \[g\]\s*[:=]\s*([\d.,\s]+)",
                    r"filament used \[g\]\s*[:=]\s*([\d.,\s]+)",
                    r"total filament weight \[g\]\s*[:=]\s*([\d.,\s]+)")
    printer = grab(text, r"^;\s*printer_model\s*[:=]\s*(.+)$",
                   r"^;\s*printer_settings_id\s*[:=]\s*(.+)$")

    used_g = None
    if used_raw:
        nums = [float(x) for x in re.findall(r"[\d.]+", used_raw)]
        if nums:
            used_g = round(sum(nums), 2)

    supports = None
    if supports_raw is not None:
        supports = supports_raw.strip().lower() in {"1", "true", "yes", "on"}

    title = re.sub(r"\.(gcode|gco|g|bgcode)(\.\w+)?$", "", os.path.basename(path), flags=re.IGNORECASE)
    title = title.replace("_", " ").strip() or "Untitled print"

    return {
        "title": title,
        "printer": printer,
        "filaments": [f for f in filaments if f.get("material")],
        "layer_height": float(layer) if layer else None,
        "infill_pct": int(round(float(infill))) if infill else None,
        "supports": supports,
        "print_time_mins": parse_time_to_mins(time_raw),
        "filament_used_g": used_g,
        "status": STATUS,
        "queued": QUEUED,
        "is_public": IS_PUBLIC,
    }


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
    if "__PRINTSHELF_API_KEY__" in API_KEY or not API_KEY:
        log("API key not configured — set PRINTSHELF_API_KEY or download the "
            "pre-filled script from PrintShelf -> Connect your slicer")
        return
    path = sys.argv[1]
    try:
        payload = build_payload(path)
        result = post(payload)
        warns = result.get("warnings") or []
        log("logged '%s' (%s filament(s)%s)" % (
            payload["title"], len(payload["filaments"]),
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
