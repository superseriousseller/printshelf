# Printed Trumpet × Real Valve Block — Claude Code Build Brief

**Route A: graft a salvaged metal valve block onto Dan Olson's editable trumpet STEP, output print-ready STLs.**

Hand this whole file to Claude Code on Claudius. It's written so the agent can set up, pull the files, do the CAD, and export STLs with one human-in-the-loop step (measuring the real valve block).

---

## 0. Definition of done

A set of sliceable STLs for a trumpet **body** that mates to a real metal valve block, produced by editing Olson's STEP file (not modeling from scratch). Specifically:

- Printed leadpipe → **[real metal valve block]** → printed bell, with a parametric **collar/adapter** connecting the printed body to the metal block.
- Every output part fits the target print bed, with alignment features where anything was split.
- A cheap **fit-check collar** printed first to confirm the block seats airtight before committing to the full horn.
- Everything parametric (one variables block) so the same pipeline re-fits to a different donor block later (euphonium/tuba reuse).

The single guiding principle: **the agent builds precisely to measured numbers. It must never invent bore diameters, valve spacing, or receiver sizes.** Those come off the physical block with calipers.

---

## 1. Files to get

**Base CAD (this is the one — it has editable source):**
- Olson "Printable Trumpet" (LtDan): `https://www.thingiverse.com/thing:662115`
  - Download the **.step** file (universal CAD — this is what we edit) and the **.sldprt** (SolidWorks backup).
  - The part to delete is named **`TMPT_ValveChamber`**. Six body pieces attach to it — those interfaces get re-targeted to the new collar.
  - Modeled as a Bb trumpet after a Bach Stradivarius; 17 pieces; already split for the bed with `_CUT` variants for small printers.

**Print-friendlier geometry reference (optional):**
- Olson v2 remix: `https://www.thingiverse.com/thing:772936` (all pieces under ~140mm, prints nicer — use as a layout reference if a v1 part prints poorly).

