"""Browse + download individual note/run samples from the University of Iowa
Musical Instrument Samples archive (theremin.music.uiowa.edu) — the free,
unrestricted reference-audio source named in the Instruments Index HANDOFF
(docs/instruments/printed-instruments-index-HANDOFF.md §4).

This only automates the mechanical part: finding + fetching files. It does
NOT pick which dynamic/technique/register sounds most natural, or trim a
downloaded run down to a specific phrase — that's real curation judgment,
left to whoever's authoring the entry. Iowa's files aren't one-note-per-file;
each covers a short chromatic run (e.g. "Cello.arco.pp.sulC.C2Gb2.aiff" =
every note from C2 to Gb2 at pp dynamic, bowed, on the C string), split out
by dynamic/technique/string. --list surfaces those tokens so you can pick
without hand-parsing filenames; --download fetches whatever you pick.

The site's link hrefs contain a literal space ("sound files/MIS/...") — this
script URL-encodes that for you; you don't need to worry about it.

Usage:
    python backend/scripts/iowa_mis_fetch.py --instruments
    python backend/scripts/iowa_mis_fetch.py --instrument cello --list
    python backend/scripts/iowa_mis_fetch.py --instrument cello \\
        --download arco mf sulC --out ~/audio/iowa/cello/
"""
import argparse
import os
import re
import sys
from urllib.parse import quote

import httpx

BASE = "https://theremin.music.uiowa.edu"

# Pre-2012 pages (mono chromatic scales, pp/mf/ff) — simplest + confirmed
# working set. Iowa's post-2012 pages exist too (higher-fidelity stereo) but
# aren't mapped here; add if/when needed.
INSTRUMENT_PAGES = {
    "flute": "MISflute.html",
    "alto-flute": "MISaltoflute.html",
    "bass-flute": "MISbassflute.html",
    "oboe": "MISoboe.html",
    "eb-clarinet": "MISEbclarinet.html",
    "bb-clarinet": "MISBbclarinet.html",
    "bass-clarinet": "MISbassclarinet.html",
    "bassoon": "MISbassoon.html",
    "soprano-sax": "MISsopranosaxophone.html",
    "alto-sax": "MISaltosaxophone.html",
    "horn": "MISFrenchhorn.html",
    "trumpet": "MISBbtrumpet.html",
    "tenor-trombone": "MIStenortrombone.html",
    "bass-trombone": "MISbasstrombone.html",
    "tuba": "MIStuba.html",
    "violin": "MISviolin.html",
    "viola": "MISviola.html",
    "cello": "MIScello.html",
    "double-bass": "MISdoublebass.html",
    "marimba": "Mismarimba.html",
    "xylophone": "MISxylophone.html",
    "vibraphone": "Misvibraphone.html",
    "bells": "MISbells.html",
    "crotales": "MIScrotales.html",
    "cymbals": "MIScymbals.html",
    "gongs-tamtams": "MISgongtamtams.html",
    "hand-percussion": "MIShandpercussion.html",
    "tambourines": "MIStambourines.html",
    "piano": "MISpiano.html",
    "guitar": "MISguitar.html",
}

_LINK_RE = re.compile(r'href="((?:sound files|sound%20files)/[^"]+\.(?:aiff|aif|mp3|wav))"', re.IGNORECASE)

_DYNAMIC_TOKENS = {"pp", "p", "mp", "mf", "f", "ff"}


def _describe(filename: str) -> str:
    """Best-effort breakdown of a sample filename into readable tokens —
    not a strict parser, since naming isn't perfectly uniform across every
    instrument family (strings have sulX; winds/brass/percussion don't)."""
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    tokens = stem.split(".")
    dynamic = next((t for t in tokens if t.lower() in _DYNAMIC_TOKENS), None)
    string = next((t for t in tokens if t.lower().startswith("sul")), None)
    bits = []
    if dynamic:
        bits.append(f"dynamic={dynamic}")
    if string:
        bits.append(f"string={string}")
    return " ".join(bits) if bits else "(see filename)"


def fetch_links(instrument: str) -> list[str]:
    page = INSTRUMENT_PAGES.get(instrument)
    if not page:
        raise ValueError(f"Unknown instrument {instrument!r}. Run --instruments to see the list.")
    resp = httpx.get(f"{BASE}/{page}", timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    return sorted(set(_LINK_RE.findall(resp.text)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instruments", action="store_true", help="List available instrument slugs and exit")
    ap.add_argument("--instrument", help="Instrument slug (see --instruments)")
    ap.add_argument("--list", action="store_true", help="List that instrument's sample files")
    ap.add_argument("--download", nargs="+", metavar="SUBSTRING", help="Download files whose filename contains ALL given substrings (case-insensitive)")
    ap.add_argument("--out", default=".", help="Directory to save downloads into (default: current dir)")
    args = ap.parse_args()

    if args.instruments:
        for slug in sorted(INSTRUMENT_PAGES):
            print(slug)
        return

    if not args.instrument:
        ap.error("--instrument is required (unless using --instruments)")

    links = fetch_links(args.instrument)
    if not links:
        print(f"No sample files found on {args.instrument}'s page — check --instruments for the right slug, or the page layout may have changed.")
        return

    if args.download:
        needles = [s.lower() for s in args.download]
        matches = [link for link in links if all(n in link.lower() for n in needles)]
        if not matches:
            print(f"No files matched {args.download!r}. Run --list to see what's available.")
            return
        os.makedirs(args.out, exist_ok=True)
        for link in matches:
            filename = link.rsplit("/", 1)[-1]
            url = f"{BASE}/{quote(link)}"
            dest = os.path.join(args.out, filename)
            print(f"Downloading {filename}...")
            resp = httpx.get(url, timeout=60.0, follow_redirects=True)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                f.write(resp.content)
            print(f"  -> {dest} ({len(resp.content) / 1024:.0f}KB)")
        return

    # Default: --list (or no action specified)
    print(f"{len(links)} sample file(s) for {args.instrument!r}:\n")
    for link in links:
        filename = link.rsplit("/", 1)[-1]
        print(f"  {filename}\n    {_describe(filename)}")


if __name__ == "__main__":
    main()
