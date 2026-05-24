# PrintShelf Chrome Extension — Manual QA Checklist

> **Scope:** v0.2.0 — Makerworld + Printables + Cults3D + Thingiverse.
> Sections 0–12 are the full Makerworld pass. Section 14 is a quick
> smoke test for the other three platforms.
>
> Plan on ~10–15 minutes. Run against **staging** (`staging.printshelf.app`)
> unless explicitly testing local dev.

---

## 0 · Setup (one time)

- [ ] Chrome → `chrome://extensions` → toggle **Developer mode** on (top right).
- [ ] Click **Load unpacked** → pick `chrome-extension/` in this repo.
- [ ] Confirm the orange "P" icon appears in the toolbar (pin it for convenience).
- [ ] Pick a test environment up front and stay on it for the whole run:
  - **Staging (recommended):** `https://staging.printshelf.app`
  - **Local:** `python -m uvicorn main:app --host 127.0.0.1 --port 8765` from `backend/`
- [ ] Sign in to that environment in a normal browser tab and confirm at least
      **one printer + one filament** exist on the account (so prints save cleanly).

---

## 1 · Popup — empty state

- [ ] Click the toolbar icon → popup opens (~320px wide, dark theme).
- [ ] Status pill in the header reads **"No key"** (gray).
- [ ] Input placeholder reads **"Paste your PrintShelf API key"**.
- [ ] The "Find it in your dashboard settings" link is present.
- [ ] Click **Save** with empty input → red feedback box: **"Paste a key first."** Input gets focus.
- [ ] Click **Test** with no key saved → red feedback: **"Save a key first."**

## 2 · Popup — dashboard deep-link (the fix)

- [ ] Click the **dashboard settings** link in the popup → opens a new tab at
      `/dashboard#api-key` on whichever base URL is configured.
- [ ] The "Chrome extension API key" `<details>` section is **already expanded**,
      key visible, page scrolled to it.

## 3 · Options page — base URL switcher

- [ ] In the popup, click **More…** → options page opens.
- [ ] Preset selector defaults to whichever base is saved (Production on first run).
- [ ] Choose **Staging** from the dropdown → input fills to `https://staging.printshelf.app`,
      becomes disabled.
- [ ] Choose **Custom…** → input becomes editable, focused.
- [ ] Choose **Local dev** → input fills to `http://127.0.0.1:8765`.
- [ ] Click **Save** → green box: **"Saved API base."**
- [ ] Reload options page → preset selector remembers your last choice.

## 4 · Popup — save flow (the other fix)

Copy your API key from `/dashboard#api-key` first.

- [ ] Paste the key, click **Save**:
  - Save button briefly turns **green with "✓ Saved"**, then reverts.
  - Status pill: **"No key"** → **"Saving…"** → **"Connected"**.
  - Feedback shows a green box: **"✓ Connected as <your-username>."**
  - Input clears; placeholder now reads **"(saved — paste again to replace)"**.
- [ ] Close and re-open the popup → pill is **"Key saved"** (green), placeholder
      still reads "(saved — paste again to replace)". No key text in the field.

## 5 · Popup — bad key

- [ ] Paste a garbage string (e.g. `not-a-real-key-1234`) → **Save**.
- [ ] Feedback: red box **"Key rejected. Re-copy it from your dashboard."**
- [ ] Pill reads **"Invalid"** in red.
- [ ] Re-paste the real key → **Save** → green again.

## 6 · Options page — Test connection

