# PrintShelf — Claude Operating Manual

> 3D print tracker at printshelf.app. Sibling of SS Book Tracker. Solo founder (Cam) — ADHD, prefers shipping over deliberating.

## Project Status

### 🔄 In Progress
- Chrome extension (`chrome-extension/`) — scaffold in repo, not user-facing yet

### 📋 Todo
- Cam dogfoods the app; get /u/cam looking post-worthy
- Reddit launch post — after dogfooding
- Stripe / paid tier — free-tier cap logging in place; ship when cap-hits justify it
- Makerworld real imports — blocked by Railway IP; Chrome extension is the fix

### ✅ Done (recent)
- Full web UI shipped to prod 2026-05-24: signup, dashboard, upload, URL import
- R2 photo storage live on both services — cdn.printshelf.app confirmed
- Print form queued status in dropdown; non-queued status correctly dequeues
- Profile rating filter 422 fixed; non-image upload on edit returns 400 with error
- 85/85 automated QA + 15/15 manual QA passing

### 🔧 Tech Debt
- None flagged

### 📋 QA Log
- **2026-05-24** — 15-section manual QA. Bugs found/fixed: queued dropdown missing, non-image upload silent on edit, profile rating 422. 85/85 auto + 15/15 manual ✅ Merged to prod.

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
**Completed 2026-05-24:**
- Queued status in print form dropdown (edit + create); dequeue correctly on status change
- Non-image upload on edit form now returns 400 with error (was silently ignored)
- Profile rating filter 422 fixed (empty string no longer crashes)
- CLAUDE.md rewritten as full operating manual with status tracking + standing rules
- Full manual QA 15/15 + automated 85/85 passing. Two prod deploys.

**In progress:** Cam dogfooding printshelf.app — building up /u/cam organically.

**Immediate next step:** Keep dogfooding. When /u/cam looks post-worthy, draft Reddit launch post. Fix anything that feels rough in daily use before posting.
