"""Ingest a printed/real audio A/B pair for one Instruments Index entry.

Shells out to ffmpeg/ffprobe (system binaries — no numpy/scipy/librosa or any
other heavy Python audio dep added to requirements.txt; the deployed app
never touches audio processing, it just renders URLs). Both clips are
loudness-normalized to the same target so the blind A/B is fair — one clip
being a few dB louder biases guessers toward calling it "real" (louder reads
as fuller/better) — see docs/instruments/printed-instruments-index-HANDOFF.md
§3d/§4 and the plan review in this slice's relay thread.

Usage:
    DATABASE_URL=postgresql://... python backend/scripts/ingest_instrument_audio.py \\
        --slug printable-recorder \\
        --printed ~/audio/recorder-printed.wav \\
        --real ~/audio/recorder-real.wav \\
        --phrase "C-major scale, one octave" \\
        --real-source "Cam, recorded same mic/room as printed clip" \\
        --real-license "Original recording" \\
        [--dry-run]

`--real` also accepts a comma-separated list of note files to concatenate
(the Iowa MIS note-by-note assembly case — see HANDOFF §4):
    --real ~/iowa/C4.aiff,~/iowa/D4.aiff,~/iowa/E4.aiff,~/iowa/F4.aiff,~/iowa/G4.aiff,~/iowa/A4.aiff,~/iowa/B4.aiff,~/iowa/C5.aiff

Re-running for the same slug replaces that slug's audio_printed/audio_real
media entries — any other media kind (none exist yet) is left untouched.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import RegistryEntry, SessionLocal  # noqa: E402
from storage import upload_audio  # noqa: E402

TARGET_LUFS = -16.0   # common web-audio loudness target; both clips share it
TRUE_PEAK = -1.5
LOUDNESS_RANGE = 11
MIN_DURATION_S = 1.0
MAX_DURATION_S = 8.0


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout


def _probe_duration(path: str) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(out.strip())


def _concat_notes(note_paths: list[str], out_wav: str) -> None:
    """Concatenate distinct note files into one clip via ffmpeg's concat
    filter (not the concat demuxer) — decodes each input first, so it
    tolerates note files that aren't all the same format/codec."""
    cmd = ["ffmpeg", "-y"]
    for p in note_paths:
        cmd += ["-i", p]
    n = len(note_paths)
    filter_inputs = "".join(f"[{i}:a]" for i in range(n))
    cmd += ["-filter_complex", f"{filter_inputs}concat=n={n}:v=0:a=1[out]", "-map", "[out]", out_wav]
    _run(cmd)


def _normalize_to_mp3(in_path: str, out_mp3: str, target_lufs: float) -> None:
    _run([
        "ffmpeg", "-y", "-i", in_path,
        "-af", f"loudnorm=I={target_lufs}:TP={TRUE_PEAK}:LRA={LOUDNESS_RANGE}",
        "-codec:a", "libmp3lame", "-b:a", "128k",
        out_mp3,
    ])


def _prepare_clip(source: str, tmpdir: str, name: str, target_lufs: float) -> tuple[bytes, float]:
    """source: a single file path, or comma-separated note paths to concat
    first. Returns (normalized mp3 bytes, duration in seconds)."""
    paths = [p.strip() for p in source.split(",")]
    for p in paths:
        if not os.path.isfile(p):
            raise FileNotFoundError(p)

    if len(paths) > 1:
        concat_wav = os.path.join(tmpdir, f"{name}-concat.wav")
        _concat_notes(paths, concat_wav)
        input_path = concat_wav
    else:
        input_path = paths[0]

    out_mp3 = os.path.join(tmpdir, f"{name}.mp3")
    _normalize_to_mp3(input_path, out_mp3, target_lufs)
    duration = _probe_duration(out_mp3)

    with open(out_mp3, "rb") as f:
        return f.read(), duration


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True, help="RegistryEntry.slug (vertical=instruments)")
    ap.add_argument("--printed", required=True, help="Path to the printed-instrument recording")
    ap.add_argument("--real", required=True, help="Path to the real-instrument recording, or comma-separated note files to concatenate")
    ap.add_argument("--phrase", required=True, help='e.g. "C-major scale, one octave"')
    ap.add_argument("--real-source", required=True, dest="real_source")
    ap.add_argument("--real-license", required=True, dest="real_license")
    ap.add_argument("--target-lufs", type=float, default=TARGET_LUFS, dest="target_lufs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    entry = db.query(RegistryEntry).filter(
        RegistryEntry.vertical == "instruments",
        RegistryEntry.slug == args.slug,
    ).first()
    if entry is None:
        print(f"ERROR: no instruments RegistryEntry with slug {args.slug!r}")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Preparing printed clip from {args.printed!r}...")
        printed_bytes, printed_dur = _prepare_clip(args.printed, tmpdir, "printed", args.target_lufs)
        print(f"Preparing real clip from {args.real!r}...")
        real_bytes, real_dur = _prepare_clip(args.real, tmpdir, "real", args.target_lufs)

    for label, dur in (("printed", printed_dur), ("real", real_dur)):
        if not (MIN_DURATION_S <= dur <= MAX_DURATION_S):
            print(f"  WARNING: {label} clip is {dur:.1f}s — expected a short {MIN_DURATION_S:.0f}-{MAX_DURATION_S:.0f}s phrase, double check the source file")

    print(f"  printed: {len(printed_bytes) / 1024:.0f}KB, {printed_dur:.1f}s")
    print(f"  real:    {len(real_bytes) / 1024:.0f}KB, {real_dur:.1f}s")
    print(f"  both normalized to {args.target_lufs} LUFS")

    if args.dry_run:
        print(f"\nDRY RUN — would update {entry.name!r} ({args.slug}) media, no upload/write.")
        return

    printed_url = upload_audio(printed_bytes)
    real_url = upload_audio(real_bytes)

    now = datetime.utcnow().isoformat()
    kept = [m for m in (entry.media or []) if m.get("kind") not in ("audio_printed", "audio_real")]
    entry.media = kept + [
        {"kind": "audio_printed", "url": printed_url, "phrase": args.phrase, "ingested_at": now},
        {
            "kind": "audio_real", "url": real_url, "phrase": args.phrase,
            "source": args.real_source, "license": args.real_license, "ingested_at": now,
        },
    ]
    db.commit()
    print(f"\nDone — {entry.name!r} ({args.slug}) now has an audio A/B pair.")


if __name__ == "__main__":
    main()