- [ ] Open options page → click **Test connection** → green: **"Connected as <user> (free)."**
- [ ] Edit the API key input with garbage → **Test** (don't Save first) → red rejection.
- [ ] Clear the input → **Test** → still works against the previously saved key
      (so a stray edit doesn't break test).

---

## 7 · Makerworld FAB — appearance

- [ ] Visit a Makerworld model page, e.g.
      `https://makerworld.com/en/models/<any-id>-<any-slug>`.
- [ ] Within ~1–2 seconds the orange **"+ Add to PrintShelf"** FAB appears
      bottom-right. It should sit above any Makerworld floating UI.
- [ ] Visit the Makerworld **home page** (`https://makerworld.com/en`) →
      FAB does **not** appear.
- [ ] Visit a Makerworld search/category page (anything not under `/models/`) →
      FAB does **not** appear.
- [ ] Visit a model page in a non-English locale, e.g.
      `https://makerworld.com/ja/models/...` → FAB **does** appear.

## 8 · Makerworld FAB — happy path

- [ ] On a model page, click the FAB.
- [ ] Button flashes through: **"+ Add to PrintShelf"** → **"Saving…"** (disabled) →
      **"Saved to queue ✓"** (green) → reverts after ~3.5 s.
- [ ] Toast appears above the button: **"Saved '<title>' to your queue."**
- [ ] Extension toolbar badge briefly shows **"✓"** on a green background.
- [ ] In another tab, go to `/dashboard/prints?queued=true` (or whichever filter
      shows the queue) and confirm the new print appears with:
  - [ ] **Title** — matches the model's actual title (not "Makerworld" or a generic blurb).
  - [ ] **Designer** — matches the author shown on the Makerworld page.
  - [ ] **Source URL** — the canonical model URL (no `utm_*` params).
  - [ ] **Thumbnail** — the model preview image (not a default/icon).
  - [ ] **Source platform** — `makerworld`.
  - [ ] **Queued** — yes; **Status** — printed (the queue convention).

## 9 · Makerworld FAB — SPA navigation

- [ ] On a model page, click another model card from the sidebar / "you may also like"
      list so the URL changes without a full reload.
- [ ] FAB stays visible. Click it on the new page → the saved print reflects the
      **new** model's title/designer/thumbnail (not the previous page).
- [ ] Click a Makerworld nav link to a non-model page (e.g. "Models" index).
      FAB disappears.
- [ ] Browser **Back** to the model page → FAB reappears.

## 10 · Makerworld FAB — auth + error paths

- [ ] In the popup, clear the saved key:
      DevTools console (on the popup) → `chrome.storage.sync.remove('apiKey')`,
      or just paste garbage and save.
      *(Or: open the extension's service worker DevTools and run the same.)*
- [ ] Reload a Makerworld model page → click the FAB.
- [ ] Button shows **"Try again"** in red; toast says
      **"Set your PrintShelf API key in the extension popup. Open settings"** (with link).
- [ ] Click **Open settings** in the toast → options page opens in a new tab.
- [ ] Re-paste a valid key in the popup → click FAB again → succeeds.

## 11 · Makerworld FAB — free-tier cap (optional)

> Skip if your test account isn't near the 50-print cap.

- [ ] Get the account to 50 prints (or temporarily lower `FREE_TIER_PRINT_LIMIT`
      in `models.py` to e.g. 2 against local dev).
- [ ] Click FAB → toast surfaces the cap-hit detail from the API
      (something like "Free tier limit (50 prints) reached. Upgrade to Pro.").
- [ ] Button shows **"Try again"** in red, not a generic "Save failed".

---

## 12 · Service worker / lifecycle

- [ ] `chrome://extensions` → click **service worker** under the PrintShelf
      extension. DevTools should attach, no errors in the console.
- [ ] In `chrome://extensions`, click **Reload** on the PrintShelf card → tabs
      with a Makerworld model page still have a working FAB after a
      page reload.

## 14 · Other platforms — smoke test

Goal: confirm the FAB appears, extracts a sensible title/designer/thumbnail,
and saves successfully on each platform. ~2 minutes each.

For each platform below:

- [ ] Open any model page on the platform.
- [ ] FAB appears bottom-right within ~1–2 s.
- [ ] Click FAB → green "Saved to queue ✓" → toast with "View in PrintShelf →".
- [ ] Click the link → on the edit page, confirm title/designer/thumbnail/source URL
      are correct and **source platform = the right one** (printables / cults3d / thingiverse).

Platforms:

- [ ] **Printables** — e.g. `https://www.printables.com/model/<id>-<slug>`.
- [ ] **Cults3D** — e.g. `https://cults3d.com/en/3d-model/<category>/<slug>`.
- [ ] **Thingiverse** — e.g. `https://www.thingiverse.com/thing:<id>`.

If a designer comes back blank for any platform, that platform's
`designerSelectors` array in `content/inject.js` needs a tweak — the
JSON-LD `author` and `<meta>` fallbacks usually catch it, but author-link
DOM patterns drift.

---

## 13 · Cleanup

- [ ] Restore `FREE_TIER_PRINT_LIMIT` if you changed it.
- [ ] Delete the test prints if you don't want them on `/u/<you>`.
- [ ] If you tested against staging, run the backend QA once before merging:
      `python backend/scripts/qa.py --base https://staging.printshelf.app`.

---

## Reporting issues

For any failed step, capture:
- The step number above.
- A screenshot of the popup/page + the toast/feedback message verbatim.
- The DevTools console output from the **service worker** (`chrome://extensions`
  → service worker link) — that's where background-side errors land.
- The DevTools console output from the **Makerworld page** — that's where
  content-script errors land.
