# Printed Instruments Index — Pre-Handoff Spec (v1.0)

Companion to `printed-instruments-index-HANDOFF.md`. This locks the product
architecture decisions and lists the concrete work required BEFORE the index is
handed to the PrintShelf codebase. Guiding promise: a visitor thinks "I didn't
know I could do this," clicks the buttons, prints the files, buys the parts, and
ends up with a working instrument — reliably, consistently, with prices in a
tight ballpark and effort ratings that match reality.

---

## 1. Locked decisions

| Question | Decision |
|---|---|
| Pricing freshness | Spec-based BOM + computed filament + weekly link-checker + scheduled price refresh + visible staleness (badges → auto-hide). Ranges, never false precision. |
| Audio sourcing | Manual curation, scripted assembly, self-hosted clips. Iowa MIS downloaded & processed (license permits); never hotlinked. Self-record the cheap instruments (recorder/ocarina/kazoo). Freesound CC0 fallback. Attribution stored per clip. |
| Community | Fully curated by Cam. Community = inputs only (suggestion form + per-card reports: dead link / price changed / I built it). No public submissions to the index. Confidence-scoring deferred until scale demands. |
| Frontier ("coming soon") | Shown prominently. Every frontier card gets "Notify me when this exists" = email capture + demand voting + episode pre-audience. |
| Email | Cam owns the list (API-driven provider or self-hosted listmonk on Railway), tagged per instrument. PrintShelf in-app notifications additionally for logged-in users. Not delegated to PrintShelf alone. |
| Generalization | Core schema is vertical-agnostic NOW. "Instruments" is collection #1 of a repeatable "verified registry of things you didn't know you could print" platform. Proof media is pluggable per collection (audio A/B for instruments). |

---

## 2. Data model (final shape)

### 2a. Core (vertical-agnostic)
```
entry {
  id, slug, collection            # "instruments" is collection #1
  name, designer, family/section
  status: frontier | listed       # frontier = no playable solution yet
  axes: {                         # 4-axis honesty card
    function: 0..3                #  = playability for instruments
    fidelity: 0..5 (+ objective_score?)   # librosa spectral for instruments
    effort:   rubric level (see 5)
    cost:     computed (see 3)
  }
  verified_by_owner: bool         # flips via content episode
  license, source_url, demo_url, note
  media: [proof objects]          # pluggable: audio A/B, video, load test…
  owner_build: null | {filament, date, episode_url}
  retail_reference: {budget:{price,url,checked}, premium:{price,url,checked}}
}
```

### 2b. BOM — parts are SPECS, links are FULFILLMENTS (key decision)
```
bom_item {
  spec: "4× bass guitar tuning machines, sealed gear"   # the requirement
  qty, tier: build | play, consumable: bool
  fulfillments: [                 # 1..n ways to buy it
    { vendor, url, price, currency, last_checked,
      availability: ok | dead | unknown, affiliate: bool }
  ]
}
```
A dead link removes ONE option, never breaks the build. Cost math uses the
cheapest available fulfillment; if none available → item shows "source needed,"
entry cost shows as incomplete rather than wrong.

### 2c. Filament (computed, never stale)
```
filament_usage: [{ material, grams }]        # grams fixed per model (from slicer)
filament_price_table: { material: $/kg }     # the ONLY maintained price input
spool_cost = Σ grams × $/kg                  # computed at render
```

---

## 3. Pricing freshness system

Three mechanisms, cheapest first:

1. **Computed filament** — no refresh needed; maintain the $/kg table (rarely changes).
2. **Weekly dead-link checker** — HTTP status pass over every fulfillment URL +
   retail reference URL. LaunchAgent on Claudius (plist logs → /tmp) or Railway
   cron. Availability rot matters more than price drift; catch it in days.
3. **Price refresh**
   - Amazon fulfillments: **Product Advertising API** — live price + affiliate
     tag in one call. ACTION: verify Associates eligibility and apply NOW
     (approval lag; Creator Connections account exists but PA-API access must be
     confirmed separately).
   - Non-Amazon fulfillments: quarterly manual-confirm pass (a generated
     checklist of URLs + stored prices to eyeball; 30-min task).

**Trust layer (self-punishing staleness):**
- Display **ranges** ("$85–$110 build"), never single false-precision numbers.
- Every cost block shows "prices checked [date]".
- Staleness escalation: >90 days → "aging prices" badge; >180 days → price
  auto-hides, shows "needs re-verification". The system must be INCAPABLE of
  confidently displaying year-old numbers.
- Availability change (item → dead with no alternate fulfillment) → flag in
  Cam's admin queue to source a substitute link for the same spec.

---

## 4. Audio pipeline

1. **Reference phrase standard**: one short phrase per instrument (one-octave
   scale or signature lick, 2–4 s). Same phrase on printed + real = fair A/B and
   valid librosa comparison.
