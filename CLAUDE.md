# Claude Code Instructions for PrintShelf

> 3D print tracking web app at printshelf.app. Sibling of SS Book Tracker
> (`~/Downloads/superseriousbooktracker/`) — same stack, mostly-reusable
> patterns. Solo founder (Cam) — ADHD, prefers shipping over deliberating.

## Stack

- **Backend:** FastAPI + SQLAlchemy + Alembic
- **DB:** PostgreSQL on Railway (SQLite fallback for local dev)
- **Auth:** JWT (header) + per-user API key (header) + session cookie (web)
- **Web UI:** Server-rendered Jinja templates, plain form POSTs. No JS framework.
- **Storage:** Cloudflare R2 (S3-compatible) for photos, with local-filesystem fallback in dev.
- **Deploy:** Railway. Two services: `printshelf-staging` (branch: `staging`) and `printshelf` (branch: `main`). Auto-deploy on push.
- **Domains:** printshelf.app (prod), staging.printshelf.app (staging), cdn.printshelf.app (R2 public CDN).

## File layout

```
backend/
  main.py                  # FastAPI app, router wiring, /api/health, /api/auth/*
  auth.py                  # JWT, API-key, cookie session — all on one Bearer dependency
  models.py                # SQLAlchemy: User, Printer, Filament, Print, CommunityFilament, ImportCache
  limits.py                # Free-tier caps (50 prints, 10 filaments) + cap-hit logging
  storage.py               # Photo storage abstraction. R2 if all 5 R2_* vars set, else local.
  import_service.py        # URL → metadata extractor (Printables/Thingiverse/Cults3D + Makerworld slug fallback)
  alembic/                 # Migrations. init_db() runs alembic upgrade head on startup.
  routes/
    printers.py            # /api/printers — JSON CRUD
    filaments.py           # /api/filaments — JSON CRUD
    prints.py              # /api/prints — JSON CRUD + /queue + /{id}/printed
    uploads.py             # /api/uploads/photo — multipart, returns {url, storage}
    imports.py             # /api/import-url — body {url} → {title, designer, thumbnailUrl, ...}
    homepage.py            # GET / — Jinja homepage with featured prints gallery
    web_auth.py            # /signup, /login, /logout, /dashboard (stub)
    web_dashboard.py       # /dashboard/{printers,filaments,prints}{,/new,/{id}/edit}
    profile.py             # GET /u/{username} — public Jinja print wall
  templates/               # Jinja templates (base, signup, login, profile, 404_user, homepage, dashboard/*)
  static/app.css           # Single dark-theme stylesheet (~25KB)
  scripts/
    qa.py                  # 85-check end-to-end QA suite (run before merging staging → main)
    scraper_spike.py       # Original spike that validated OG-tag extraction. Kept as reference.
    smoke_crud.sh          # Quick bash smoke test of the JSON CRUD
    seed_user.py           # Throwaway YAML seeder. Replaced by the dogfood UI flow — don't use for launch.
seed/
  cam.template.yaml        # Template; cam.yaml is gitignored
  reddit_post.md           # Draft launch copy (gitignored)
data/                      # SQLite for local dev (gitignored)
uploads/photos/            # Local upload fallback when R2 isn't configured (gitignored)
```

## Current state (as of 2026-05-22)

- **Production (printshelf.app)**: scaffold + auth + JSON CRUD + Jinja public profiles. Web UI (signup/dashboard/upload/import) is still on `staging` waiting to merge to `main`.
- **Staging (staging.printshelf.app)**: feature-complete for v1 web UI. All 85 QA checks passing.
- **R2**: bucket created, custom domain wired. API token created. Env vars **except `R2_PUBLIC_URL_BASE`** are set on both Railway services. Adding that one var flips uploads from ephemeral local → durable R2.
- **Open work**: see Tasks section.

## Build history (Council-driven)

The Council was convened twice and shaped this project:

1. **First Council (early)** — picked the architecture: API-only + Jinja for `/u/{username}`, defer Stripe and React SPA. Core CRUD first.
2. **Second Council (mid-build)** — picked the launch sequence: photos > endpoints, drag-drop to R2, ship Reddit post when /u/cam is post-worthy. Resulted in the YAML seed plan.
3. **Cam pivot (this session)** — rejected manual seeding entirely. New plan: build the real product (signup + dashboard + upload + URL import), Cam dogfoods, /u/cam fills organically. Reddit post deferred until product is shippable.

