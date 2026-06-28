# PrintShelf — Claude Operating Manual

> 3D print tracker at printshelf.app. Sibling of SS Book Tracker. Solo founder (Cam) — ADHD, prefers shipping over deliberating.

## Project Status

### 🔄 In Progress
- **Google OAuth login (session 28i)** — "Sign in with Google". No new deps (manual flow via `httpx`+`jwt`, both present). PLAN:
  1. `models.py`: `User.google_sub` (String(64), nullable, unique, indexed) — links/marks Google accounts. Migration `a8b9c0d1e2f3` (down `f7a8b9c0d1e2`).
  2. Routes in `web_auth.py` (reuse `_set_session_cookie`/`_PROD`): `GET /auth/google/login` → CSRF `state` in short-lived signed cookie (+`next`), redirect to Google authorize (`scope=openid email profile`, `redirect_uri={APP_URL}/auth/google/callback`, `prompt=select_account`). `GET /auth/google/callback` → verify state, exchange code at `oauth2.googleapis.com/token`, fetch `openidconnect.googleapis.com/v1/userinfo`; find by `google_sub`→else email (link, set sub)→else create (unique username from name/email via `USERNAME_RE`, random unusable `password_hash`, `email_verified=True`, avatar from Google pic, `send_welcome`); set session cookie → redirect `next`.
  3. Config-gated: `_google_configured()` (GOOGLE_CLIENT_ID+SECRET set). Button only renders when configured (`google_enabled` ctx on login/signup); login route 303s to /login if unconfigured. **Deploys safe before creds exist.**
  4. `login.html`/`signup.html`: "Continue with Google" button + divider.
  Env (Cam provisions): `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`; register redirect URIs `https://printshelf.app/auth/google/callback` + `https://staging.printshelf.app/auth/google/callback` in Google Console. Account-link by verified email is safe. QA: 85/85 + gating/redirect-URL/username-gen unit tests locally; real Google round-trip on staging after Cam sets creds.
- Cam dogfooding printshelf.app at `/@PluggedIn3d`
- Affiliate env vars pending: `BAMBU_AFFILIATE_REF`, `POLYMAKER_AFFILIATE_REF`, `MATTERHACKERS_AFFILIATE_REF` (simple `?ref=` params, no code change needed)

