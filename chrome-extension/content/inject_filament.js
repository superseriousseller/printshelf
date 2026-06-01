// PrintShelf — filament-retailer content script.
//
// Injects a floating "Add filament to PrintShelf" button on retailer
// product pages. On click, sends the current URL to the background
// worker, which delegates metadata extraction to PrintShelf's server
// (/api/filaments/import-url) and then creates the filament.
//
// The extension's job is intentionally light:
//   1. Detect we're on a product page.
//   2. Read the currently-SELECTED variant color from the DOM — that's
//      the bit the server scrape can't see (the OG tag shows the
//      default variant, not the user's selection).
//   3. Let the server do the rest (brand, material, base color, price).
//
// Phase-2 scope: Polymaker only. Other retailers will be added as
// additional entries in STORES with their own DOM selectors.

(() => {
  const FAB_ID = "printshelf-fab";

  // Hunt for a 6-digit hex within a label DOM subtree. Polymaker stores it
  // in any of these places depending on the theme/product line:
  //   - inline style attr on the label or a descendant
  //     (style="background-color:#F4EFEB" or "--swatch-color:#F4EFEB")
  //   - textContent of the label (the Panchroma swatches print
  //     "Matte\nCotton\nWhite\n  #F4EFEB" into the label body)
  function findHexInLabel(lbl) {
    if (!lbl) return "";
    // 1. Style attr on the label itself or any descendant.
    const candidates = [lbl, ...lbl.querySelectorAll("[style]")];
    for (const el of candidates) {
      const m = (el.getAttribute("style") || "").match(/#[0-9A-Fa-f]{6}\b/);
      if (m) return m[0].toLowerCase();
    }
    // 2. textContent fallback.
    const m = (lbl.textContent || "").match(/#[0-9A-Fa-f]{6}\b/);
    return m ? m[0].toLowerCase() : "";
  }

  // Polymaker's product description / spec table includes a "HEX Code: #XXXXXX"
  // row for filaments. Use that as a page-wide fallback when the swatch label
  // doesn't carry the hex itself (PolyLite line, etc.).
  function findHexInPageDescription() {
    // Common containers Shopify themes drop the description into.
    const containers = document.querySelectorAll(
      ".product__description, .product-single__description, " +
        ".product-description, .rte, [itemprop='description']"
    );
    for (const c of containers) {
      const text = c.textContent || "";
      const m = text.match(/hex(?:\s*code)?\s*[:：]?\s*(#[0-9A-Fa-f]{6})\b/i);
      if (m) return m[1].toLowerCase();
    }
    // Last-ditch: any "HEX Code: #XXXXXX" anywhere on the page.
    const m = (document.body.textContent || "").match(/hex(?:\s*code)?\s*[:：]\s*(#[0-9A-Fa-f]{6})\b/i);
    return m ? m[1].toLowerCase() : "";
  }

  // Pull a clean color name + hex out of a label's combined textContent.
  // Polymaker's swatch labels concatenate the slug ("MatteCottonWhite"),
  // an inline hex string, and the proper name ("Matte Cotton White") — we
  // want only the proper name and the hex, separately.
  function cleanColorLabel(raw) {
    const text = String(raw || "");
    const hexMatch = text.match(/#[0-9A-Fa-f]{6}\b/);
    const hex = hexMatch ? hexMatch[0].toLowerCase() : "";
    // Strip hex(es) and collapse whitespace.
    const stripped = text.replace(/#[0-9A-Fa-f]{6}\b/g, " ").replace(/\s+/g, " ").trim();
    // Prefer the longest "Proper Cased Words" sub-phrase ("Matte Cotton White").
    // The lookbehind prevents matching mid-CamelCase — without it, the regex
    // happily started at the trailing "White" of "MatteCottonWhite" and ate
    // everything that followed.
    const properPhrases = stripped.match(/(?<![A-Za-z])[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+/g) || [];
    if (properPhrases.length) {
      properPhrases.sort((a, b) => b.length - a.length);
      return { name: properPhrases[0], hex };
    }
    // No multi-word phrase — return the longest non-CamelCase-concat word.
    const singleWord = stripped.match(/(?<![A-Za-z])[A-Z][a-z]+(?![A-Za-z])/g) || [];
    if (singleWord.length) {
      singleWord.sort((a, b) => b.length - a.length);
      return { name: singleWord[0], hex };
    }
    return { name: stripped, hex };
  }

  // Converts an rgb(r,g,b) string to lowercase #rrggbb hex. Used to normalise
  // inline style background-color values from computed styles.
  function rgbToHex(rgb) {
    const m = (rgb || "").match(/rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)/i);
    if (!m) return "";
    return "#" + [m[1], m[2], m[3]].map((n) => parseInt(n, 10).toString(16).padStart(2, "0")).join("");
  }

  // Bambu product descriptions contain a <table class="pct_tb"> with one row per
  // color variant: color name | hex code | swatch cell. Parse it into a
  // lowercase-hex → canonical-name map so we can identify any selected swatch color.
  function buildBambuColorMap() {
    const map = {};
    for (const row of document.querySelectorAll("table.pct_tb tr")) {
      const cells = row.querySelectorAll("td");
      if (cells.length < 2) continue;
      const name = (cells[0].textContent || "").trim();
      const hexRaw = (cells[1].textContent || "").trim();
      const m = hexRaw.match(/#[0-9A-Fa-f]{6}/);
      if (name && m) map[m[0].toLowerCase()] = name;
    }
    return map;
  }

  const STORES = [
    {
      store: "bambu",
      hosts: ["us.store.bambulab.com", "eu.store.bambulab.com", "store.bambulab.com"],
      pathPattern: /^\/products\/[^/]+/i,
      readVariant: () => {
        const colorMap = buildBambuColorMap();

        // Walk candidate "selected swatch" elements from most to least specific.
        // Bambu's Next.js store renders variants as styled buttons/divs; we read
        // the background-color of whatever carries the active/selected state.
        const SWATCH_SELECTORS = [
          // Aria / data attributes set by their React components
          "[aria-selected='true']",
          "[aria-pressed='true']",
          "[data-selected='true']",
          "[data-active='true']",
          // Common CSS-class patterns for active swatches
          ".selected", ".is-selected", ".active", ".is-active",
          ".sku--selected", ".sku-item--active", ".color--selected",
          ".variant--active", ".product-option--selected",
        ];
        for (const sel of SWATCH_SELECTORS) {
          for (const el of document.querySelectorAll(sel)) {
            // Read inline style first (most reliable), then computed.
            const inlineStyle = el.getAttribute("style") || "";
            const inlineMatch = inlineStyle.match(/background(?:-color)?\s*:\s*(#[0-9A-Fa-f]{6}|rgb\([^)]+\))/i);
            let hex = inlineMatch
              ? (inlineMatch[1].startsWith("#") ? inlineMatch[1].toLowerCase() : rgbToHex(inlineMatch[1]))
              : "";
            if (!hex) {
              const computed = window.getComputedStyle(el).backgroundColor;
              hex = computed && computed !== "rgba(0, 0, 0, 0)" && computed !== "transparent"
                ? rgbToHex(computed) : "";
            }
            if (hex && colorMap[hex]) return { name: colorMap[hex], hex };
            if (hex) {
              // Hex found but not in table — fall through to name-reading below
              // but keep the hex so we can still return something.
              const name = (el.getAttribute("aria-label") || el.getAttribute("title") || "").trim();
              if (name) return { name, hex };
            }
          }
        }

        // No selected swatch found — try reading a "Color: <name>" text label that
        // Bambu renders near the variant picker once a variant is selected.
        const colorLabelPattern = /color\s*[:：]\s*(.+)/i;
        for (const el of document.querySelectorAll("[class*='option'], [class*='variant'], [class*='color'], [class*='sku']")) {
          const text = (el.textContent || "").replace(/\s+/g, " ").trim();
          const m = text.match(colorLabelPattern);
          if (m && m[1].trim().length > 0 && m[1].trim().length < 60) {
            const name = m[1].trim();
            const hexEntry = Object.entries(colorMap).find(([, n]) => n.toLowerCase() === name.toLowerCase());
            return { name, hex: hexEntry ? hexEntry[0] : "" };
          }
        }

        return { name: "", hex: "" };
      },
    },
    {
      // Anycubic (Shopify). Each color is a radio input whose value attribute
      // contains both the name and hex: e.g. "White (#EFF0F1)".
      store: "anycubic",
      hosts: ["store.anycubic.com"],
      pathPattern: /^\/products\/[^/]+/i,
      readVariant: () => {
        const checked = document.querySelector(
          'input[type="radio"][name="Color"]:checked, ' +
          'input[type="radio"][name*="color" i]:checked'
        );
        if (!checked) return { name: "", hex: "" };
        // value format: "White (#EFF0F1)" or "Black (#212721)"
        const raw = checked.value || "";
        const hexMatch = raw.match(/#([0-9A-Fa-f]{6})/);
        const hex = hexMatch ? "#" + hexMatch[1].toLowerCase() : "";
        // Strip the parenthesised hex to get the clean color name
        const name = raw.replace(/\s*\(#[0-9A-Fa-f]{6}\)\s*/i, "").trim();
        return { name, hex };
      },
    },
    {
      // MatterHackers. Each color is its own URL (/store/l/{slug}/sk/{SKU}).
      // The color name lives in the page title — let the server extract it.
      store: "matterhackers",
      hosts: ["www.matterhackers.com", "matterhackers.com"],
      pathPattern: /^\/store\/l\//i,
      readVariant: () => ({ name: "", hex: "" }),
    },
    {
      // Amazon. Selected color name shown in
      // #inline-twister-expanded-dimension-text-color_name. No hex available.
      store: "amazon",
      hosts: ["www.amazon.com", "amazon.com"],
      pathPattern: /\/dp\/[A-Z0-9]{10}|\/gp\/product\/[A-Z0-9]{10}/i,
      readVariant: () => {
        // Primary: the inline twister selected-value span
        const el = document.getElementById("inline-twister-expanded-dimension-text-color_name");
        if (el) {
          const name = (el.textContent || "").trim();
          if (name) return { name, hex: "" };
        }
        // Fallback: aria-label on the dimension heading "Selected Color is X."
        const heading = document.querySelector("[aria-label*='Selected Color']");
        if (heading) {
          const m = (heading.getAttribute("aria-label") || "").match(/Selected Color is ([^.]+)\./i);
          if (m) return { name: m[1].trim(), hex: "" };
        }
        return { name: "", hex: "" };
      },
    },
    {
      store: "polymaker",
      hosts: ["us.polymaker.com", "polymaker.com", "shop.polymaker.com"],
      // Shopify storefronts use /products/<slug> for product pages.
      pathPattern: /^\/products\/[^/]+/i,
      // Returns { name, hex } for the currently-selected color variant.
      readVariant: () => {
        // 1. Checked swatch input → look up its associated <label>.
        const checked = document.querySelector(
          'fieldset.product-form__input--swatch input[type="radio"]:checked, ' +
            '.product-form__input--swatch input[type="radio"]:checked, ' +
            'input[type="radio"][name^="Color"]:checked, ' +
            'input[type="radio"][name*="color" i]:checked'
        );
        let lbl = null;
        if (checked && checked.id) {
          lbl = document.querySelector(`label[for="${CSS.escape(checked.id)}"]`);
        }
        // Hunt the hex up-front so every name-source branch can reuse it.
        const hexFromLabel = lbl ? findHexInLabel(lbl) : "";
        const hex = hexFromLabel || findHexInPageDescription();

        if (lbl) {
          // a. aria-label is almost always clean ("Matte Cotton White").
          const aria = (lbl.getAttribute("aria-label") || "").trim();
          if (aria) return { name: aria, hex };
          // b. visually-hidden span (Shopify accessibility pattern).
          const vh = lbl.querySelector(".visually-hidden, .sr-only, .visuallyhidden");
          if (vh && (vh.textContent || "").trim()) {
            const cleaned = cleanColorLabel(vh.textContent);
            return { name: cleaned.name, hex: hex || cleaned.hex };
          }
          // c. Last resort: parse the combined textContent (carries slug+hex+name blob).
          const cleaned = cleanColorLabel(lbl.textContent);
          return { name: cleaned.name, hex: hex || cleaned.hex };
        }
        if (checked && checked.value && checked.value.trim()) {
          const cleaned = cleanColorLabel(checked.value);
          return { name: cleaned.name, hex: hex || cleaned.hex };
        }
        // 2. Visible "Color: <name>" pattern that Dawn themes render outside swatches.
        for (const legend of document.querySelectorAll(".product-form__input legend, .product-form__input .form__label")) {
          const text = (legend.textContent || "").trim();
          const m = text.match(/color\s*[:：]\s*(.+)$/i);
          if (m) {
            const cleaned = cleanColorLabel(m[1]);
            return { name: cleaned.name, hex: hex || cleaned.hex };
          }
        }
        return { name: "", hex };
      },
    },
  ];

  const HOST = (window.location.hostname || "").toLowerCase();
  const CONFIG = STORES.find((s) => s.hosts.includes(HOST));
  if (!CONFIG) return; // host not in our list — should never happen given the manifest match.

  // One-shot console log on inject so you can verify the loaded version in
  // devtools without opening chrome://extensions: `chrome.runtime.getManifest().version`
  // works too but this is zero-typing.
  try {
    const v = chrome.runtime && chrome.runtime.getManifest && chrome.runtime.getManifest().version;
    if (v) console.log(`[PrintShelf] filament content script v${v} active on ${HOST}`);
  } catch { /* orphaned context — fine, we'll handle it on click */ }

  // ---------- Helpers ----------

  // After the extension is reloaded (e.g. dev-mode "Reload" in chrome://extensions),
  // already-injected content scripts on open tabs become orphans: chrome.runtime
  // still appears to exist but has no .id and any sendMessage call throws
  // "Cannot read properties of undefined (reading 'sendMessage')". Detecting this
  // lets us show a clean "refresh this page" message instead of the cryptic error.
  function isOrphanedExtensionContext() {
    try {
      return !chrome || !chrome.runtime || !chrome.runtime.id;
    } catch {
      return true;
    }
  }

  const escapeHtml = (s) =>
    String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  function isProductPage() {
    return CONFIG.pathPattern.test(window.location.pathname);
  }

  function extract() {
    const variant = CONFIG.readVariant ? CONFIG.readVariant() : { name: "", hex: "" };
    return {
      sourceUrl: window.location.href,
      store: CONFIG.store,
      colorName: (variant.name || "").trim() || null,
      colorHex: (variant.hex || "").trim() || null,
    };
  }

  // ---------- FAB UI ----------

  function buildFab() {
    const root = document.createElement("div");
    root.id = FAB_ID;
    root.innerHTML = `
      <div class="ps-fab-toast" data-toast hidden></div>
      <button class="ps-fab-btn" type="button" data-btn>
        <span class="ps-fab-icon" data-icon>+</span>
        <span data-label>Add filament to PrintShelf</span>
      </button>
    `;
    document.body.appendChild(root);

    const btn = root.querySelector("[data-btn]");
    const label = root.querySelector("[data-label]");
    const icon = root.querySelector("[data-icon]");
    const toast = root.querySelector("[data-toast]");

    const setState = (state, text, opts = {}) => {
      root.classList.remove("ps-state-success", "ps-state-error");
      if (state === "success") root.classList.add("ps-state-success");
      if (state === "error") root.classList.add("ps-state-error");
      label.textContent = text;
      btn.disabled = !!opts.disabled;
      icon.textContent = opts.icon || "+";
    };

    const showToast = (htmlOrText, kind, autoHideMs = 5000) => {
      toast.removeAttribute("hidden");
      if (kind === "html") toast.innerHTML = htmlOrText;
      else toast.textContent = htmlOrText;
      void toast.offsetWidth;
      toast.classList.add("ps-visible");
      clearTimeout(toast._hideT);
      if (autoHideMs > 0) {
        toast._hideT = setTimeout(() => {
          toast.classList.remove("ps-visible");
          setTimeout(() => toast.setAttribute("hidden", ""), 200);
        }, autoHideMs);
      }
    };

    btn.addEventListener("click", async () => {
      if (isOrphanedExtensionContext()) {
        setState("error", "Refresh page", { icon: "!" });
        showToast(
          "PrintShelf was reloaded — refresh this page to re-enable the button.",
          "text",
          8000
        );
        setTimeout(() => setState("idle", "Add filament to PrintShelf"), 5000);
        return;
      }
      const meta = extract();
      setState("loading", "Adding…", { disabled: true });

      let resp;
      try {
        resp = await chrome.runtime.sendMessage({ type: "addFilament", payload: meta });
      } catch (err) {
        setState("error", "Try again", { icon: "!" });
        const msg = /Extension context invalidated|undefined.*sendMessage/i.test(String(err && err.message || err))
          ? "PrintShelf was reloaded — refresh this page to re-enable the button."
          : `Extension error: ${err.message || err}`;
        showToast(msg, "text", 8000);
        setTimeout(() => setState("idle", "Add filament to PrintShelf"), 3500);
        return;
      }

      if (resp && resp.ok) {
        setState("success", "Added to wishlist", { icon: "✓" });
        const labelText = resp.filament
          ? `${resp.filament.brand || ""} ${resp.filament.material || ""}${resp.filament.colorName ? " · " + resp.filament.colorName : ""}`.trim()
          : "filament";
        if (resp.filamentUrl) {
          showToast(
            `Added ${escapeHtml(labelText)} to your wishlist. ` +
              `<a href="${escapeHtml(resp.filamentUrl)}" target="_blank" rel="noopener">View in PrintShelf →</a>`,
            "html",
            8000
          );
        } else {
          showToast(`Added ${labelText} to your wishlist.`, "text");
        }
        setTimeout(() => setState("idle", "Add filament to PrintShelf"), 3500);
        return;
      }

      // Manual-fallback path: server couldn't auto-fill all required fields;
      // open the prefilled dashboard form in a new tab so the user finishes
      // it themselves (only takes the unfilled fields).
      if (resp && resp.needsManual && resp.manualUrl) {
        setState("idle", "Add filament to PrintShelf");
        window.open(resp.manualUrl, "_blank", "noopener");
        showToast("Opened PrintShelf — finish a couple of fields and save.", "text", 6500);
        return;
      }

      setState("error", "Try again", { icon: "!" });
      // Belt-and-suspenders: humanizeError() in background.js already
      // stringifies object-shaped errors (FastAPI's structured 402 detail),
      // but coerce here too in case a future code path leaks an object.
      const rawErr = resp && resp.error;
      const errText =
        typeof rawErr === "string" ? rawErr :
        rawErr ? JSON.stringify(rawErr) :
        "Save failed.";
      if (resp && resp.needsApiKey) {
        showToast(
          `${escapeHtml(errText)} <a href="#" data-open-options>Open settings</a>`,
          "html",
          8000
        );
        toast.querySelector("[data-open-options]")?.addEventListener("click", (e) => {
          e.preventDefault();
          chrome.runtime.sendMessage({ type: "openOptions" });
        });
      } else {
        showToast(errText, "text", 6500);
      }
      setTimeout(() => setState("idle", "Add filament to PrintShelf"), 4500);
    });

    return root;
  }

  function ensureFab() {
    if (!isProductPage()) {
      removeFab();
      return;
    }
    if (document.getElementById(FAB_ID)) return;
    if (!document.body) return;
    buildFab();
  }

  function removeFab() {
    const existing = document.getElementById(FAB_ID);
    if (existing) existing.remove();
  }

  // ---------- SPA URL watcher ----------
  // Shopify storefronts swap variants client-side; the URL also changes on
  // some themes. popstate covers Back/Forward; 1Hz polling catches in-page
  // pushState (out of reach of an isolated-world patch).

  let lastUrl = window.location.href;
  const onUrlMaybeChanged = () => {
    if (window.location.href === lastUrl) return;
    lastUrl = window.location.href;
    ensureFab();
  };
  window.addEventListener("popstate", onUrlMaybeChanged);
  setInterval(onUrlMaybeChanged, 1000);

  ensureFab();
})();
