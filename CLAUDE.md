# PrintShelf — Claude Operating Manual

> 3D print tracker at printshelf.app. Sibling of SS Book Tracker. Solo founder (Cam) — ADHD, prefers shipping over deliberating.

## Project Status

### 🔄 In Progress
- Cam dogfooding printshelf.app at `/@PluggedIn3d`
- Affiliate program signups — set env vars on Railway prod as they arrive: `AMAZON_AFFILIATE_TAG`, `BAMBU_AFFILIATE_REF`, `POLYMAKER_AFFILIATE_REF`, `MATTERHACKERS_AFFILIATE_REF`, `ANYCUBIC_AFFILIATE_REF`
- Railway prod setup needed: add `CRON_SECRET` env var + create Cron service (`0 10 * * *`, `curl -sf -X POST https://printshelf.app/internal/drip -H "X-Cron-Secret: $CRON_SECRET"`)

### 📋 Todo
- Per-print video URL (free feature — content creators link YouTube/TikTok to prints)
- Social link input UX fix (placeholder shows username but user must still type — add "Use @handle" JS fill)
- Reddit launch post
- Makerworld real imports — blocked by Railway IP; Chrome extension is the workaround

### ✅ Done (recent)
- Onboarding drip emails (2026-06-02) — Day-2 "log your first print" + Day-7 "see what others are logging". /internal/drip cron endpoint (secret-gated). 10/10 QA. On prod (117002a).
- Welcome email / sitemap / profile stats / print view links (2026-06-02) — 5/5 QA. On prod (6e50872).
- Queue IA / Explore / Scroll bug (2026-06-02) — Queue removed from sidebar, /explore page, sidebar column fill fix, fieldset overflow fix. On prod (db4dc26).
- Audit fixes (2026-06-01) — mobile hamburger nav, footer Privacy/Terms/Contact, Terms of Service, hero gallery caption, logged-out CTA → example shelf. On prod (ba66a17).
- Stripe Pro billing (2026-06-01) — $4.99/mo or $39/yr. 8/8 QA. On prod (62d914c).
- Chrome extension v0.3.7 — Polymaker, Bambu Lab, Anycubic, MatterHackers, Amazon filament buttons + brand fix.
- Email notifications + verification, follow/feed, search, profile discovery, affiliate redirector, filament URL import — on prod (sessions 9–13).

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
**Completed 2026-06-02 (session 15–16):**
- Welcome email, sitemap, profile stats, print view links — prod (6e50872)
- Onboarding drip emails Day-2 + Day-7 — prod (117002a)

**In progress:**
- Cam dogfooding at `/@PluggedIn3d`
- Affiliate env vars pending when codes arrive
- Railway prod: add CRON_SECRET + create Cron service for /internal/drip

**Immediate next step:** Per-print video URL field (free, content-creator feature) then social link UX fix.