### ✅ Done (recent)
- Collections (2026-06-28) — user-named groups of prints (many-to-many). `Collection` (name, description, `.url_id` via `print_url_id`) + `CollectionPrint` join (unique pair); migration `f7a8b9c0d1e2` (2 tables); `FREE_TIER_COLLECTION_LIMIT=10` via `enforce_collection_limit` (web→/dashboard/upgrade on 402). Dashboard (`/dashboard/collections` list+create, `/{id}` manage rename/description/delete + member grid w/ remove, `/{id}/remove`); sidebar nav + count. Add-from-print: owner checkboxes on print-detail → `POST /@{u}/prints/{id}/collections` syncs membership (session-cookie like `/rate`, ownership re-checked, foreign ids ignored). Public: `GET /@{u}/collections/{ref}` (bare-id/stale-slug→301; visitors see only public+non-queued prints, owner sees all) + Collections section on profile (cover+visible-count, non-empty only). Reuses `.print-card` grid. Additive (new tables only). 16/16 QA PASS (Cam, build 187e779; create/rename/delete, multi-collection membership, public page, bare-id **301 confirmed on staging**, remove≠delete-print, private-print hidden from visitors) + ownership/cap verified locally + 85/85. On prod (aa680da). Note: create form `name` is `required` (client) + server no-ops empty (a fast-automation empty-submit no-op'd — not a human-reachable bug).
- Filament Buy-link store-search fallback (2026-06-27) — **bug:** Bambu filaments showed no "Buy" link. **Cause:** the link is gated on `filament.source_url`; filaments added manually/via extension (esp. Bambu) have none → no link on every device (NOT a mobile bug — no CSS hides `.chip-buy`). **Fix:** `affiliate.store_search_url(brand,material,color,finish)` maps brand→store search (verified live: Bambu/Polymaker/SUNLU/Anycubic `…/search?q=`, MatterHackers `…/store/c?q=`, FlashForge `…/search?q=`; **Amazon `/s?k=` catch-all** for brands w/ no dedicated store) → `apply_affiliate()` adds the ref. `affiliate.filament_buy_url(...)` = product URL if `source_url` else fallback. Wired into print-detail buy chip (profile.py), `/dashboard/filaments/{id}/buy` redirector (click tracked via `detect_store(target)`), filaments_list (show Buy when `source_url or brand`). Links work bare today, monetize once refs set; Amazon tag applies on prod (set since 2026-06-04), absent on staging (expected — same as Bambu-ref note). 5/5 + edge QA PASS (Cam, build 86d6ffd; Bambu→store search, unknown→Amazon, product URL wins, query formatting). 85/85. On prod (2e2478f).
- User data export + Prints-badge fix (2026-06-27) — closes the trust/GDPR/portability gap (account-delete had no export). Owner-only (session-cookie via `_require_user`): `GET /dashboard/account/export.json` = full dump `{exportedAt, account, printers[], filaments[], prints[]}` (model `to_dict()`; prints embed their `PrintLink`s inline; account block excludes secrets — no api_key/password). `GET /dashboard/account/export.csv` = prints flattened for spreadsheets (resolved printer name + joined material labels, not IDs). Both stream as `attachment; filename=printshelf-export-{username}-{date}.{ext}`. `account_form.html` "Your data" section (id `your-data`) before Danger Zone; `delete_account.html` "export first" link. **Bug fix (surfaced during QA):** sidebar Prints badge counted `queued==False` (10) but the nav link opens the "All" tab (38) → badge now counts all prints (`_ctx`). Additive/read-only, no schema. 6/6 QA PASS (Cam, build 7ff91d7) + zero-prints edge verified locally (empty arrays / header-only CSV) + logged-out→login + 85/85. On prod (405c609).
- Search/Explore facets (2026-06-24) — Explore filterable by **material / filament-brand / printer-brand** over data already stored (no schema). `homepage.py` explore takes `material`/`fbrand`/`printer` params, validated against the option lists (distinct `Filament.material`/`Filament.brand`/`Printer.brand`) so unknown/junk input is ignored. **Printer** facet = clean SQL `join(Printer).filter(brand==…)`. **Material/fbrand** facet (filaments stored as `Print.filament_ids` JSON array, no reverse index, not portably SQL-filterable) = resolve matching `Filament.id` sets → lightweight scan of `(Print.id, filament_ids)` over public prints → `qualifying` IDs → `q.filter(Print.id.in_(qualifying))`; existing sort+pagination run unchanged; scan only when a filament facet is active. Query-string threading centralized in the route: `facet_qs` (sort+facets, for category pills) + `pager_qs` (all active, for pager) via `urlencode`. `explore.html`: 3 auto-submit `<select>`s + "Clear filters" link; `.explore-sort-form` now `flex-wrap`. **Known cap** (documented in code): `IN(...)` on huge lists hits SQLite's variable limit — fine on prod Postgres; a `print_filaments` assoc table is the scale fix. **Follow-up flagged:** brand-name casing dupes (`Bambu`/`BAMBULAB`/`Bambu Labs`) appear as separate facet options — needs a brand-normalization pass (out of scope here). 8/8 QA PASS + 3 edge (empty-state, junk-value, no overflow 390–1024px) + 85/85; facets matched ground-truth queries exactly. On prod (6ab8732).
- PWA / installable (2026-06-24) — printshelf.app is now installable to the home screen (retention for an at-the-printer logging app). `static/manifest.webmanifest` (standalone, `start_url:/dashboard`, `scope:/`, dark theme/bg `#0f1115`). On-brand PIL-generated icons (3 white shelf bars on accent `#ff6a3d`): 192, 512, maskable-512 (extra safe-zone), apple-touch-180. Service worker at **`GET /sw.js`** (root scope so no `Service-Worker-Allowed` header needed): network-first navigations → cached `/offline` fallback, cache-first `/static/*`, versioned cache `printshelf-v1`; `GET /offline` + self-contained `offline.html`. `base.html` head: manifest link + theme-color + apple-mobile-web-app metas + apple-touch-icon + feature-gated SW registration. `main.py` registers `.webmanifest` MIME (`application/manifest+json`) for StaticFiles. **Gotcha:** SW only registers on secure contexts (HTTPS/localhost) — LAN-IP-over-HTTP won't, so runtime SW proof must be on staging/prod HTTPS, not the local LAN-IP Playwright trick. Verified via Playwright on prod HTTPS: SW `activated`, Chromium detects manifest (standalone, 3 icons), theme/apple metas present, offline page served. iPhone install confirmed by Cam. Additive (no schema/DB). 85/85. On prod (bfc2362).
- Time-decayed "Trending" explore sort (2026-06-24) — completes the engagement loop (lifetime likes alone let old prints dominate discovery forever). New explore `sort="trending"` = most likes in the last `TRENDING_WINDOW_DAYS=7`. Portable, no DB-specific date math: Python-computed `cutoff=utcnow()-7d` bind param; recent-likes subquery (count per print where `created_at>=cutoff`), `outerjoin`ed into the explore query, `order_by coalesce(rc,0).desc(), created_at.desc()`. **Degrades to newest** when nothing's been liked recently (rc=0 for all → created_at tiebreak; never empty). `popular` (all-time "Most liked") kept as a separate option; default stays `newest`. `homepage.py` handles trending as a special case (the join) outside `_EXPLORE_SORT`; `_EXPLORE_SORTS` set validates it. Migration `e6f7a8b9c0d1` adds `ix_likes_created_at` (+ matching `Index` in models.py). 6/6 QA PASS + 2 edge (Newest-fallback byte-identical; all-time vs 7-day) + 85/85. On prod (ee06329).
- Feed cold-start fallback (2026-06-24) — new users who follow nobody (or whose followees haven't posted) used to hit an empty feed dead-end. `feed` route in `web_dashboard.py`: when personalized `feed_items` is empty, fall back to a global discovery query (recent public+non-queued prints **with an image**, excluding the viewer's own, newest, limit 50) + `is_discover=True`. `feed.html` header reads "Discover" + a state-accurate note above the cards: `follows_nobody`→"You're not following anyone yet…", else→"The makers you follow haven't posted yet…" (both link to /search); the `feed-empty` 👥 block now only shows on a truly empty site. Read-only/additive (no schema; followed-feed path untouched). 6/6 QA PASS + 2 edge (both note variants) + 85/85. On prod (468eb5f).
- Likes + per-print views + "Most liked" sort (2026-06-24) — the engagement loop on top of follow/queue. `Like` model (unique `user_id`+`print_id` pair, `ix_likes_pair`) + denormalized `Print.like_count` (**recomputed from the likes table on every toggle** → drift-proof even on fast double-clicks) and `Print.view_count`. Routes `POST /@{u}/prints/{id}/like`+`/unlike` mirror `/rate`: session-cookie auth, `X-Requested-With: fetch`→JSON `{liked,count}`, no-JS→303 back, unauth→401/login, **owner can't like own print→403**. `public_print_detail` increments `view_count` for non-owners only (mirrors `profile_views`, skips owner) + computes `liked` for the viewer. Detail page: heart toggle (fetch-enhanced, no reload) for logged-in non-owners / read-only count for owner / login-link for logged-out + 👁 view count (all visible). ♥-count badge on explore+feed+profile cards. Explore `"Most liked"` sort = `like_count desc, created_at desc` (honest all-time; time-decayed "Trending" is a future follow-up — portable SQL date math deferred). Migration `d5e6f7a8b9c0` (additive: `likes` table + 2 counter cols, `server_default='0'`; **no behavior change to existing flows**). 8/8 QA PASS (Cam, build 0f34fba) + 9/9 local like-flow + 85/85. On prod (f82581c).
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
- **2026-06-28 (session 28h)** — Collections (named print groups, many-to-many). 16/16 QA PASS (Cam, build 187e779 @PluggedIn3d): sidebar nav+live count, create→manage, rename/description persist (slug updates), add-to-collections checkboxes (sticky), one print in 2 collections, public collection page + profile section w/ covers, bare-id→slug redirect (curl-confirmed **301** on staging; the browser hid the code + showed a transient 503 = mid-QA deploy restart, since healthy), remove≠delete-print, uncheck removes, delete via confirm modal leaves prints intact, private-print hidden from logged-out visitors. Cap (10) not testable on Cam's Pro account → verified locally (11th→/dashboard/upgrade) + ownership (other user can't view/delete). Minor: fast-automation empty-name submit no-op'd — not human-reachable (`required` + server no-op). 85/85. On prod (aa680da). Cam left staging test data (collections id 1/3, a private Auryn print, filament id 318) to clean up.
- **2026-06-27 (session 28g)** — Filament Buy-link store-search fallback. 5/5 + edge QA PASS (Cam, build 86d6ffd @PluggedIn3d): every filament row now has a Buy link; Bambu filament w/o URL → `us.store.bambulab.com/search?q=PLA+Matte+Black`; public-print chip shows "Buy →"; unknown brand (QA Test Brand) → `amazon.com/s?k=QA+Test+Brand+PETG+Red`; filament w/ saved product URL → exact product page (unchanged); query formatting "PLA Matte Black" correct. **Amazon tag note:** staging links lacked `?tag=` because `AMAZON_AFFILIATE_TAG` isn't set on staging (proven env-wide — the existing Hatchbox *product* link also lacked it); code applies the tag when the var is set (verified locally) and prod has had it since 2026-06-04. Prod confirmed: banana-sword print renders chip-buy for its Bambu filaments. 85/85. On prod (2e2478f).
- **2026-06-27 (session 28f)** — User data export (JSON + CSV) + Prints-badge fix. 6/6 functional QA PASS (Cam, build 7ff91d7 @PluggedIn3d): "Your data" section renders, JSON export has account/printers/filaments/prints with full fields + **no secrets** (verified no api_key/password), CSV is one-row-per-print with human-readable printer/filament names (no IDs), delete page shows "export first" link, logged-out → login redirect (no anonymous data leak). Zero-prints edge verified by me locally (empty arrays / header-only CSV). Cam's QA surfaced a real pre-existing bug — sidebar Prints badge showed 10 (printed-only) next to a 38-row "All" list → fixed to count all prints; Cam confirmed badge now reads 38 on staging. 85/85. On prod (405c609).
- **2026-06-24 (session 28e)** — Search/Explore facets (material/filament-brand/printer-brand). 8/8 functional QA PASS (Cam, build ffcb616 @PluggedIn3d): all 3 dropdowns render, each facet filters, facets compose with each other + category + sort, "Clear filters" keeps category/sort, facets persist across sort changes + pills + pager. Edge PASS: no-match→clean empty state, junk `?material=Adamantium`→ignored, mobile stacking. Two QA-flagged observability caveats both closed by me: (1) dead-zone overflow — verified `doc_overflow_px=0` at every width 390–1024 (flex-wrap, not the @media rule, does it; 540px screenshot confirms 2-row wrap); (2) filtered pagination — no >24-result facet on staging seed to render "Older →", but page=2 of a filtered URL returns 200 w/ facets preserved + ground-truth logic verified. Real follow-up noted: brand-name casing dupes in facet options (needs normalization, out of scope). 85/85. On prod (6ab8732).
- **2026-06-24 (session 28d)** — PWA / installable. Browser-level QA PASS (build 91e4d84): manifest well-formed (PrintShelf, standalone, start_url /dashboard, dark theme), icons 192/512/maskable all 200 image/png rendering the orange shelf mark (maskable bars inside safe zone), SW registered scope / state "activated", iOS apple-mobile-web-app metas + apple-touch-icon present, branded `/offline` page renders (📡 "You're offline"). Native install/launch/airplane-mode steps verified by Cam on **iPhone** ("looks good"). Playwright installability proof run on both staging AND prod HTTPS (SW activated, manifest detected w/ 3 icons + correct MIME, offline navigation served). 85/85. On prod (bfc2362).
- **2026-06-24 (session 28c)** — Time-decayed "Trending" explore sort. 6/6 manual QA PASS (Cam, build 2c3f746 @PluggedIn3d): Trending option in dropdown, liking pushes prints to top of Trending (liked 132+120 → top 3 alongside pre-liked 128), unliking drops them back to their Newest positions, sorts+category pills+pagination all carry `&sort=trending` cleanly. Edge PASS: with no recent likes Trending order is **byte-identical** to Newest (graceful fallback); all-time "Most liked" vs 7-day "Trending" coincide on staging only because all likes are <7d old (full decay verified locally with 30-day-old seeded like → dropped to pos 8 while fresh like ranked #1). 85/85. On prod (ee06329).
- **2026-06-24 (session 28b)** — Feed cold-start fallback. 6/6 manual QA PASS (Cam, build d81622e @PluggedIn3d 0-following): Discover header + note + cards on cold start, own prints excluded (32 cards, 0 own), all cards have images, "Find makers" → /search, following a maker flips to "Feed" w/ no note, unfollow returns to Discover. Cam flagged 1 copy bug (note said "not following anyone" in the follows-but-empty state) → fixed via `follows_nobody` flag + distinct copy, re-QA PASS on build 49cbdad (both variants render accurately). 85/85 throughout. On prod (468eb5f).
- **2026-06-24 (session 28)** — Likes + per-print views + "Most liked" explore sort (engagement loop). 8/8 manual QA PASS (Cam, build 0f34fba @PluggedIn3d as non-owner) covering all 3 like states (button/read-only/login-link), non-owner view increment + owner suppression, liked-state persistence on reload, popular sort ordering, ♥ badge on explore/feed/profile cards. Edge cases PASS: logged-out heart→login link (no error), fast double-click nets to correct count (drift-proof recompute), self-like silently refused. 9/9 local like-flow (like/unlike/idempotency/own-403/unauth-401/no-JS-303) + 85/85 automated. On prod (f82581c).
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
**Completed 2026-06-24 (session 28):**
- Likes + per-print views + "Most liked" explore sort — engagement loop atop follow/queue. `Like` model + drift-proof `like_count` (recomputed on toggle) + `view_count`; `/like`+`/unlike` routes mirror `/rate`; detail-page heart toggle (3 states) + 👁 views; ♥ badge on explore/feed/profile cards; migration `d5e6f7a8b9c0` (additive). 8/8 QA + 9/9 local + 85/85 PASS. On prod (f82581c).
- Feed cold-start fallback — empty personalized feed now falls back to community Discovery (recent public prints w/ image, own excluded); state-accurate note (follows-nobody vs follows-but-empty). 6/6 + 2 edge QA PASS. On prod (468eb5f).
- Time-decayed "Trending" explore sort — `sort=trending` ranks by likes in the last 7 days (portable recent-likes subquery); degrades to newest when no recent engagement. "Most liked" (all-time) kept separate. Migration `e6f7a8b9c0d1` (index). 6/6 + 2 edge QA PASS. On prod (ee06329).
- PWA / installable — home-screen install (manifest + shelf icons + service worker w/ offline fallback). SW at `/sw.js` (root scope); `/offline` page; `.webmanifest` MIME registered. iPhone install confirmed by Cam; Playwright proof on prod HTTPS. 85/85. On prod (bfc2362).
- Search/Explore facets — Explore filterable by material / filament-brand / printer-brand (validated query params; printer = SQL join, material/fbrand = filament-ID scan over JSON `filament_ids`). Auto-submit dropdowns + Clear-filters; facets persist across sort/category/pager. 8/8 + 3 edge QA. On prod (6ab8732).
- User data export (JSON + CSV) + Prints-badge fix — owner-only export of full account data (no secrets) + spreadsheet CSV; badge now counts all prints (was printed-only). 6/6 QA + zero-prints edge + 85/85. On prod (405c609).
- Filament Buy-link store-search fallback — filaments without a product URL (esp. Bambu) now get a Buy link to the brand store search (Amazon catch-all); was: no link at all. `affiliate.store_search_url`/`filament_buy_url`. 5/5 + edge QA. On prod (2e2478f).
- Collections — user-named groups of prints (many-to-many): dashboard CRUD, add-from-print checkboxes, public collection pages + profile section, free-tier cap 10. Migration `f7a8b9c0d1e2`. 16/16 QA. On prod (aa680da).

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

**Immediate next step:** Set CF proxy env vars on Railway prod; **set affiliate refs on prod to monetize the new Buy-link fallback** — `BAMBU_AFFILIATE_REF`, `POLYMAKER_AFFILIATE_REF`, `MATTERHACKERS_AFFILIATE_REF` (Bambu/Polymaker store-search + product links currently link but earn nothing until set); confirm `AMAZON_AFFILIATE_TAG` is still set on prod (it powers the Amazon catch-all). Then next feature — Cam's call. Remaining candidates (engagement loop + cold-start + PWA + facets + data-export + Collections now DONE): OAuth/Google social login (signup-funnel friction — needs Cam to provision Google OAuth creds first); **brand-name normalization** (facet options + filament data show casing dupes like `Bambu`/`BAMBULAB`/`Bambu Labs`, `Hatchbox`/`HATCHBOX` — surfaced by the facets feature); explore facets scale fix (`print_filaments` assoc table to replace the in-memory JSON-array scan).
