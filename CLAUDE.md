# PrintShelf — Claude Operating Manual

> 3D print tracker at printshelf.app. Sibling of SS Book Tracker. Solo founder (Cam) — ADHD, prefers shipping over deliberating.

## Project Status

### 🔄 In Progress
- Chrome extension (`chrome-extension/`) — **v0.3.5 submitted to Chrome Web Store 2026-05-29, pending review** (filament button on Polymaker + model pages). First review may be slow: host permissions + Authentication-info/Website-content data disclosure trigger in-depth review.
- Cam dogfooding printshelf.app — building up /@cam organically
- Affiliate program signups (Amazon Associates, Bambu, Polymaker, MatterHackers, Anycubic) — set env vars on Railway prod as they come in: `AMAZON_AFFILIATE_TAG`, `BAMBU_AFFILIATE_REF`, `POLYMAKER_AFFILIATE_REF`, `MATTERHACKERS_AFFILIATE_REF`, `ANYCUBIC_AFFILIATE_REF`
- Extension Phases 3+ — add Anycubic, MatterHackers, Bambu, Amazon to `STORES` in `inject_filament.js`. Each needs its own swatch selectors. Architecture proven on Polymaker.

### 📋 Todo
- Reddit launch post — after /@cam looks post-worthy
- Stripe / paid tier — free-tier cap logging in place; ship when cap-hits justify it
- Makerworld real imports — blocked by Railway IP; Chrome extension is the fix

### ✅ Done (recent)
- Chrome Web Store submission (v0.3.5, 2026-05-29) — trimmed manifest `description` to 119 chars (132 limit), replaced placeholder icons with real 16/48/128 PNGs, declared single-purpose + permission justifications + data disclosure (Authentication info + Website content), No remote code, privacy policy at /privacy. Paste-ready listing copy lives in `chrome-extension/PUBLISH.md`.
- Filament Chrome extension button (Polymaker, v0.3.4) — one-click "Add filament" on `/products/*` pages. Reads selected-variant color name + hex from the DOM (Polymaker packs both into the swatch label's textContent); falls back to "HEX Code: #…" in the product description for the PolyLite line. Server-side `POST /api/filaments/import-url` provides brand/material/price. Status defaults to `want`.
- Delete-confirm modal — replaced native `confirm()` across filaments / printers / prints lists with a centered modal overlay (Cam's parallel work).
- Filament URL import (Amazon, Bambu, Polymaker, MatterHackers, Anycubic) — paste a product URL, pre-fills brand/material/color/price from OG tags + JSON-LD
- Affiliate redirector — `/dashboard/filaments/{id}/buy` injects per-store tag at click-time; bare URLs in DB
- Hard-error vs soft-warn notice styling (red `notice-error` vs yellow `notice-warn`)
- Search + sort on prints list (title search, sort by newest/oldest/title/rating/date)
- Sidebar counts — live Prints / Queue / Filaments badges in nav
- Overview dashboard stats row (prints, queued, success %, filaments, printers)
- Public profile cards — filament material chips with color swatches
- Filament form color picker — native input[type=color] synced with hex field
- Print detail page, clickable cards/rows, Printables title fix, thumbnail field hidden
- Chrome extension v0.2.0 title bugs fixed (JSON-LD preferred, doubled attribution stripped)

### 🔧 Tech Debt
- None flagged

### 📋 QA Log
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
backend/scripts/qa.py      # 85-check automated QA suite
chrome-extension/          # separate project — do not suggest changes here as backend changes
```

## Operational Gotchas
- **Railway containers are ephemeral** — local uploads vanish on redeploy. R2 required for staging/prod.
- **Makerworld blocks Railway IPs** — slug parser gives partial result; real imports are Chrome extension's job.
- **Pydantic EmailStr** rejects `.test`/`.example`/`.localhost` — use `@printshelf.app` for test accounts.
- **Print form is multipart/form-data** — all `/dashboard/prints` POSTs must use multipart.
- **Title not HTML5-required** — server auto-imports from `source_url` if blank; 400 if neither present.

## Conventions
- JSON API: camelCase keys. Auth: JWT or API key on same Bearer header. Lists: `{items,total,limit,offset}`.
- Cross-user FK refs → 400. Free-tier cap → 402 `upgrade_required`. Migrations run on startup via `init_db()`.

## Dev & Deploy
```bash
source venv/bin/activate && cd backend && python -m uvicorn main:app --host 127.0.0.1 --port 8765
python backend/scripts/qa.py --base https://staging.printshelf.app
```
Deploy: push `staging` → smoke test → 85/85 QA → merge to `main` → push → return to `staging`. Never force-push main. Never work directly on main.

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
**Completed 2026-05-29 (session 6):**
- Chrome Web Store submission (v0.3.5) — fixed the upload-blocking manifest `description` (136 → 119 chars; 132 limit), confirmed real 16/48/128 icons (old 128 was a 306-byte placeholder), built the upload zip, and filled the dashboard: single-purpose, storage + combined host-permission justifications, No remote code, data disclosure (Authentication info + Website content), all three certifications, privacy URL https://printshelf.app/privacy. Submitted, pending review.
- All committed on `staging` (icon/manifest commits `2901571`, `e18d754`); tree clean.
- URL migration `/u/{username}` → `/@{username}` — canonical routes updated in `profile.py`, all templates + `qa.py` updated, 301 redirects in place for legacy links. Needs staging deploy + QA before merging.

**In progress:**
- Chrome extension v0.3.5 **pending Web Store review** — watch for approval or a policy-cited rejection email.
- Cam dogfooding printshelf.app
- Affiliate signups pending — env vars to set on Railway prod when codes arrive: `AMAZON_AFFILIATE_TAG`, `BAMBU_AFFILIATE_REF`, `POLYMAKER_AFFILIATE_REF`, `MATTERHACKERS_AFFILIATE_REF`, `ANYCUBIC_AFFILIATE_REF`

**Immediate next step:** Deploy URL migration to staging and run QA (verify `/@cam` loads, `/u/cam` 301-redirects, all internal links use `/@`). Then merge both icon/manifest commits and URL migration to main together. Meanwhile: Extension Phases 3+ OR affiliate signups.
