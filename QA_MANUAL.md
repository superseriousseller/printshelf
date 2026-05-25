# PrintShelf Manual QA Script

Target: https://staging.printshelf.app  
Run this top to bottom in a fresh private/incognito window.

---

## 1. Public surfaces (no login)

- [ ] `GET /` — homepage loads, hero headline visible, "Sign up" link present
- [ ] `GET /static/app.css` — returns 200, dark theme applies
- [ ] `GET /u/doesnotexist` — renders the custom 404 shelf page (not a generic error)
- [ ] `GET /api/health` — returns `{"status":"ok"}`

---

## 2. Signup

- [ ] `GET /signup` — form renders
- [ ] Submit with mismatched passwords → stays on `/signup`, error shown in form
- [ ] Submit with valid unique email + matching passwords → redirects to `/dashboard`, session cookie set
- [ ] Try signing up again with the same email → error (duplicate)

---

## 3. Login / logout

- [ ] Log out (footer/nav logout button) → redirects to `/`
- [ ] `GET /dashboard` while logged out → redirects to `/login`
- [ ] `GET /login` — form renders
- [ ] Submit wrong password → error shown
- [ ] Submit correct credentials → redirects to `/dashboard`, greeted by username

---

## 4. Printers

- [ ] `GET /dashboard/printers` — loads, "Add printer" button present
- [ ] Add a printer (name: "Bambu P1S") → 303 redirect, printer appears in list
- [ ] Printer appears in the Printer dropdown on the print form

---

## 5. Filaments

- [ ] `GET /dashboard/filaments` — loads, "Add filament" button present
- [ ] Add a filament (brand: "Bambu", material: "PLA", color: "Fire Engine Red", hex: `#CC0000`) → appears in list with red swatch
- [ ] Verify color swatch renders next to the filament name in the list

---

## 6. Prints — basic create

- [ ] `GET /dashboard/prints` — loads, "+ Log print" and "+ Queue print" buttons present
- [ ] Add a print manually:
  - Title: "Benchy"
  - Designer: "3DBenchy"
  - Status: printed
  - Assign the printer and filament from above
  - Rating: ★★★★
  - Notes: "perfect first layer"
  - Mark public
  - → 303 redirect, print appears in list

---

## 7. Prints — URL import (Printables)

- [ ] Click "Add print", paste a Printables URL into the "Import from a model URL" field, click "Pre-fill form"
- [ ] Title, designer, thumbnail URL, source platform auto-filled
- [ ] Submit → print saved with imported metadata
- [ ] Add the same URL a second time → import hits the cache (server-side, instant)

---

## 8. Prints — URL import (Makerworld)

- [ ] Paste a Makerworld URL that has a slug (e.g. `https://makerworld.com/en/models/12345-my-cool-model`)
- [ ] Title is extracted from the slug (partial result), notice banner shown
- [ ] Paste a bare Makerworld ID URL (no slug) → 400 error, message says to paste the full URL manually

---

## 9. Prints — queued flow

- [ ] Click "+ Queue print" (or "+ Log print" → set Status to "queued") 
- [ ] Submit with title "Cable Clip" → redirects to queued list (`/dashboard/prints?queued=true`)
- [ ] Print appears in queue with a "Mark as printed" button
- [ ] **Edit the queued print:**
  - Open edit form → Status dropdown shows **queued** selected
  - Change notes, leave Status as "queued", save → print still in queue ✓
- [ ] **Dequeue via dropdown:**
  - Edit again → change Status to **printed** → save
  - Print no longer in queue, appears in main prints list ✓
- [ ] **Mark as printed button:**
  - Add another queued print ("ENDER DRAGON")
  - From the queue list, click "Mark as printed"
  - Print leaves queue, print_date set to today ✓

---

## 10. Prints — edit (non-queued)

- [ ] Edit the "Benchy" print → change rating to ★★★★★, save → change persists
- [ ] Edit → remove the printer assignment → save → printer shows as "none"
- [ ] Status dropdown on a non-queued print shows printed/failed/partial (not queued pre-selected)

---

## 11. Photo upload

- [ ] Edit a print → upload a JPEG photo from your computer → save
- [ ] Photo appears on the print card in the dashboard list
- [ ] **Verify R2:** right-click the photo → "Copy image address" — URL should start with `https://cdn.printshelf.app/` (not `/uploads/` or `localhost`)
- [ ] Upload a non-image file (e.g. a `.txt`) → 400 error shown
- [ ] Upload a second photo on the same print → replaces the first

---

## 12. Public profile

- [ ] `GET /u/<your-username>` — renders your public print wall
- [ ] Prints marked public appear; prints marked private do not
- [ ] Toggle a print from public → private → re-check profile; it's gone
- [ ] Profile page has `og:title` and `og:description` meta tags (view source)
- [ ] Material filter (e.g. "PLA") narrows results
- [ ] Status filter (e.g. "printed") narrows results

---

## 13. Homepage gallery

- [ ] `GET /` — featured prints section shows at least one public print card
- [ ] Clicking a print card goes to the correct public profile

---

## 14. Free-tier cap

- [ ] Add filaments until you hit the 11th → response is 402 with an `upgrade_required` error (check in browser or network tab)
- [ ] Error message references the filament limit

---

## 15. API key auth (sanity check)

- [ ] `GET /dashboard` or Profile → find your API key in account settings (if exposed in UI) or via `GET /api/auth/me` with JWT
- [ ] `curl -H "Authorization: Bearer <apiKey>" https://staging.printshelf.app/api/auth/me` → returns your user object

---

## Pass criteria

All 15 sections green. Pay special attention to:
- Section 9 (queued ↔ printed transitions) — freshly fixed
- Section 11 R2 URL check — confirms R2 is wired, not local fallback
