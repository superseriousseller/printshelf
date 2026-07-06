---
name: brass-valve-graft
description: >
  Use when grafting a real (salvaged/metal or donor-plastic) valve block onto a
  3D-printable brass instrument body — trumpet, cornet, flugelhorn, euphonium,
  baritone, or tuba. Covers editing an existing CAD/STEP body, excising the
  printed valve section, building a parametric collar/adapter that mates the
  printed tubing to the real valve cluster, checking bore continuity, splitting
  for the print bed, and exporting STLs. Includes donor selection, the physical
  measurement checklist, the CadQuery + FreeCAD-MCP toolchain, sealing method,
  and print-splitting rules. Trigger for any "print the body, use real valves"
  brass build.
---

# Brass Valve-Block Graft

The airtight, ported piston valve is the one part of a brass instrument that FDM
printing cannot make well — it needs machined tolerances. Everything else
(leadpipe, bell, tuning slides, bracing) prints fine. This skill grafts a real
metal valve cluster into a printed body so you inherit the hard part instead of
fighting it.

**Core rule: build to measured numbers. Never invent a bore diameter, casing
spacing, or receiver size. They come off the physical block with calipers.**

## When to use
- Any valved brass where a playable all-printed version doesn't exist (trumpet is
  the reference build; euphonium, tuba, French horn are the follow-ons).
- You have, or can buy, a cheap donor instrument to salvage the valve cluster from.
- You have an editable CAD body (STEP preferred) to cut and graft onto.

## Do NOT use for
- Slide brass (trombone) — no valves to replace; print the body, use a PVC/CF slide.
- All-printed valve attempts — different problem, out of scope here.
- Woodwind key mechanisms — related idea (print body, salvage keys) but different
  geometry; see a woodwind-specific skill.

## Inputs to gather first

**Donor block** — cheap/broken student instrument or cornet (eBay/pawn/surplus).
Salvage the valve cluster: casings + pistons + caps + the stubs where leadpipe,
bell, and each valve slide attach. Real block brings real springs and slides.

**Editable body CAD** — a STEP file of a printable version of the target
instrument. Identify the solid that is the printed valve section (to delete) and
the stubs that meet it (to re-target to the collar).

**Measurements** (fill before any collar modeling):

| Variable | Measure |
|---|---|
| `bore_dia` | main tube inner diameter |
| `casing_spacing[]` | center-to-center between adjacent valve casings |
| `leadpipe_recv_od/id` | block stub the leadpipe attaches to |
| `bell_recv_od/id` | block stub the bell attaches to |
| `vslide_od[]`, `vslide_pos[]` | each valve-slide port size + XYZ/angle |
| `block_bbox` | overall block bounding box (for the cradle) |
| `stub_insert_depth` | printed-tube overlap onto each metal stub (8–12 mm) |
| `oring_groove` | O-ring cross-section + groove per sealing bore |
| `socket_clearance` | slip-fit gap, start 0.15–0.25 mm, tune on fit-check |

## Toolchain
- **CadQuery (headless, primary)** — import STEP, boolean cut/union, build the
  parametric collar, split for bed, export STL. Reviewable and git-diffable.
- **FreeCAD + FreeCAD MCP (visual verify)** — screenshot after each destructive
  op to confirm the cut/graft landed before continuing.
- **build123d** — fallback modeler for awkward ops. **OpenSCAD** — optional
  deterministic path for the collar only.
- Bridge sockets live under `/tmp`.

## Workflow
1. **Import & inventory** — load STEP, list solids, screenshot, identify the
   printed valve section + its mating stubs. Confirm before cutting.
2. **Excise** — boolean-remove the printed valve section; trim mating stubs to
   clean coplanar faces at recorded coordinates. Save versioned STEP.
3. **Parametric collar** — one part, two sides: sockets for the body stubs
   (from spacing + coordinates) and receivers/cradle that seat the metal block's
   leadpipe and bell stubs (`recv_od + socket_clearance`) with O-ring grooves on
   sealing bores. Keep internal bore continuous at `bore_dia`.
4. **Union & continuity check** — union collar + body; assert no bore step-change
   over tolerance (~0.3 mm) at any junction; flag failures.
5. **Split for bed** — per solid, check bounding box vs bed (256 mm typical,
   180 mm mini); planar-split oversized parts and add registration pins/dovetails
   so halves self-align; reuse existing seams where they work.
6. **Export** — STL per part + assembly STEP + `manifest.csv` (name, bbox,
   supports y/n, orientation, filament).
7. **Fit-check first** — export the collar + short stub sections only; print,
   seat the real block, tune `socket_clearance` for an airtight slip-fit; only
   then print the full body.

## Sealing & material
- **PETG / ABS / ASA**, not PLA (breath moisture; PLA creeps at joints).
- Walls ≥ 4–5, infill ≥ 30% for airtightness; run 10–20 °C hotter to close
  inter-layer micro-gaps that leak.
- O-ring or thin silicone sleeve at every printed-to-metal joint — the metal stub
  is a clean cylindrical sealing surface.
- Orient prints for smooth internal bore surfaces; avoid supports inside tubes
  (use teardrop/elliptical bridged cross-sections).

## Guardrails
- Missing a required dimension → stop and ask; do not invent it.
- Screenshot-verify each destructive op before proceeding.
- Keep everything parametric (one variables block); commit a STEP per stage.
- Do not model valve internals — porting/bore is inherited from the real block;
  the collar handles only the interface.

## Per-instrument notes
- **Trumpet / cornet** — reference build. Bore ~11.5–11.7 mm. Body fits a 256 mm
  bed largely un-split; cornet is more compact.
- **Flugelhorn** — like trumpet but more conical; watch the leadpipe taper.
- **Euphonium / baritone** — larger bore, 3–4 valves, bigger body → more
  bed-splitting; compensating valve blocks are more complex, measure carefully.
- **Tuba / sousaphone** — build-volume dominates; expect heavy sectioning of bell
  and branches; a real 4-valve block is the anchor, print everything around it.
- **French horn** — hardest: rotary (not piston) valves + tightly coiled conical
  tubing. Start from a single-Bb layout; treat as R&D, not a repeat of this recipe.

## Reuse note
After a successful build, record the filled parameter set and the donor block it
matched, so a future run can start from the nearest prior fit rather than zero.
