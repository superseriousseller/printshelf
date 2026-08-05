# PrintShelf — Activation & Growth Work Log (Aug 2026)

Maintained by Tess. Started from a thumbnail fix + activation build, then branched into
email-quota, email-verification, and traffic-source work. This is the single source of truth
so nothing gets lost and nothing ships to prod unverified.

**Status legend:** ✅ done & verified · 🔷 built + QA'd, STAGED (not on prod) · ⏳ in progress · ⬜ approved, not built · 💤 idea/awaiting decision

**Deploy model (confirmed 2026-08-04):** prod deploys from **`main`**; the `staging` branch feeds the
`printshelf-staging` Railway service. All work below is committed on **`staging`** and is NOT on prod
until `staging` → `main` is merged + pushed (Railway auto-redeploys prod). **No prod deploy without Cam's explicit OK.**

---

## Work items

| # | Item | Status | Commit | Notes |
|---|------|--------|--------|-------|
| 1 | **Thumbnail backfill** — resolve missing MakerWorld/og covers | ✅ DONE on PROD | `cdc7490` (pushed to staging) | Ran against prod DB. Verified via live API: **239/242** have thumbnails (was 58). 3 left need user-uploaded photos. |
| 2 | **Activation build** — first-print CTA + honest checklist completion | ✅ DONE on PROD (2026-08-05) | `8a0bc96` | Browser QA **35/35** (23 core + 6 bonus + 6 regression), 0 console/server errors. Merged staging→main + pushed; Railway redeployed; prod smoke test passed (health ok, public surfaces 200, /u→/@ 404 shelf ok). Independently re-smoked live on prod same day: fresh real-browser run, **18/18 PASS** (real MakerWorld thumbnail rendered, `naturalWidth=991`, 0 console/server errors), test account fully deleted after. |
| 3 | **MakerWorld copy fix** — stale "must be entered manually" | ✅ DONE on PROD (2026-08-05) | `edadcce` | Placeholder + hint corrected. Shipped in same merge as #2. |
| 4 | **Resend email quota** — hit ~80% of daily free tier | ✅ RESOLVED (2026-08-05) | — | Cam upgraded Resend to **1,000 emails/day** (was free tier). Next tier = 5k/day if needed. Headroom restored. |
| 5 | **Email reorder** — verify-at-signup; welcome fires on verify success (not both at signup) | ✅ DONE on PROD (2026-08-05) | `052c132` | `send_welcome` moved out of `signup_submit` into `verify_email`'s success branch (gated by the existing `used_at` replay check, so it can't double-fire). Google OAuth signups unaffected — they verify inline and already send welcome separately in the callback. **QA'd on `staging.printshelf.app` against real Resend send logs (not just code reading)**: real-browser signup → Resend API confirmed **exactly 1 email** (verification only, no welcome); browser-clicked the real verify link → welcome email then present exactly once, verification still exactly once (no duplicates). 10/10 checks passed. Cam approved prod deploy 2026-08-05; merged staging→main + pushed. |
| 6 | **Silent referrer/UTM capture** on signup (no user-facing form) | 🔷 BUILT + QA'D, STAGED (2026-08-05) | `3bf93fc`, `43a1b65`, `3b460eb` | 8 nullable columns on `users` (`signup_referrer`, `signup_landing_path`, `signup_landing_querystring`, `utm_source/medium/campaign/content/term`), migration `f9708986d682` (down_revision `f5a6b7c8d9e0`, applied to staging DB). New `attribution.py`: HTTP middleware captures Referer + UTM + landing path into a short-lived HttpOnly cookie on a visitor's first real page GET (skips `/static`, `/api`, `/admin`, technical paths), **first-touch-wins** (never overwritten by later pages). Read back in both `create_user()` (password signup) and `_find_or_create_google_user`'s new-account branch (Google OAuth) — both signup paths covered; account-linking paths untouched. Missing/malformed cookie → all fields `None`, no crash. **Zero UX change: no new form fields, nothing rendered** — verified, not assumed. **QA'd real-browser, local server on `staging` branch + staging DB**: (1) landed with a real Referer (`reddit.com/r/3Dprinting`) + full UTM set on `/` → browsed to an unrelated page first → verified the capture cookie was **not** overwritten → signed up from `/signup` → re-queried the DB → every field (referrer, all 5 UTM params, landing_path=`/`, querystring) matched exactly. (2) Direct signup with no referrer/UTM straight to `/signup` → row created fine, all attribution fields `NULL`, `signup_landing_path`=`/signup`, no crash. (3) Signup form's visible fields confirmed byte-identical to before (`email`, `username`, `display_name`, `password`, `password_confirm` — nothing added). 18/18 real checks passed (1 test-script selector bug along the way — an overly broad CSS selector also matched the topbar's pre-existing search box — not a product issue, confirmed and corrected). Full 85-check suite re-run: 83/85, same 2 pre-existing external failures as before this work (Printables.com transiently 403ing our scraper UA — confirmed via direct curl, unrelated to any of these changes). All test accounts deleted from staging DB after, verified 0 residue. **Staged only — not merged to main, not on prod.** |
| 7 | **Traffic-source investigation** (this wave) | ⏳ open | — | See findings below. Source still unknown; needs CF dashboard OR item #6. |

## Known flags / watch

- ⚠️ **0 of 84 spike signups have logged a print.** Steady round-the-clock, all-password signups. Could be a low-intent placement (freebie/tool-directory) rather than a quality community. Confirm source before treating 176 users as a pure win.
- ⚠️ **No Cloudflare Analytics API token** exists (only a CF Worker proxy secret + R2). CF referrer data only exists if printshelf.app is **proxied** (orange-cloud), not just DNS→Railway. Verify CF DNS mode before relying on the dashboard.
- ℹ️ **QA test accounts not fully cleaned from staging DB** (~59 `@printshelf.app` rows). Harmless, but the QA agent claimed cleanup.
- ℹ️ `backend/.env` `DATABASE_URL` points to **staging**, not prod. Prod DB = Railway `Postgres` service `DATABASE_PUBLIC_URL` (mainline.proxy.rlwy.net).

## Traffic findings (real prod data, pulled 2026-08-04 via Railway prod DB)

- **176 total users.** Signups/day: 7/29 →1, 7/30 →2, **8/2 →13, 8/3 →35, 8/4 →36 (partial, still climbing).**
- Signup times spread evenly across all 24h → **evergreen/steady source, not a video/viral spike.**
- Emails real + diverse: gmail 20, hotmail 5, yahoo 4, outlook 3, aol/live, + corporate incl. **4× erco.com**. 84 password / 3 Google.
- **Activation of this wave: 0 / 84.**

## Deploy checklist (run before ANY of #2/#3/#5/#6 hit prod)

- [ ] Cam explicitly approves prod deploy
- [ ] Merge `staging` → `main`, push (Railway auto-redeploys prod)
- [ ] Post-deploy smoke test on live printshelf.app: new-signup zero-state renders (CTA + checklist); existing account dashboard loads normally; no console/server errors
- [ ] Confirm Resend upgrade is live before/with the email-reorder deploy (#5)
- [ ] If #6 shipped: verify a real signup writes a source value; re-query prod DB to confirm

---
_Update this file as items move. Relay sessions working in this repo should read + update it too._