## Operational gotchas

- **Railway containers are ephemeral.** Local-mode uploads (anything under `uploads/photos/`) DO NOT survive a redeploy. Always run with R2 configured in staging/prod. See `memory/project_railway_ip_blocked_by_makerworld.md`.
- **Makerworld blocks Railway IPs.** Server-side scraping works locally, 403s from Railway. Slug parser in `import_service.py` produces a partial result (title from URL) when fetch fails. Real Makerworld imports are the Chrome extension's job (future).
- **Pydantic EmailStr rejects RFC-2606 TLDs** (`.test`, `.example`, `.invalid`, `.localhost`). Use `@printshelf.app` for any throwaway test emails.
- **Title field on print form is not HTML5-required.** If `source_url` is set, server auto-imports title from URL on save. If neither title nor URL is provided, server returns 400 with a helpful message.
- **Print form is multipart/form-data** (because of the photo file input). All form posts that hit `/dashboard/prints` must use multipart.

## Conventions

- All JSON API responses use **camelCase** keys (`thumbnailUrl`, `apiKey`). The cached and fresh paths of `/api/import-url` are both normalized to camelCase via `routes/imports.py:_wire_response`.
- All auth endpoints accept **JWT or API key** on the same `Authorization: Bearer` header. The Chrome extension will use the per-user API key.
- All list endpoints support `limit`/`offset` + return `{items, total, limit, offset}`.
- Cross-user references on FK fields are validated server-side and return 400 (not 404) — see `routes/prints.py:_validate_refs`.
- Free-tier caps return **402 upgrade_required** with `{error, resource, limit, current}` payload. Every cap-hit logs a single line so we can decide when to ship Stripe.
- Migrations: `cd backend && alembic revision --autogenerate -m "desc"` then commit the file. Migrations run on startup via `init_db()` in `models.py`.

## Dev workflow

```bash
# Local dev (SQLite, local upload fallback)
source venv/bin/activate
cd backend && python -m uvicorn main:app --host 127.0.0.1 --port 8765

# Full QA suite (85 checks) — run before merging staging → main
python backend/scripts/qa.py --base https://staging.printshelf.app

# Generate a migration after model changes
cd backend && alembic revision --autogenerate -m "what_changed"

# Local upload + import roundtrip
python backend/scripts/qa.py    # creates 2 test users + a print with a photo
```

## Deploy workflow

Mirrors SS Book Tracker:
1. Work on `staging` branch (default). All sessions should be on staging or a feature branch.
2. Push to `staging` → Railway auto-deploys `printshelf-staging`.
3. Manual smoke-test on `https://staging.printshelf.app`.
4. Run `python backend/scripts/qa.py --base https://staging.printshelf.app` → must be 85/85 green.
5. `git checkout main && git merge staging --no-ff && git push origin main` → Railway auto-deploys `printshelf`.
6. `git checkout staging` → return to home base.

**Never** force-push main. **Never** work directly on main.

## Open tasks (when context resumes)

1. **Add `R2_PUBLIC_URL_BASE=https://cdn.printshelf.app`** to both Railway services. (4 of 5 R2 vars are set; this one is missing.)
2. **Verify R2 uploads on staging** — probe via QA suite or manual upload.
3. **Merge staging → main** for production deploy of the web UI.
4. **Chrome extension** (separate codebase under `chrome-extension/`). The wedge — one-click import from Makerworld/Printables/Cults3D/Thingiverse via the rendered DOM (no IP-rep problem since requests come from the user's browser).
5. **Reddit post** — only after Cam has dogfooded the product and /u/cam looks post-worthy.

## Things to avoid

- **Don't write manual seed YAML files** — Cam rejected this approach. Build the real flow instead.
- **Don't add JS frameworks** without asking. Jinja + form POSTs + maybe inline `<script>` snippets is the v1 contract.
- **Don't run QA after every trivial edit** — only after shipping a feature.
- **Don't re-read entire files** that are already in context.
- **Don't suggest the Chrome extension as a code change to this repo** — it's a separate project.
