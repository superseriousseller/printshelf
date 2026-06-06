# Chrome Web Store Submission Notes

Paste-ready copy for the Chrome Web Store developer dashboard.

---

## Listing fields

### Short description (132 chars max)
> Save 3D models and filaments to PrintShelf from Printables, Makerworld, Cults3D, Thingiverse, Amazon, Bambu Lab, and more.

### Detailed description
> PrintShelf is a tracker for makers who 3D print. This extension adds a
> one-click button on model and filament pages so you can save items to your
> PrintShelf library without copy-pasting anything.
>
> On model pages (Printables, Makerworld, Cults3D, Thingiverse), one click
> saves the model to your print queue with title, designer, and thumbnail
> pre-filled.
>
> On filament retailer pages, one click saves the filament to your library
> with brand, material, color name, hex code, price, and finish (Silk, Matte,
> Glow, etc.) pulled automatically from the page. The color variant you have
> selected is captured from the live page — not just the default shown in
> metadata.
>
> Requires a free PrintShelf account at https://printshelf.app — paste your
> API key into the extension popup once and you're done. Your key is stored
> locally and only used to authenticate requests to printshelf.app.

### Category
Productivity

### Language
English (US)

---

## "What's new" copy (for this update)

> v0.3.8: Added SUNLU and FlashForge filament store support. Finish type
> (Silk, Matte, High Speed, Glow, etc.) is now auto-extracted from product
> titles across all filament stores. Previous updates added Bambu Lab,
> Anycubic, MatterHackers, and Amazon.

---

## Permission justifications

### `storage`
> Stores the user's PrintShelf API key and the API base URL (production /
> staging / local dev) in `chrome.storage.sync` so they only have to paste
> their key once per browser profile.

### Host permissions for `https://printshelf.app/*`, `https://staging.printshelf.app/*`, `http://127.0.0.1:8765/*`, `http://localhost:8765/*`
> The extension sends authenticated POST requests to PrintShelf's own API to
> save prints and filaments. Localhost and staging entries are needed so
> developers and beta testers can point the extension at a non-production
> backend during testing.

### Host permissions for model platforms (Printables, Makerworld, Cults3D, Thingiverse)
> A content script injects an "Add to PrintShelf" button on model-detail
> pages and reads the page's Open Graph and JSON-LD tags (title, designer,
> thumbnail URL) when the user clicks the button. No data is read or
> transmitted until the user explicitly clicks the button.

### Host permissions for filament retailers (Amazon, Bambu Lab, Polymaker, Anycubic, MatterHackers, SUNLU, FlashForge)
> A content script injects an "Add filament to PrintShelf" button on product
> pages and reads the currently-selected color variant's name, hex code,
> material, price, and finish from the DOM when the user clicks the button.
> The live DOM is required because server-rendered metadata only reflects the
> default variant — not the one the user has selected. No data is read or
> transmitted until the user explicitly clicks the button.

---

## Required assets

| Asset | Spec | Status |
|-------|------|--------|
| Icon 128×128 | PNG | `icons/icon128.png` |
| Screenshot 1 | 1280×800 PNG/JPG | model page (Printables or Makerworld) with FAB visible |
| Screenshot 2 | 1280×800 PNG/JPG | filament page (Amazon or Bambu Lab) with button visible |
| Promotional tile small | 440×280 | optional |

---

## Privacy policy URL
https://printshelf.app/privacy

---

## Single-purpose declaration
> PrintShelf's single purpose is to let users save 3D model pages and
> filament product pages to their PrintShelf library with one click,
> capturing metadata from the current page so they don't have to copy-paste.

---

## Pre-submission checklist

- [ ] Manifest version is 0.3.8
- [ ] Privacy policy live at https://printshelf.app/privacy (returns 200)
- [ ] Popup displays correct version (0.3.8)
- [ ] Two 1280×800 screenshots captured (clean Chrome window, devtools closed)
- [ ] Zipped `chrome-extension/` directory (exclude `QA.md`, `PUBLISH.md`)
- [ ] Logged into Chrome Web Store developer console with the right account
