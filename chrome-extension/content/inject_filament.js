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

  const STORES = [
    {
      store: "polymaker",
      hosts: ["us.polymaker.com", "polymaker.com", "shop.polymaker.com"],
      // Shopify storefronts use /products/<slug> for product pages.
      pathPattern: /^\/products\/[^/]+/i,
      // Best-effort: pull the active swatch's accessible label. Polymaker's
      // theme renders swatches as radio inputs with associated <label>s.
      readColorName: () => {
        // 1. Checked swatch input → look up its label.
        const checked = document.querySelector(
          'fieldset.product-form__input--swatch input[type="radio"]:checked, ' +
            '.product-form__input--swatch input[type="radio"]:checked, ' +
            'input[type="radio"][name^="Color"]:checked, ' +
            'input[type="radio"][name*="color" i]:checked'
        );
        if (checked) {
          if (checked.id) {
            const lbl = document.querySelector(`label[for="${CSS.escape(checked.id)}"]`);
            const text = lbl ? (lbl.getAttribute("aria-label") || lbl.textContent || "") : "";
            if (text.trim()) return text.trim();
          }
          if (checked.value && checked.value.trim()) return checked.value.trim();
        }
        // 2. Visible "Color: <name>" pattern that Dawn themes render.
        for (const legend of document.querySelectorAll(".product-form__input legend, .product-form__input .form__label")) {
          const text = (legend.textContent || "").trim();
          const m = text.match(/color\s*[:：]\s*(.+)$/i);
          if (m) return m[1].trim();
        }
        return "";
      },
    },
  ];

  const HOST = (window.location.hostname || "").toLowerCase();
  const CONFIG = STORES.find((s) => s.hosts.includes(HOST));
  if (!CONFIG) return; // host not in our list — should never happen given the manifest match.

  // ---------- Helpers ----------

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
    return {
      sourceUrl: window.location.href,
      store: CONFIG.store,
      colorName: CONFIG.readColorName() || null,
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
      const meta = extract();
      setState("loading", "Adding…", { disabled: true });

      let resp;
      try {
        resp = await chrome.runtime.sendMessage({ type: "addFilament", payload: meta });
      } catch (err) {
        setState("error", "Try again", { icon: "!" });
        showToast(`Extension error: ${err.message || err}`, "text");
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
      const errText = (resp && resp.error) || "Save failed.";
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