2. **Iowa MIS**: download per-note files once for each covered instrument;
   script assembles the phrase (pydub/librosa: concatenate, normalize loudness,
   transcode mp3/ogg). One-time script, reused per instrument.
3. **Hosting**: self-host processed clips (Cloudflare R2). Never hotlink Iowa.
4. **Attribution**: `real_source`, `real_license`, credit line on page.
5. **Not covered by Iowa** (recorder, ocarina, kazoo, misc aux percussion):
   self-record — these are the cheapest real instruments to buy/borrow, and
   same-mic/same-room is the fairest A/B anyway. Freesound CC0 fallback with
   per-clip license check.
6. **Fairness rule**: Iowa is anechoic (dry). Record printed clips dry or apply
   matching light reverb to both. Otherwise room tone, not the instrument, wins.
7. **Printed clips**: manual (Cam records during build episodes) — inherently.
8. **UI**: soundboard buttons [▶ Printed] [▶ Real] + blind "which is real?"
   toggle (labels hidden until guess). Instant playback, no player chrome.

---

## 5. Effort rubric (so ratings are consistent)

Two components, displayed together:
- **Print load**: bucketed hours (S <5h · M 5–20h · L 20–50h · XL 50h+) — derive
  from slicer estimates, same source as gram weights.
- **Assembly skill**: 1 none/snap-fit · 2 glue+hardware · 3 tension/tuning setup
  (strings, membranes) · 4 precision fitting (reaming, pads, valve seating) ·
  5 instrument-tech skills assumed.
Every entry's effort must be assigned from this rubric, not vibes, so "the
actual effort matches" across the index.

---

## 6. Community & contribution model

- **No public submissions.** Cam is the sole author of record; curation is the
  product.
- **Suggestion inbox** (Tally form, same pattern as collab intake): "index this
  model" / "I want instrument X" → feeds Cam's queue, invisible to public.
- **Per-card reports** (one-click, no account): dead link · price changed ·
  I built this (optional photo/result). Readers become monitoring sensors.
- Revisit SS Book Tracker-style confidence scoring only if report volume or
  catalog size makes solo curation the bottleneck.

---

## 7. Frontier + subscribe mechanics

- Frontier entries are first-class citizens with the same card chrome, clearly
  badged, each explaining WHY it's unsolved (the physics) and the closest
  existing attempt.
- **"Notify me when this exists"** on every frontier card → email list with a
  per-instrument tag. This is simultaneously: demand voting (ranks the next
  episode), audience pre-building (launch-day distribution), and list growth.
- **General subscribe**: "new instruments & verified builds" on the page.
- Provider: API-driven (Buttondown / Loops / listmonk on Railway) so the
  promote-to-Verified automation can trigger sends. PrintShelf in-app
  notifications fire additionally for logged-in users; the public list is
  Cam-owned and portable to future collections.

---

## 8. Work list before PrintShelf handoff

**Cam (manual, blocking):**
- [ ] Slice each listed model once → record grams + print-hours (feeds spool
      cost + effort rubric). Start: cello, recorder, trombone, marimba.
- [ ] Verify Amazon Associates / PA-API eligibility; submit application.
- [ ] Choose email provider (API-driven) + create list with per-instrument tags.
- [ ] Fill filament $/kg table (own real costs).

**Buildable now (Claude Code tasks):**
- [ ] Migrate REGISTRY/FRONTIER from the HTML prototype into the final schema
      (§2), converting every parts string into spec+fulfillment BOM items.
- [ ] Dead-link checker job + staleness badge logic.
- [ ] PA-API price-refresh job (behind a flag until approval lands).
- [ ] Iowa audio pipeline script (download → assemble phrase → normalize →
      transcode → upload R2 → write attribution fields).
- [ ] Effort-rubric fields + backfill from slicer data as it arrives.
- [ ] Suggestion form + per-card report endpoints → admin queue.
- [ ] Notify-me buttons wired to tagged email list; promote-to-Verified hook
      that triggers the announcement send.

**PrintShelf integration (after the above):**
- [ ] Mount as a PrintShelf collection using the vertical-agnostic schema.
- [ ] Cam's builds surface via `owner_build` (links model + filament + episode).
- [ ] In-app notifications for logged-in users mirroring list sends.

---

## 9. Definition of "ready to hand over"

The index is handoff-ready when: every listed entry has a spec-based BOM with
≥1 live fulfillment link, computed spool cost from real gram weights, an
effort rating from the rubric, a checked-date on every price, the staleness
logic demonstrably hides >180-day prices, at least the cello/recorder/trombone/
marimba have working audio A/B, and the frontier cards capture emails. Anything
less ships a promise the product can't keep.
