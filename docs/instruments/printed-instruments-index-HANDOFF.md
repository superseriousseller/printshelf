# PluggedIn3D — Printed Instruments Index · Project Handoff

Paste this into a new chat to continue. Attach the three companion files listed
in §11 if you have them; this doc alone is enough to rebuild everything if not.

---

## 1. What this project is

A **verified, curated registry of 3D-printable musical instruments** — the single
source of truth that doesn't exist yet. The differentiator is honesty: every entry
says whether the file actually *plays*, what it *really* costs to build, how close
it *sounds* to the real thing, and what it *takes* to build. It grows as
PluggedIn3D films builds (the series is the verification pipeline; each episode
promotes an entry to "verified").

**Priorities, in order:** (1) maximum usefulness/helpfulness to makers and music
educators, (2) affiliate revenue from parts/filament/retail links. These
complement — honesty is what makes the affiliate links convert. A trusted decision
tool beats a print-cheerleader.

**Where it lives:** as a section of **PrintShelf** (Cam's SaaS — FastAPI / Postgres
/ Railway / Cloudflare), with Cam's own prints mixed in, links to non-printable
parts, and filaments used. Community submissions later use the confidence-scoring /
admin-verification pattern from SS Book Tracker. Pricing reuses GoodToSell's
source-adapter + cost-control infrastructure.

---

## 2. Current state

- A working **index prototype** exists: `printable-instruments-index.html` (v0.2),
  a self-contained hostable HTML file. Full concert band grouped Woodwind / Brass /
  Percussion / Strings — 22 buildable entries + a 9-item "frontier" of gaps. Search
  + filter by section + filter by playability. Signature UI element = the
  **playability meter**. The `REGISTRY` and `FRONTIER` JS objects in that file are
  effectively the schema.
- Two more deliverables exist (see §11): the trumpet valve-graft Claude Code brief,
  and the reusable brass-valve-graft SKILL.md.
- **Not yet built:** the pricing rebuild, the sound-comparison feature, and the
  four-axis card. Design for all three is locked (below) and ready to implement.

---

## 3. Design decisions (locked)

### 3a. The four-axis trade-off card
Every instrument shows four independent axes so all trade-offs are legible at a glance:

- **Plays?** — playability meter, 0–3: Decoration / Plays-with-caveats / Playable /
  Verified-on-video. (Verified = built & played on camera by PluggedIn3D. Currently
  none are Verified — that rung is filled by the series.)
- **Sounds like the real thing?** — new tone-fidelity gauge (separate axis; a printed
  recorder scores near-perfect because real recorders are already plastic, a printed
  violin plays fine but sounds student-grade).
- **What does it take?** — effort/difficulty: print hours + assembly skill
  (sanding, gluing, tuning).
- **What does it cost / save?** — the price tiers + retail range (below).

Card sketch:
```
O'CELLO · Conor O'Kane · Strings
PLAYS    ▮▮▮▯  Playable
SOUNDS   ▮▮▯▯  Student-grade   [▶ Printed] [▶ Real]  (blind-guess toggle)
EFFORT   ▮▮▮▮  Advanced · ~40h print + assembly
$14 spool · $91 build · $129 play-ready   (breakdown ▾, each part linked)
vs retail: $200 student ↔ $3,000+ pro   (both affiliate-linked)
```

### 3b. Pricing — three tiers (this resolves the "do we include the bow?" question)
- **Spool cost** = filament only. The awe headline; ties to the "Spool to Zero" series.
- **Build cost** = filament + everything required to make the instrument physically
  complete (strings, steel rod, tuners, springs, drum heads).
- **Play-ready cost** = + accessories needed to make sound that aren't the instrument
  body (bow + rosin, reeds, mouthpiece if not printed, mallets, drumsticks, valve oil).

The bow lives in **play-ready** — not buried, not in the headline. Same slot handles
reeds, mallets, valve oil. Mark `consumable: true` on reeds/rosin/strings/oil so a
"first-year cost" can exclude durable items.

**Insight to exploit:** print-vs-retail savings vary wildly. Trombone = filament +
$5 PVC slide vs ~$300 retail (huge). Cello/clarinet close the gap because
strings/reeds cost real money. Sorting the index by "savings vs retail" surfaces the
best content targets automatically.