**Alternate base (if you'd rather start from realistic valve routing):**
- hobbyman "Full Size Working Trumpet": `https://www.thingiverse.com/thing:307088` (Selmer-modeled, valve routes modeled realistically). Mesh-heavier; use only if the Olson STEP proves awkward.

**Mouthpiece:**
- Use a real metal mouthpiece (best), or Olson's STL (he sells it), or a printed brass-style mouthpiece. Not on the critical path.

**Donor metal valve block (the physical part):**
- A cheap/broken student **trumpet** or **cornet** — eBay, pawn shops, school surplus, ~$30–60. Cornet blocks are more compact if bench/print space is tight.
- The salvage target is the **valve cluster**: the three brazed valve casings + pistons + top/bottom caps + the stubs where leadpipe, bell, and the three valve slides attach.
- Alternative donor: a **pTrumpet plastic valve block** (lighter, already plastic — but a metal block gives the best seal/sound).
- Real block = real springs and real slides come with it, so Olson's spring-sourcing headache disappears.

**Measurement tools:** digital calipers (required) or a 3D scanner (nice-to-have for the block's mating stubs).

---

## 2. Environment setup on Claudius

```bash
# --- Python CAD engine (headless, precision, STEP-native) ---
python3 -m venv ~/trumpet-graft/.venv
source ~/trumpet-graft/.venv/bin/activate
pip install --upgrade pip
pip install cadquery build123d trimesh numpy
#   cadquery  -> primary modeling (OpenCASCADE; best training-data coverage / precision)
#   build123d -> fallback modeler if a cadquery op is awkward
#   trimesh   -> bounding-box checks, bed-fit tests, STL sanity

# --- FreeCAD + FreeCAD MCP (visual verify loop for the import/cut surgery) ---
# FreeCAD: install the desktop app (brew install --cask freecad) so the MCP can drive a live doc.
# FreeCAD MCP (neka-nat): https://github.com/neka-nat/freecad-mcp
#   - clone it, copy addon/FreeCADMCP into FreeCAD's Mod/ directory
#   - start the RPC server from the "FreeCAD MCP" workbench inside FreeCAD
#   - register the server in Claude Code's MCP config (uvx-based; verify exact command in the repo README)
#   - the bridge listens on a socket under /tmp  (same /tmp rule your LaunchAgents use)

# --- OpenSCAD (optional, deterministic fallback for the collar only) ---
brew install openscad
```

**Division of labor:**
- **CadQuery (headless, via Claude Code)** does the real work: import STEP, cut the valve chamber, build the parametric collar, union, split for the bed, export STLs. Reviewable, git-diffable, no GUI needed.
- **FreeCAD MCP** is the *eyes*: after each destructive geometry op, render a screenshot and verify the cut/graft landed where intended before continuing. This is the self-correction loop you were missing before.
- **SketchUp MCP (already connected):** skip it here — mesh/architectural, wrong tool for airtight tubing.

---

## 3. Measured inputs — fill these in before the CAD run

Measure the donor block and enter numbers. These become the top-of-file parameter block. **Do not let the agent guess any of these.**

| Variable | What to measure | Typical Bb ballpark |
|---|---|---|
| `bore_dia` | Main tube inner diameter (leadpipe/bell bore) | ~11.5–11.7 mm |
| `casing_spacing_12` | Center-to-center, valve 1 → valve 2 casing | measure |
| `casing_spacing_23` | Center-to-center, valve 2 → valve 3 casing | measure |
| `leadpipe_recv_od` / `_id` | OD/ID of the block stub the leadpipe attaches to | measure |
| `bell_recv_od` / `_id` | OD/ID of the block stub the bell attaches to | measure |
| `vslide_od[1..3]` | OD of each valve-slide port on the block | measure |
| `vslide_pos[1..3]` | XYZ position/angle of each slide port | measure/scan |
| `block_bbox` | Overall block bounding box (for the cradle) | measure |
| `stub_insert_depth` | How deep printed tube slips over each metal stub | 8–12 mm |
| `oring_groove` | O-ring cross-section + groove dims per sealing bore | pick O-ring, then spec |
| `socket_clearance` | Printed-to-metal slip-fit gap (tune on fit-check) | start 0.15–0.25 mm |

---

## 4. Staged build plan (what Claude Code executes)

**Stage A — Import & inventory.**
Load `thing662115.step` in CadQuery. List all solids/bodies; match them to Olson's part names. Open the same file in FreeCAD (MCP) and screenshot an isometric so we can visually confirm which solid is `TMPT_ValveChamber` and identify the six stubs that meet it.

**Stage B — Excise the printed valve chamber.**
Boolean-remove `TMPT_ValveChamber`. Trim the six mating stubs to clean, coplanar faces at recorded coordinates (these become the collar sockets). Save `stage_b.step`. Screenshot-verify the cut faces are clean and square.

**Stage C — Build the parametric collar (CadQuery, from Section 3).**
One new part with two mating sides:
- **Body side:** six sockets that accept the trimmed body stubs (leadpipe-out, bell-in, and the connections that used to run into the valve chamber), positioned from `casing_spacing_*` and the recorded stub coordinates.
- **Block side:** receivers/cradle that seat the metal block's leadpipe and bell stubs, sized `*_recv_od + socket_clearance`, with **O-ring grooves** (`oring_groove`) on each sealing bore. Optionally a light clamp/strap boss to hold the block.
Keep the internal bore continuous at `bore_dia` through every junction.

**Stage D — Union & continuity check.**
Union collar + trimmed body. Programmatically walk each junction and assert no bore step-change greater than a set tolerance (e.g. 0.3 mm) — a discontinuity here kills response. Flag any junction that fails. Save `stage_d.step`.

**Stage E — Split for the print bed.**
Set `bed = 256` (A1/P1/X1) or `180` (A1 Mini). For each solid: check its bounding box (trimesh); if any axis exceeds bed minus margin, planar-split and add registration features (Ø5 mm peg + socket, or a shallow dovetail) at the seam so halves self-align. Reuse Olson's existing seams where they already work. Label each part (embossed name or manifest entry).

**Stage F — Export.**
Write one **STL per part** to `./out/`, plus an assembly `trumpet_assembly.step`. Generate `manifest.csv`: part name, bounding box, needs-supports (y/n), suggested orientation, suggested filament.

**Stage G — Fit-check first (do this before printing the whole horn).**
Export **only** the collar (Stage C) plus ~20 mm stub sections. Print it, seat the real block, check for slip-fit + O-ring seal. If loose/tight, change **one** variable (`socket_clearance`), re-run Stages C–F. Loop here — it's cheap — until the block seats airtight, *then* print the full body.

---

## 5. Material & print settings (for the manifest defaults)

- **Filament:** PETG, ABS, or ASA — your breath is warm and wet, and PLA creeps and absorbs moisture at the joints over time. (Olson used ABS + acetone welding.)
- **Walls ≥ 4–5, infill ≥ 30%** for airtightness.
- **Run hot** — a commenter on the original found +10–20 °C improves layer bonding and closes the micro-gaps that leak air. Worth it here.
- **Sealing:** O-ring or thin silicone sleeve at every printed-to-metal joint; the metal stub is a clean cylindrical sealing surface, far better than printed-to-printed.
- **Bore smoothness matters acoustically** — orient prints so internal tube surfaces are as smooth as possible; avoid support inside tubes (use teardrop/elliptical port cross-sections where bridging is needed, as Olson did).

---

## 6. Guardrails for the agent

- Build strictly to Section 3 numbers. If a required dimension is missing, **stop and ask** — do not invent it.
- After every destructive op, screenshot-verify via FreeCAD MCP before proceeding.
- Save a versioned `.step` at each stage (git-commit them).
- Keep the entire model parametric with the variables block at the top of the script.
- The valve block's internal porting/bore is inherited from the real part — do **not** try to model valve internals. The collar only handles the interface.

---

## 7. Deliverables

`./out/*.stl` (per part) · `trumpet_assembly.step` · `manifest.csv` · `params.py` (the filled Section 3 block) · the printed fit-check collar. Once it plays: wrap the workflow as a `SKILL.md` (measurement checklist + collar recipe) so the euphonium and tuba follow-ons reuse it.

---

## 8. First prompt to paste into Claude Code

> Read `trumpet-valve-graft-claude-code-brief.md` in this folder and set up the project.
>
> 1. Create the venv and install cadquery, build123d, trimesh, numpy. Confirm FreeCAD MCP is reachable; if not, walk me through finishing its install.
> 2. Download `thing:662115`'s `.step` file into `./src/` (ask me to paste the direct file URL if you can't fetch it — Thingiverse download links need a logged-in session).
> 3. Run **Stage A**: import the STEP, inventory the solids, and show me a FreeCAD screenshot with `TMPT_ValveChamber` and its six mating stubs highlighted. Wait for me to confirm before cutting anything.
> 4. Pause and give me the Section 3 measurement table to fill in from the physical valve block. Do not proceed to Stage C until I've entered real numbers.
> 5. Then run Stages B→F, screenshot-verifying each geometry op, and export the **fit-check collar only** (Stage G) first. I'll print it and report the fit before we do the full body.
>
> Keep everything parametric with a `params.py`. Never invent a dimension — if one's missing, stop and ask.
