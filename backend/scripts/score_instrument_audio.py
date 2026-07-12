"""Compute an objective printed-vs-real similarity score for one Instruments
Index entry, using librosa. LOCAL-ONLY — run this from your own machine, not
Railway. See backend/scripts/requirements-audio-scoring.txt: librosa (+ the
numpy/scipy/numba/soundfile it pulls in) is deliberately NOT in the repo-root
requirements.txt Railway installs. The deployed app never imports librosa —
it only ever renders the float this script writes to RegistryEntry.objective_score.

Requires an entry that already has both clips (run ingest_instrument_audio.py
first). Downloads the printed + real clips from their CDN URLs, extracts a
couple of standard timbre features, and combines them into a 0-1 similarity
score. This is a simple heuristic, not a rigorous audio-fingerprinting
pipeline — per the HANDOFF, it's meant to be *a* signal alongside the
subjective fidelity_axis rating, not the final word:

  - MFCC cosine similarity (70% weight): mean-pooled MFCCs capture overall
    timbre/spectral envelope — the standard "does this sound like the same
    kind of instrument" feature.
  - Spectral centroid similarity (30% weight): a cheap brightness/tone-color
    check that MFCCs alone can miss.

Usage:
    pip install -r backend/scripts/requirements-audio-scoring.txt
    DATABASE_URL=postgresql://... python backend/scripts/score_instrument_audio.py \\
        --slug printable-recorder [--dry-run]
"""
import argparse
import os
import sys
import tempfile

import httpx

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_DIR)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))  # backend/.env, regardless of cwd — DATABASE_URL

from models import RegistryEntry, SessionLocal  # noqa: E402

MFCC_WEIGHT = 0.7
CENTROID_WEIGHT = 0.3


def _download(url: str, dest: str) -> None:
    resp = httpx.get(url, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        f.write(resp.content)


def _load_audio(path: str):
    import librosa
    y, sr = librosa.load(path, sr=None, mono=True)
    return y, sr


def _mfcc_similarity(y1, sr1, y2, sr2) -> float:
    import librosa
    import numpy as np
    m1 = librosa.feature.mfcc(y=y1, sr=sr1, n_mfcc=13).mean(axis=1)
    m2 = librosa.feature.mfcc(y=y2, sr=sr2, n_mfcc=13).mean(axis=1)
    denom = (np.linalg.norm(m1) * np.linalg.norm(m2)) or 1e-9
    cos = float(np.dot(m1, m2) / denom)
    return max(0.0, cos)  # cosine similarity can go negative; floor at 0


def _centroid_similarity(y1, sr1, y2, sr2) -> float:
    import librosa
    c1 = float(librosa.feature.spectral_centroid(y=y1, sr=sr1).mean())
    c2 = float(librosa.feature.spectral_centroid(y=y2, sr=sr2).mean())
    rel_diff = abs(c1 - c2) / max(c1, c2, 1e-9)
    return max(0.0, 1.0 - rel_diff)


def compute_similarity(printed_path: str, real_path: str) -> float:
    y1, sr1 = _load_audio(printed_path)
    y2, sr2 = _load_audio(real_path)
    mfcc_sim = _mfcc_similarity(y1, sr1, y2, sr2)
    centroid_sim = _centroid_similarity(y1, sr1, y2, sr2)
    score = MFCC_WEIGHT * mfcc_sim + CENTROID_WEIGHT * centroid_sim
    return round(min(1.0, max(0.0, score)), 3)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True, help="RegistryEntry.slug (vertical=instruments)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        import librosa  # noqa: F401
    except ImportError:
        print("ERROR: librosa isn't installed. Run:\n  pip install -r backend/scripts/requirements-audio-scoring.txt")
        sys.exit(1)

    db = SessionLocal()
    entry = db.query(RegistryEntry).filter(
        RegistryEntry.vertical == "instruments",
        RegistryEntry.slug == args.slug,
    ).first()
    if entry is None:
        print(f"ERROR: no instruments RegistryEntry with slug {args.slug!r}")
        sys.exit(1)

    media = entry.media or []
    printed = next((m for m in media if m.get("kind") == "audio_printed"), None)
    real = next((m for m in media if m.get("kind") == "audio_real"), None)
    if not printed or not real:
        print(f"ERROR: {args.slug!r} doesn't have both clips yet — run ingest_instrument_audio.py first")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        printed_path = os.path.join(tmpdir, "printed.mp3")
        real_path = os.path.join(tmpdir, "real.mp3")
        print(f"Downloading printed clip from {printed['url']}...")
        _download(printed["url"], printed_path)
        print(f"Downloading real clip from {real['url']}...")
        _download(real["url"], real_path)

        print("Computing similarity...")
        score = compute_similarity(printed_path, real_path)

    print(f"\nobjective_score = {score}")

    if args.dry_run:
        print(f"\nDRY RUN — would update {entry.name!r} ({args.slug}), no write.")
        return

    entry.objective_score = score
    db.commit()
    print(f"\nDone — {entry.name!r} ({args.slug}) objective_score set to {score}.")


if __name__ == "__main__":
    main()
