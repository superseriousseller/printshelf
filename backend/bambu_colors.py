"""Bambu Lab official filament color names, keyed by product line + hex.

Sourced from Bambu\'s official hex-code tables (community-compiled JSON in
static/data/bambu_colors.json). Used to give slicer-imported Bambu filaments
their EXACT manufacturer color name — never a nearest-color guess. Returns None
when the hex isn\'t an official Bambu color (the swatch still shows correctly).
"""
import functools
import json
import os

_DATA = os.path.join(os.path.dirname(__file__), "static", "data", "bambu_colors.json")


@functools.lru_cache(maxsize=1)
def _table():
    try:
        raw = json.load(open(_DATA))
    except Exception:
        return []
    out = []
    for c in raw.get("colors", []):
        name = c.get("name", "")
        hexv = (c.get("hex") or "").strip().upper()
        line, color = (name.split(" \u2014 ", 1) + [""])[:2] if " \u2014 " in name else ("", name)
        if hexv and color:
            out.append((line.strip(), color.strip(), hexv))
    return out


def _line_hint(material, finish):
    mat = (material or "").strip().upper()
    fin = (finish or "").strip().lower()
    if mat == "PLA":
        if not fin:
            return "PLA Basic"
        if "matte" in fin:
            return "PLA Matte"
        if "silk" in fin:
            return "PLA Silk"
        if "wood" in fin:
            return "PLA Wood"
        if "carbon" in fin or fin == "cf":
            return "PLA-CF"
        if "translucent" in fin or "transparent" in fin:
            return "PLA Translucent"
        if "tough" in fin:
            return "PLA Tough+"
        return "PLA " + fin.title()
    return mat


def color_name(brand, material, finish, hexv):
    """Exact Bambu color name for (brand, material, finish, hex), or None."""
    if not hexv or "bambu" not in (brand or "").lower():
        return None
    h = hexv.strip().upper()
    matches = [(line, color) for (line, color, hh) in _table() if hh == h]
    if not matches:
        return None
    want = _line_hint(material, finish)
    if want:
        for line, color in matches:
            wl, ll = want.lower(), line.lower()
            if wl in ll or ll in wl:
                return color
    names = {c for _, c in matches}
    if len(names) == 1:          # same name across lines -> unambiguous
        return matches[0][1]
    return None                  # ambiguous across product lines -> don't guess
