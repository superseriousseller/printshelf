# ROADMAP / BACKLOG — PrintShelf

Living backlog. Not a commitment to do these now — captured so effort goes
where real usage is. Priorities are rough; reorder freely.

---

## P1 — Source attribution ("where did this come from?")  ← Cam's priority (2026-08-06)

**Why:** We literally could not answer "how many filaments were added via the
Chrome extension?" because nothing on a created row records *which client made
it*. Right now web-created, extension-created, API-created, and iOS-Shortcut-
created rows are indistinguishable. We need to know so we can put effort/
marketing into what people actually use.

**IMPORTANT distinction — two different axes, don't conflate them:**
- `prints.source_platform` (already exists) = where the **model/content** is
  from — `makerworld` / `printables` / `cults3d` / `manual` / etc.
- **NEW** `source` / `created_via` = which **PrintShelf client** created the row
  — `web` / `extension` / `api` / `shortcut` / `import` / `seed` / `unknown`.
  A print can be `source_platform=makerworld` AND `created_via=extension`.

### Scope
Add `created_via` to every user-created entity: **filaments, prints** (and
consider **printers, collections** for completeness).

### Mechanism (proposed)
First-party clients declare themselves with an HTTP header on every create:
`X-PrintShelf-Client: <web|extension|shortcut|slicer>`.
Server resolves `created_via` at create time:
- Header present + recognized → use it.
- Bearer-token (API key) request, no/unknown header → `api`  ← this is the
  "someone used the raw API / a third-party integration" case Cam wants visible.
- Session-cookie request (dashboard), no header → `web`.
- `/share?url=` iOS Shortcut flow → `shortcut`.
- `tools/printshelf_postprocess.py` → `POST /api/prints/ingest` → `slicer`.
- Store as a short string column (default `unknown`, nullable=False), indexed.

### Client changes needed
- **Chrome extension** (`chrome-extension/background.js`): add
  `X-PrintShelf-Client: extension` header to the `/api/prints/queue`,
  `/api/filaments`, and `/api/filaments/import-url` POSTs.
- **Web dashboard** create paths: set `web` server-side (session auth) or via
  header on the HTMX forms.
- **`/share` flow** → `shortcut`. **ingest** → `slicer`.

### Backfill (best-effort, don't guess wrong)
- Prints with `source_platform != 'manual'` → most likely `extension` (that's
  how model pages get captured) but could be web URL-import → mark `unknown`
  unless we can tell them apart; don't overclaim.
- Filaments with a store `source_url` → likely `extension`; without → `web`.
- Mark anything uncertain `unknown` rather than a wrong definite value.

### Surface it
- Admin dashboard: a **"By source"** breakdown for filaments + prints (mirror
  the existing affiliate "By surface" section) so this question is a real query,
  not a manual DB dig. Split first-party (`web`/`extension`/`shortcut`) vs
  external `api`.
