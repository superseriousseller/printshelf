# Chrome Web Store Submission Notes

Paste-ready copy for the Chrome Web Store developer dashboard so you don't
have to draft this under pressure once the upload form is in front of you.

---

## Listing fields

### Short description (132 chars max)
> Add 3D models from Printables, Makerworld, Cults3D, Thingiverse — and Polymaker filaments — to your PrintShelf library.

### Detailed description
> PrintShelf is a tracker for makers who 3D print. This extension adds a
> one-click "Add to PrintShelf" button on supported pages so you don't have
> to copy-paste URLs into your library.
>
> Supported sites:
>  - Model platforms: Printables, Makerworld, Cults3D, Thingiverse
>  - Filament retailers: Polymaker (more coming)
>
> What you get:
>  - One click adds a model to your print queue with title, designer, and thumbnail pre-filled
>  - On Polymaker product pages, one click adds the filament to your wishlist with brand, material, color name, hex, and price pulled from the page
>  - Your selected color variant is captured from the live page — not just the default variant
>
> Requires a free PrintShelf account at https://printshelf.app — paste your
> API key into the extension popup once and you're done. Your key is stored
> locally and only used to authenticate requests to printshelf.app.

### Category
Productivity

### Language
English (US)

---

## Permission justifications

The Web Store form asks for a one-sentence rationale for each permission
block. Paste these verbatim.

### `storage`
> Stores the user's PrintShelf API key and the API base URL (production /
> staging / local dev) in `chrome.storage.sync` so they only have to paste
> their key once per browser profile.

### Host permissions for `https://printshelf.app/*`, `https://staging.printshelf.app/*`, `http://127.0.0.1:8765/*`, `http://localhost:8765/*`
> The extension sends authenticated POST requests to PrintShelf's own API to
> save prints and filaments. Localhost and staging entries are needed so
> developers and beta testers can point the extension at a non-production
> backend during testing.

### Host permissions for `https://makerworld.com/*`, `https://www.makerworld.com/*`, `https://printables.com/*`, `https://www.printables.com/*`, `https://cults3d.com/*`, `https://www.cults3d.com/*`, `https://thingiverse.com/*`, `https://www.thingiverse.com/*`
> A content script injects an "Add to PrintShelf" button on model-detail
> pages of each platform and reads the page's Open Graph and JSON-LD tags
> (title, designer, thumbnail URL) when the user clicks the button. No data
> is read or transmitted until the user explicitly clicks the button.

### Host permissions for `https://us.polymaker.com/*`, `https://polymaker.com/*`, `https://shop.polymaker.com/*`
> A content script injects an "Add filament to PrintShelf" button on
> Polymaker product pages and reads the currently-selected color variant's
> name and hex code from the DOM when the user clicks the button. This data
> is needed because Polymaker's product page serves the *default* variant in
> its server-rendered metadata; the actual color the user picked only exists
> in the live DOM.

---

## "What's new" copy (for updates after the initial publish)

For v0.3.5 (assumes this is the first submission):

> First public release. Adds an "Add to PrintShelf" button on model pages
> (Printables, Makerworld, Cults3D, Thingiverse) and a separate filament-add
> button on Polymaker product pages.

---

## Required assets

| Asset | Spec | Status |
|-------|------|--------|
| Icon 128×128 | PNG | already in `icons/icon128.png` |
| Screenshot 1 | 1280×800 PNG/JPG | **NEEDED** — FAB on a real Printables/Makerworld model page |
| Screenshot 2 | 1280×800 PNG/JPG | **NEEDED** — FAB on a real Polymaker product page with a non-default color selected |
| Promotional tile small | 440×280 | optional, can skip for v1 |

Capture both screenshots from the same Chrome profile in a clean window
(close devtools, hide bookmarks bar). The FAB should be clearly visible in
the bottom-right.

---

## Privacy policy URL
https://printshelf.app/privacy

---

## Single-purpose declaration
> PrintShelf's single purpose is to let users add 3D model pages and
> filament product pages to their PrintShelf library with one click,
> capturing metadata from the current page so they don't have to copy-paste.

---

## Pre-submission checklist

- [ ] Manifest version bumped (currently 0.3.5)
- [ ] Privacy policy live at https://printshelf.app/privacy (returns 200)
- [ ] Popup + options pages display the actual version (not "v0.1.0")
- [ ] Two 1280×800 screenshots captured
- [ ] Zipped `chrome-extension/` directory (exclude `.git`, `node_modules`, `QA.md`, `PUBLISH.md`)
- [ ] Logged into Chrome Web Store developer console with the right account
- [ ] Have read the [single-purpose policy](https://developer.chrome.com/docs/webstore/program-policies/single-purpose) once
