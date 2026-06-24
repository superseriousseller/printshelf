# PrintShelf — Claude Operating Manual

> 3D print tracker at printshelf.app. Sibling of SS Book Tracker. Solo founder (Cam) — ADHD, prefers shipping over deliberating.

## Project Status

### 🔄 In Progress
- Cam dogfooding printshelf.app at `/@PluggedIn3d`
- Affiliate env vars pending: `BAMBU_AFFILIATE_REF`, `POLYMAKER_AFFILIATE_REF`, `MATTERHACKERS_AFFILIATE_REF` (simple `?ref=` params, no code change needed)

### ✅ Done (recent)
- Human-readable hybrid print URLs (2026-06-23) — `/@user/prints/{id}-{slug}` (e.g. `/@PluggedIn3d/prints/32-emergency-guitar-picks...`) replacing opaque `/prints/{id}`. Numeric ID stays the lookup key so the slug is **decorative** — old bare-ID links 301-redirect (zero breakage, no DB migration). `slugify()` in models.py (NFKD accent-fold→ascii, lowercase, alnum→hyphen, cap 60 at word boundary; empty/all-emoji title → bare `{id}`, no trailing hyphen) + `Print.slug`/`Print.url_id` props. `public_print_detail` takes `print_ref: str`, parses leading int, 301-canonicalizes bare-ID/stale-slug/wrong-case → current `{id}-{slug}`. All public links emit `url_id` (profile, explore[dict key], search, feed, prints_list, print_detail og:url+canonical+related, sitemap[query fetches title]). `/rate`+`/queue` POSTs stay bare-int. No per-user badge (Cam's call — global PK ≠ per-user count, so it'd mislead). 8/8 QA PASS + 85/85 + 6/6 redirect cases. On prod (902e89f).
- Dashboard mobile grid blowout fix (2026-06-17) — `.dash-shell` used `grid-template-columns: 1fr` (=`minmax(auto,1fr)`); the auto-min forced the track to content min-content (~723px), so `.dash-main` overflowed and was clipped by an `overflow-x:hidden` band-aid → nav/stats/cards cut off & unreachable on ALL 12 dashboard pages. Fixed with `minmax(0,1fr)` on both shell rules; nav now wraps (all items tappable). Also fixed account `.dash-socials` fieldset overflow (`min-width:0`). **`visual_audit.py` upgraded** to flag CLIPPED-UNREACHABLE content (element past viewport w/ no scrollable ancestor) — the bug class the page-level scrollWidth check missed; proven to catch the regression. On prod (ed1fad0).
- Full Playwright visual/function audit (2026-06-17) — `backend/scripts/visual_audit.py` loads every HTML screen at desktop+mobile, flags non-200/console errors/mobile horizontal overflow + screenshots. Found 1 bug: `/developers` API table overflowed mobile +23px → fixed (scrolls in its own box). 40 loads clean + 8 functional checks pass. On prod (68691e8 fix, b3acfc4 script).
- Inline rating + 3D categories (2026-06-16) — owner-only **blank** star widget on public detail page (hollow ☆ at rest, fill on hover, click to set; saved value shows in title badge + "N★" hint; badge syncs live). Session-cookie route `POST /@{user}/prints/{id}/rate` (API PATCH is Bearer-only); non-owner 403, unauth 401; no-JS form fallback. Categories expanded to 11 3D-printing-focused (slugs preserved, existing tags safe); Explore pills now data-driven from `PRINT_CATEGORIES`, detail badge uses `PRINT_CATEGORY_LABELS`. Star widget mirrors SS Book Tracker `StarRating.jsx`. 7/7+2 QA PASS, 2-fix cycle (badge live-sync, mobile nowrap). On prod (3c8f66a). Verified JS via jsdom (Playwright can't reach host localhost in sandbox).
- Browse-by-brand filament picker (2026-06-16) — added collapsible per-brand `<details>` groups below the token search (Jinja `groupby('brand')`, count badges). Chips stay the single source of truth: browse checkboxes carry **no name attr** (no double-submit), only mirror chip state. Bidirectional sync (tick row↔add chip, ×↔uncheck row, search-add↔check row) via `setRowChecked` helper. Edit pre-checks rows server-side from `selected_ids`. 7/7 + 3 edge QA PASS. On prod (b524f74). Verified JS sync via jsdom (Playwright can't reach host localhost in sandbox).
- Filament token/chip picker (2026-06-15) — replaced 200+ item checkbox list on print form with a compact token multi-select: type to filter (client-side over JSON-embedded filaments, dropdown capped at 10), click to add a colored chip, ×/Backspace to remove, no duplicate-add. Edit forms pre-populate chips **server-side** via `selected_filaments` ctx var (JS inits its `selected` Set from DOM `data-id`s — avoids ID-matching bugs). 11/11 QA PASS (1-fix cycle: edit pre-population). On prod (c1f6605).
- Makerworld CF proxy (2026-06-11) — Cloudflare Worker (`cloudflare-worker/fetch-proxy.js`) proxies Makerworld fetches through CF edge IPs, bypassing Railway's IP block; full title + thumbnail returned; OG title suffix stripped. 3/3 QA PASS. On prod (ae857fd). Env vars: `CF_FETCH_PROXY_URL`, `CF_FETCH_PROXY_SECRET` (both envs).
- Account page: API key moved above Danger Zone (2026-06-11). On prod (ae857fd).
- Mobile form fix + polish (2026-06-08) — form rows collapse at ≤600px (was ≤480px); link-row stacks on mobile; sidebar nav 44px tap targets + scroll fade; modal shadow. 7/7 QA PASS. On prod (c332545).
- Chrome extension v0.3.9 (2026-06-08) — removed brand names from manifest + store description to pass keyword spam review. No functional changes.
- Category field + explore filtering (2026-06-08) — category on print form (tools/household/art/toys-games/miniatures/functional/other); explore pills now live filters; Failed pill added; sort/pagination preserve filters; detail page badge links to explore. 11/11 QA PASS. On prod (bcce5c2).
- Design system cleanup (2026-06-08) — base font 16px; --stat-queued/--stat-done tokens; removed --radius-lg/--radius-xl; table border-radius fixed (border-collapse: separate); all pill radii tokenized; filter bar pills; Go button removed. 14/14 QA PASS. On prod (9183a43).
- P0 mobile blockers (2026-06-08) — hamburger 44×44px; filter chip + Edit/Delete tap targets 44px; iOS input zoom fix (16px !important); sidebar overflow-x hidden; prints header full-width. 12/12 QA PASS. On prod (f8a05f5).
- Thumbnail focal point drag (2026-06-07) — drag crosshair overlay on photo upload page saves focal_x/focal_y via PATCH API; all thumbnails (profile, explore, homepage, dashboard, feed) respect object-position. Migration a2b3c4d5e6f7. 11/11 QA PASS. On prod (c0177eb).
- UX audit fixes (2026-06-06) — filament typeahead search on print form; Explore sort control (Newest/Oldest/Top rated); ghost button contrast fix; Cancel button styling; human-readable print dates.
- Filament search API + Print Links API (2026-06-06) — GET /api/filaments?q= fuzzy search; POST/PATCH /api/prints accepts links[] array. On prod (4e752b6).
- Chrome extension v0.3.8 submitted to Chrome Web Store (2026-06-06) — SUNLU + FlashForge stores, finish field extraction, Bambu Lab screenshot added.
- Print Links (2026-06-05) — per-print labeled affiliate links (max 5) to accessories (Amazon, Bambu, Polymaker, Anycubic, MatterHackers, SUNLU, FlashForge); domain allowlist enforced server-side; tags injected at render-time; "Goes great with" chips on public detail page. 5/5 QA (3-fix cycle: HTML field name mismatch, update-path validation, URL-only validation). On prod (1bfe7bb).
- Sortable table headers + filter chips (2026-06-05) — filaments + printers tables sortable by column; filament status filter chips; admin Refresh button + mobile layout; site-wide mobile CSS. On prod (49ce449).
- Chrome extension v0.3.8 (2026-06-04) — SUNLU + FlashForge store support; finish extraction from product title (Silk/Matte/Glow/etc.); SUNLU brand fix (Shopify JSON-LD override). 8/8 QA. On prod (027dbc3).
- Affiliate disclosure footer (2026-06-04) — FTC + Amazon Associates required language. On prod (bac0c83).
- Print again button (2026-06-04) — owner sees "Print again" on detail page; pre-fills new print form with title, designer, source, printer, filaments, slicer settings; photo blank; notice banner shown. 8/8 QA. On prod (ba09c69).
- Filament finish field (2026-06-04) — free-text finish field (Silk, Matte, Glow, etc.) on filament form with datalist suggestions; shown on chips + list. On prod (0db617c).
- Affiliate expansion (2026-06-04) — Anycubic (Awin), SUNLU, FlashForge (Impact), filament price/kg + Buy link on print detail, filament own/want UX. On prod (eb22374). Env vars set: `AMAZON_AFFILIATE_TAG`, `AWIN_AFFILIATE_ID`, `ANYCUBIC_AWIN_MERCHANT_ID`, `SUNLU_AFFILIATE_REF`, `FLASHFORGE_IMPACT_PID`.
- Signup fix (2026-06-04) — removed HTML5 pattern attr blocking all signups. On prod (adf981d).
- Shelf analytics + API docs (2026-06-02) — on prod (5a3fa53). Print cost tracking (fd32413). Per-print video URL (0e6401d). Onboarding drip emails (117002a). Stripe Pro billing (62d914c). Sessions 9–13 features.

### 🔧 Tech Debt
- None flagged

### 📋 QA Log
- **2026-06-23 (session 27)** — Human-readable hybrid print URLs (`/@user/prints/{id}-{slug}`). Feature: 8/8 manual QA PASS (Cam, build 902e89f) + 85/85 automated + 6/6 redirect cases. Then a 3-pass hardening sweep (test-and-fix → grill → techdebt): added a 12-case `slugify` unit battery (accents/emoji/punct/CJK/word-boundary cap — all pass); adversarial route grill found **0 bugs** (malformed refs → safe 303 profile; CRLF echo → quoted to `%0D%0A`, int-guard rejects pre-echo; open-redirect impossible — all targets relative `/@…`); techdebt found+fixed 1 self-introduced item (sitemap duplicated the `{id}-{slug}` format → extracted `print_url_id()` single source of truth, byte-identical output). Feature on prod (902e89f), refactor on prod (8ea0e99).
- **2026-05-25 (session 5)** — Filament extension button (Polymaker only). Four QA rounds: v0.3.0 (`fd024d8`) shipped feature; v0.3.1 (`1ae3943`) fixed toast `[object Object]` + malformed `color_name`; v0.3.2 (`4eecd6a`) fixed empty `color_hex`; v0.3.3-4 added orphan-context toast + version-log polish. Final QA on v0.3.2: all 3 variants (Panchroma Matte Cotton White #f4efeb, PolyLite Black #030305, Panchroma Matte Lavender Purple #9572bf) saved with correct color_name + color_hex; page-wide hex fallback rejected 15+ stray CSS hexes on PolyDryer Box XL. Merged to prod (3501e5e).
- **2026-05-25 (session 4)** — Filament URL import + affiliate redirector. Cam manual QA found 2 bugs on `9c34ce5` (MatterHackers source_url truncation, misleading green notice for unknown stores) → fixed in `68025be`. Notice-color polish in `ceed648`. Final sanity: 85/85 automated QA on staging + 5/5 manual spot checks. Merged to prod (382e9b6). The "Step 5b /buy strips MatterHackers URL" finding was investigated and proved to be MatterHackers's own server redirect chain, not our code.
- **2026-05-24 (session 3)** — 23/23 manual QA pass on build 38e52af. All 5 features green. Merged to prod (9c4053b).
- **2026-05-24 (session 2)** — 15/15 manual QA. Print detail page, clickable cards, title fixes. Merged to prod.

---

## Stack
- **Backend:** FastAPI + SQLAlchemy + Alembic | **DB:** PostgreSQL/Railway, SQLite local
- **Auth:** JWT + per-user API key + session cookie on one `Authorization: Bearer` dependency
- **Web UI:** Jinja templates + form POSTs. No JS framework.
- **Storage:** Cloudflare R2 → cdn.printshelf.app. Local fallback in dev only (ephemeral on Railway).
- **Deploy:** Railway. `staging` → `printshelf-staging`. `main` → `printshelf`. Auto-deploy on push.

## Key Files
```
backend/main.py            # app entry, router wiring
backend/auth.py            # all auth logic
backend/models.py          # User, Printer, Filament, Print, ImportCache + enums
backend/limits.py          # free-tier caps (50 prints, 10 filaments)
backend/storage.py         # R2 / local abstraction
backend/import_service.py  # URL → metadata (Printables/Thingiverse/Cults3D + Makerworld slug)
backend/routes/            # printers, filaments, prints, uploads, imports, web_dashboard, profile
backend/scripts/qa.py      # 85-check automated QA suite (httpx, no browser)
backend/scripts/visual_audit.py  # Playwright all-screens desktop+mobile audit (overflow/console/screenshots)
chrome-extension/          # separate project — do not suggest changes here as backend changes
```

## Operational Gotchas
- **Railway containers are ephemeral** — local uploads vanish on redeploy. R2 required for staging/prod.
- **Makerworld blocks Railway IPs** — slug parser gives partial result; real imports are Chrome extension's job.
- **Pydantic EmailStr** rejects `.test`/`.example`/`.localhost` — use `@printshelf.app` for test accounts.
- **Print form is multipart/form-data** — all `/dashboard/prints` POSTs must use multipart.
- **Title not HTML5-required** — server auto-imports from `source_url` if blank; 400 if neither present.
- **Stripe prod go-live** — set these 4 env vars on Railway prod (Stripe live-mode Dashboard):
  - `STRIPE_SECRET_KEY` = `sk_live_...`
  - `STRIPE_WEBHOOK_SECRET` = `whsec_...` (from Webhooks → printshelf.app/stripe/webhook endpoint)
  - `STRIPE_PRICE_MONTHLY` = `price_live_...` ($4.99/mo product)
  - `STRIPE_PRICE_ANNUAL` = `price_live_...` ($39/yr product)
  - Note: Railway webhook delivery is unreliable — sync success-page upgrade is the primary path; webhook handles lifecycle events only.
- **Stripe webhook** — Railway staging webhook delivery unreliable (pending_webhooks=1, no inbound requests). Worked around via httpx session retrieve on /dashboard/billing/success. Webhook still handles subscription cancellations/renewals if it fires.

## Conventions
- JSON API: camelCase keys. Auth: JWT or API key on same Bearer header. Lists: `{items,total,limit,offset}`.
- Cross-user FK refs → 400. Free-tier cap → 402 `upgrade_required`. Migrations run on startup via `init_db()`.

## Dev & Deploy
```bash
source venv/bin/activate && cd backend && python -m uvicorn main:app --host 127.0.0.1 --port 8765
python backend/scripts/qa.py --base https://staging.printshelf.app
```
Deploy: push `staging` → smoke test → 85/85 QA → merge to `main` → push → return to `staging`. Never force-push main. Never work directly on main.

**Browser/visual QA (Playwright):** The sandboxed browser can't reach `127.0.0.1`, but it CAN reach the Mac's **LAN IP** or any public URL. Best for iterating on uncommitted changes: bind uvicorn `--host 0.0.0.0` and point Playwright at `http://<LAN-IP>:<port>` (`ipconfig getifaddr en0` → e.g. `192.168.50.250`). Renders local code, no deploy. Or use `https://staging.printshelf.app` for deployed code (how SS Book Tracker's `e2e/` does it). Driver: `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3` (playwright 1.57). Set `viewport` for mobile (390/375) + `page.screenshot()` for true pixel-layout proof. Gotcha: other projects squat ports (saw `app.main:app` on 8765) — pick a clean port (8770) and don't kill non-printshelf servers. jsdom-against-local still fine for pure JS/DOM logic. Local owner-only login: `filtest@printshelf.app` / `testpass1`.

---

## Standing Rules

**Task Tracking** — Update status sections after every major task and at end of every session. Maintain ARCHIVE.md for removed content.

**File Hygiene** — Keep under 150 lines. Compress Done first. Drop completed bugs after 2 sessions.

**Definition of Done** — Feature works · Error handling in place · No hardcoded secrets · Meaningful ops logged · Self-check for adjacent breakage · Performance acceptable · Non-obvious code documented.

**Feature Workflow** — Research → note tradeoffs → scope steps → document plan in CLAUDE.md → then code. Never start without a documented plan.

**Bug Workflow** — Identify root cause before fixing. Never patch symptoms. Document cause and change. Verify nothing adjacent broke.

**Breaking Changes** — Flag explicitly before touching anything that affects existing behavior. Wait for confirmation.

**Error Handling** — No silent errors. User-facing messages must never expose internals or stack traces. Every external call must have error handling.

**Logging** — Log all meaningful ops (external API calls, background processes, state changes) at production-debug level.

**Secrets** — Never hardcode credentials. Always use env vars. Flag immediately if found.

**Performance** — Basic check before staging. Flag anything slow under real usage.

**Self-Check** — After any change: adjacent breakage? Edge cases? Consistent with codebase? Note in QA Log.

**Customer-Facing QA Gate:**
1. Deploy to staging. Stop.
2. Generate and post QA script (format below). Say: *"Staging is ready for QA. Waiting for your go-ahead before merging."* Stop.
3. Merge only after explicit confirmation. If QA fails — fix, redeploy, new script, wait again. Never auto-merge.

```
QA SCRIPT — [Feature] | [Date]
PRE-CONDITIONS: - [ ] ...
STEPS: - [ ] Step N: Go to... expect...
EDGE CASES: - [ ] ...
PASS CRITERIA: All boxes checked, no unexpected behavior.
```

**Rollback Awareness** — Note rollback path before every prod deploy. Flag if none exists.

**Documentation** — Document non-obvious decisions in code or DECISIONS.md. Clarity for a cold return in 3 months.

**Session Handoff** — End every session with a "Next Session Starts Here" block: completed, in progress, immediate next step.

**Re-reading** — If asked to re-read CLAUDE.md mid-session, do so immediately and treat it as current instructions.

---

## Next Session Starts Here
**Completed 2026-06-23 (session 27):**
- Human-readable hybrid print URLs — `/@user/prints/{id}-{slug}`; numeric ID stays the lookup key, slug is decorative, old bare-ID links 301-redirect (no migration). `slugify()`+`Print.url_id` in models.py; route 301-canonicalizes bare/stale/wrong-case; all public links + sitemap emit slug. 8/8 QA + 85/85 + 6/6 redirect cases PASS. On prod (902e89f).

**Completed 2026-06-16 (session 26):**
- Filament token/chip picker — replaced 200+ item checkbox list on print form with token multi-select (type→filter→chip). Edit forms pre-populate chips server-side. 11/11 QA PASS. On prod (c1f6605).
- Browse-by-brand groups — collapsible per-brand sections below the search, bidirectionally synced with chips. 7/7 + 3 edge QA PASS. On prod (b524f74).
- Inline blank-star rating on detail page + 11 3D-printing categories (Explore pills data-driven). 7/7 + 2 edge QA PASS. On prod (3c8f66a).

**In progress:**
- Cam dogfooding at `/@PluggedIn3d`
- Affiliate env vars still pending: `BAMBU_AFFILIATE_REF`, `POLYMAKER_AFFILIATE_REF`, `MATTERHACKERS_AFFILIATE_REF`
- Prod env vars needed: `CF_FETCH_PROXY_URL`, `CF_FETCH_PROXY_SECRET` (set on Railway prod service)

**Immediate next step:** Set CF proxy env vars on Railway prod, then next feature — Cam's call.