- Bonus: cross-tab source × platform (e.g. "extension users overwhelmingly log
  MakerWorld") to guide where to deepen integrations.

---

## P2 — Verify the Printables / Cults3D / Thingiverse scrapers  (possible bug, not preference)

Live prod data (2026-08-06): prints by `source_platform` = **MakerWorld 291,
Printables 3, Thingiverse 0, Cults3D 0**, despite all four being supported in
the extension's `content/inject.js` + host_permissions. A near-total flatline on
3 of 4 supported sites usually means a **broken content script**, not that
nobody uses them. Do a live capture test on each before assuming it's just user
preference. (Applies to both the extension and the web URL-import path.)

The automated Tier-1 harness (`backend/scripts/extension_qa.py`) covers the
create + `created_via` path. A Tier-2 harness (`backend/scripts/extension_qa_scrape.py`,
added 2026-08-06) drives the REAL content scripts on live model pages headed.

**Tier-2 findings (2026-08-06, headed, several runs — NET: no scraper bug found):**
- **Thingiverse — WORKS.** FAB injects, scrape returns the real title
  ("ANAVI Handle desktop mount"). Its prod **0 is user behavior, not a broken
  scraper** — don't "fix" it; promote it if anything.
- **Printables — WORKS (earlier "bug" was a test artifact).** On a DIRECT model
  load (how users arrive from Google / a shared link / a new tab) the scrape is
  correct ("Ultimate Weekly Pill Organizer & Dispenser Gravity Cascade"). A
  standalone DOM probe confirmed the page has correct JSON-LD name + og:title +
  h1. The earlier "www.printables.com" only reproduced when the harness reached
  the page via listing→click (SPA soft-navigation → content script scraped before
  hydration → fell back to document.title). Possible LOW-PRI edge case: a user who
  browses Printables internally and clicks the FAB mid-soft-nav could get the site
  name. Dominant path is fine; not worth a fix now.
- **MakerWorld — works (prod 291); not re-verified in-harness.** Its listing
  defeats anchor-scraping (SPA); no live direct URL was on hand to test.
- **Cults3D — UNVERIFIABLE via harness: Cloudflare "Just a moment…" challenge**
  blocks the automated browser (a real human browser passes it). So its prod 0 is
  NOT shown to be a scraper bug — it's just untestable this way. Needs a 30-sec
  manual click-through on a real Cults3D model to confirm the FAB + scrape work.

**Bottom line:** every scraper reachable by the harness works. The 291/3/0/0
flatline is a **traffic/behavior** story (which sites users actually import
from), not broken content scripts. Cults3D is the only unconfirmed one (Cloudflare).
Remaining optional work: get past Cloudflare (real user profile / manual) to
confirm Cults3D; add live `direct` URLs for makerworld/cults3d to the harness.

---

## P3 — Close the print → filament adoption gap

Prod data: **46 distinct users have logged a print, but only ~7 have saved a
filament** (and 242/251 filaments are Cam's own dogfooding — real external
filament-savers ≈ a handful). Filament-saving is where the affiliate revenue
lives, and it's not being discovered. Ideas:
- Post-print-log prompt: "Saved from MakerWorld — track the filament you used
  too?" (a version of this shipped 2026-07-12 as the 3-tier picker; measure
  whether it moved the needle now that we can attribute source).
- Make the extension's filament-save affordance more discoverable on store pages.

---

## P4 — Extension telemetry / health

Zero visibility into extension usage beyond the Web Store's public "~101 users"
(active-users figure; Google no longer shows lifetime installs publicly — the
install/uninstall + weekly-active trend is only in the CWS Developer Dashboard).
Consider lightweight first-party event logging: button clicks, save successes/
failures, per-site capture failures (feeds P2). Respect privacy / keep minimal.

---

## Monetization backlog (pre-scale — adoption is the real lever right now)

At ~46 lightly-active users and ~6 real filament-savers, revenue features are
premature vs. getting filament-saving adopted. But latent in the data:
- **Affiliate on every saved filament** — extension already captures the store
  URL; make the in-app buy-again/product link carry the tag. **Amazon is ~65%
  of saves and Associates is already set up** → commission *and* feeds the
  ≥10-Amazon-sales/30d API-eligibility floor SSBT depends on. Cleanest option.
  (Cross-check with the known affiliate-wiring gaps in `backend/affiliate.py`.)
- **Pro-gate price-drop / restock alerts** — we already store `price_at_save` +
  `source_url`. Poll them, alert on drops → user clicks affiliate link to rebuy.
  One feature = retention + affiliate clicks + Pro upgrades.
- **Sponsored / featured filament brands** — later, once volume justifies it
  (Polymaker / Bambu are already affiliate partners).

---

## Admin "Is it earning?" false-green (from 2026-08-06 admin work)

The admin `/admin` "Is it earning?" table marks a store "✓ earning" whenever its
env var is merely *set* — but per the known affiliate-wiring gaps
(Awin/Polymaker/MatterHackers), the attribution can still be wrong. Make the
status reflect actual wiring, not just env-var presence. Needs an audit of
`affiliate.py`'s per-store attribution.

---

_Backlog seeded 2026-08-06 from a Tess review of the extension's real prod
usage. See STATE.md for current shipping state._
