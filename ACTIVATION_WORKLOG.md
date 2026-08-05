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
| 6 | **Silent referrer/UTM capture** on signup (no user-facing form) | ⬜ awaiting go | — | Cam declined a "how'd you hear" FORM; this is invisible capture. Adds source column to users, stores Referer + utm_*. Makes every future signup attributable. |
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