### 3c. Retail comparison
Link a **budget** model *and* a **high-end** model, both affiliate. The tone-fidelity
gauge is what keeps this honest — "$130 printed vs $3,000 pro" is only fair when the
sound gauge shows what you give up. Price = what you save; fidelity = what you give up.

### 3d. Sound comparison
- **Two short clips per instrument**, not one file: `[▶ Printed]` (Cam's recording) and
  `[▶ Real]` (reference), both playing the **same short phrase** (a one-octave scale or
  a signature lick), 2–4 sec each, soundboard-style instant playback.
- Same-phrase rule makes it (a) a fair A/B and (b) a valid input to the librosa score.
- **Blind "which one's real?" toggle** — hides labels until you guess. The viral moment.
- **Objective fidelity component:** run Cam's existing **librosa** feature extractor
  (from the band sync-licensing pipeline) on printed-vs-reference recordings for a
  spectral-similarity number (MFCC distance, harmonic-to-noise, spectral centroid).
  Present as *a* signal alongside the clip + subjective 1–5, not gospel.

---

## 4. Sourcing the "real" reference audio (legal paths only)

1. **Record your own** (best) — same mic + same room as the printed clip = fairest A/B.
   You're filming builds anyway; borrow/rent a real one for the episode.
2. **University of Iowa Musical Instrument Samples** — theremin.music.uiowa.edu/MIS.html.
   Free since 1997, usable for any project without restriction. Note-by-note, 3
   dynamics, anechoic; 23 orchestral instruments + percussion — covers nearly the whole
   band. Assemble the same reference phrase from individual notes.
3. **Freesound.org** — CC / CC0 clips for anything Iowa lacks; check license, credit CC-BY.
4. **Do NOT** pull audio from YouTube/Spotify/commercial recordings — copyrighted,
   exposes the whole resource, and unnecessary given Iowa.

Store `real_source` + `real_license` per clip (same honesty discipline as STL licenses).
**Recording-fairness note:** Iowa is anechoic (dry); room-recorded printed clips carry
reverb. Record printed clips dry, or apply matching reverb to both, so neither ears nor
the librosa score are fooled by room tone rather than the instrument.

---

## 5. Live pricing — the realistic architecture

Do **not** scrape prices per pageview (fragile, rate-limited). Instead:
- **Filament cost is computed**, not scraped: `grams × $/kg` from a maintained filament
  price table (Cam's real costs). Grams come from slicing each model once and storing them.
- **Parts:** store `unit_price` + `source_url` + `last_checked`; refresh on a schedule via
  a Claudius LaunchAgent (Cam's pattern). Display "prices as of [date]."
- **Amazon parts:** Cam is an FBA seller → likely eligible for the **Product Advertising
  API**, giving real prices *and* affiliate tags (parts breakdown = revenue stream).

---

## 6. Data model (per entry)

```
name, by (designer), family (Woodwind|Brass|Percussion|Strings|Practice aid)
playability: 0..3          # decoration | caveats | playable | verified
tone_fidelity: 0..5        # + optional librosa_score
effort: 0..5               # print hours + assembly skill
verified_by_pluggedin3d: bool
bed, material
filament: [{type, grams}]  # grams from slicer -> spool cost
parts: [{name, qty, unit_price, currency, source_url, last_checked,
         tier: "build"|"play", consumable: bool}]
computed: spool_cost, build_cost, play_cost
retail_reference: {budget:{price,url}, premium:{price,url}}
printed_clip, real_clip, real_source, real_license
license (of the STL), source_url, demo_url, note
your_build: null | {filament, date}   # PrintShelf "my print" slot
```
Keep it parametric/structured so community submissions and re-pricing are trivial.

---

## 7. The registry (research already done — don't re-source these)

Playability: **D**ecoration / **C**aveats / **P**layable. All URLs verified.

**Woodwind**
- Printable Recorder — Prusa — P — easy backbone win — blog.prusa3d.com (recorder/ocarina/kazoo guide)
- Printable Ocarina — Prusa/community — P
- Printable Kazoo — PistonPin — P — needs membrane (wax paper/film)
- Collapsible Flute — Tele Tunes — P — 3dprintableflutes.com — paid, commercial license available, Bambu profiles
- Membrane Clarinet — DrJones — C — printables.com/model/495171 — membrane reed, no drilling
- Piccolo Clarinet in A — JDWoodwinds — P — jdwoodwind.com — **paid STL, personal use**; advanced
- Bass Clarinet in G — JDWoodwinds — C — paid STL, experts only
- Bb Clarinet (WIP) — Epiccraftful — D — thingiverse:3737183 — unfinished, remix candidate

**Brass**
- PrintBone — PieterB — **P (the brass success story)** — printables.com/model/80020 — parametric OpenSCAD; needs PVC/carbon-fiber slide; designer says partials in tune
- Original 3D Printed Trombone — Piercet — C — printables.com/model/33526 — historical first; PEX/PVC tubing
- Full Size Working Trumpet — hobbyman — C — **flagship verify target** — cults3d.com / thingiverse:307088 — Selmer-based, realistic valve routing, "should produce sounds," needs springs+felts
- Overly-Complicated Trumpet — GCV3D — C — printables.com/model/492588 — valves are printed *slides* (dodges the airtight-piston problem); unverified
- 17-Piece Printable Trumpet — Dan Olson (sculptswithteeth/LtDan) — **D (cautionary)** — thingiverse:662115 — designer says it plays badly; **includes editable .step + .sldprt** (this is the Route A base); mouthpiece works well
- Brass Mouthpieces (all) — various — P — playable printed mouthpieces exist for every brass

**Percussion**
- Mini Marimba (13 bars) — Equals Engineering — P — printables.com/model/257938 — tuned C-major G4–E6, Python tuning script; filament/color change detunes it; short sustain
- Tapophone (Finger Mallet) — L10design — P — makerworld — membrane idiophone, in tune; Standard Digital License (no redistribution)
- Snare Drum Shell — The-Manimal — P (hybrid) — cults3d — shell prints, add real heads/hoops/lugs/wires
- Auxiliary percussion — various — P — claves/woodblock/guiro/shakers/tambourine frames; easiest wins

**Strings** (the ring beyond band)
- O'Cello — Conor O'Kane — P — thingiverse:1703629 — mature, demo video, steel rod through 6 parts, 20cm bed; CC BY-NC; **base for the kid-cello scale job**
- F-F-Fiddle — OpenFab PDX — P — openfabpdx.com/fireball-fiddle — the origin printed violin
- Hovalin — Kaitlyn & Matt Hova — P — hovalabs.com/hovalin — confirm specs before quoting on camera

**Frontier (no confidently-playable printable version yet — the best "nobody's done this" episodes):**
- Saxophone (home FDM) — closest is Olaf Diegel's SLS-nylon alto (industrial, not a home download)
- Oboe / English horn — double reed; closest is a printed musette/shawm on a real oboe reed
- Bassoon — double reed + folded conical bore
- French horn — coiled conical tubing + rotary valves; only mouthpieces exist; hardest brass
- Euphonium / baritone — valved conical low brass; mouthpiece only
- Tuba / sousaphone — build-volume + valves; sectioned build
- Timpani — tunable kettle + head + pedal; hybrid at best
- **Verified playable trumpet** — flagship (see §8)
- **Kid-size cello** — the original request; scale-and-reinforce the O'Cello; fastest first Verified entry

---

## 8. The trumpet valve deep-dive (key technical thread)

The airtight, ported **piston valve** is the one part FDM can't make — real valve
casings are machined/brazed to lathe tolerances; FDM layer lines leak.

- **Solved in plastic, but not by printing:** the pTrumpet (injection-molded ABS) plays,
  doesn't leak, in tune — but that's factory precision, not FDM.
- **O-rings** seal *slides* and simple pistons, **not** ported trumpet pistons (air passes
  *through* the piston via ports that must align in two positions). So O-rings help the
  slide workaround, not a true printed valve.
- **Chosen path — Route A: real metal valve block + printed body.** Proven by the
  pTrumpet **hyTech** (metal valves + plastic body). For a maker: buy a cheap/broken
  student trumpet or cornet (~$30–60), salvage the valve cluster, print everything else
  (leadpipe, bell, tuning slides, bracing) around it. The acoustically hard valve-section
  bore comes correct for free from the real block. **This exact STL doesn't exist yet —
  it's a genuine gap and the most likely first truly-playable printed trumpet.**
- Not relevant to FDM: Michael Westphal's metal-3D-printed trumpet (SLS stainless+bronze).

---

## 9. Route A build pipeline (see the brief file)

Graft a real valve block onto **Olson's editable STEP** (thingiverse:662115 — includes
.step + .sldprt; delete the `TMPT_ValveChamber` solid, graft a parametric collar).

- **Driver:** Claude Code on Claudius (iterate + print-test loop; not Cowork).
- **CAD engine:** CadQuery or build123d (Python, OpenCASCADE, STEP-native, precision).
- **Visual verify:** FreeCAD + FreeCAD MCP (neka-nat) — screenshot after each op.
- **Skip** the connected SketchUp MCP (mesh/architectural, wrong tool).
- **Hard rule:** build to *measured* block dimensions (calipers); never invent bore/
  spacing. Print a fit-check collar first; tune `socket_clearance`; then print the body.
- **Beds:** Cam's Bambus are 256mm (A1/P1/X1) and 180mm (A1 Mini). Olson already split
  the body for the bed, so print-splitting is mostly inherited; new splitting = just the
  collar + the six re-jointed interfaces. CadQuery can auto-split oversized parts and add
  alignment pins.
- Materials: PETG/ABS/ASA (breath moisture; not PLA); walls ≥4–5, infill ≥30%, run
  10–20°C hotter to close leak gaps; O-ring/silicone at printed-to-metal joints.

Full staged plan (A–G) is in `trumpet-valve-graft-claude-code-brief.md`. To start:
point Claude Code at that file — *"Read the brief and start."*

---

## 10. Skills setup (Claude Code)

- Personal skills live in `~/.claude/skills/<skill-name>/SKILL.md` (hidden folder;
  reveal in Finder with Cmd+Shift+. or use terminal). Each skill in its own subfolder.
- `mkdir -p ~/.claude/skills/brass-valve-graft`, drop the SKILL.md in, **restart Claude
  Code** (a skills dir created mid-session isn't watched until restart).
- The `brass-valve-graft` skill generalizes Route A to euphonium/tuba (see file).
- (Reminder: `/mnt/skills/` is inside the sandbox, NOT on the Mac. Ignore it.)

---

## 11. Files already produced (attach these to the new chat)

1. `printable-instruments-index.html` — the v0.2 index prototype (full REGISTRY +
   FRONTIER data + playability-meter UI).
2. `trumpet-valve-graft-claude-code-brief.md` — the Route A build runbook.
3. `brass-valve-graft-SKILL.md` — the reusable CAD-graft skill.
4. `printed-instruments-index-HANDOFF.md` — this document.

---

## 12. Open tasks (suggested priority)

1. **Pricing rebuild of the index** — add the four-axis card + spool/build/play tiers +
   retail range + breakdown links. *Blocker:* needs Cam's slicer gram-weights per model
   (start: cello, recorder, trombone, marimba) for exact headline numbers.
2. **Sound feature** — reference-phrase list per instrument; wire `[▶ Printed]`/`[▶ Real]`
   soundboard buttons + blind-guess toggle + clip data model; pull Iowa MIS references.
3. **Kid-size cello build spec** — scale factors off the O'Cello, rod gauge, string
   tension, parts list. The original request; fastest first "Verified" entry + episode.
4. **Trumpet Route A** — run the Claude Code brief; buy a donor block; produce the
   fit-check collar. Flagship "verified playable trumpet."
5. **Productionize into PrintShelf** — data model → real app; community submissions with
   SS Book Tracker confidence scoring; Amazon PA-API pricing refresh via LaunchAgent.

---

## 13. Guardrails / principles

- Rate honestly; the honesty *is* the affiliate funnel. "Just buy it" is a valid,
  monetizable verdict.
- Verify playability on camera before promoting an entry to Verified.
- Audio: legal sources only (Iowa MIS / Freesound / self-recorded); never rip
  copyrighted recordings.
- CAD: measured numbers only; fit-check before full prints.
- Keep everything parametric/structured for reuse and community data.
