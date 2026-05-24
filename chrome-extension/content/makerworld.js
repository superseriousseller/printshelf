// PrintShelf — Makerworld content script.
//
// Injects a floating "Add to PrintShelf" button on model pages and pulls
// metadata (title, designer, thumbnail, source URL) from the rendered DOM
// when the button is clicked. Reading on click rather than on inject
// keeps us safe against late hydration.

(() => {
  const PLATFORM = "makerworld";
  const FAB_ID = "printshelf-fab";

  // Match /models/<id...> at any locale prefix: /en/models/..., /ja/models/..., /models/...
  const MODEL_PATH_RE = /^\/([a-z]{2,3}\/)?models\/[^/]+/i;

  // ---------- Metadata extraction ----------

  const trim = (s) => (typeof s === "string" ? s.replace(/\s+/g, " ").trim() : "");

  const metaContent = (selector) => {
    const el = document.querySelector(selector);
    return el ? trim(el.getAttribute("content")) : "";
  };

  function readJsonLdAuthors() {
    const out = [];
    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
    for (const s of scripts) {
      try {
        const raw = JSON.parse(s.textContent || "null");
        const nodes = Array.isArray(raw) ? raw : [raw];
        for (const node of nodes) {
          if (!node || typeof node !== "object") continue;
          const author = node.author || node.creator;
          if (!author) continue;
          if (Array.isArray(author)) {
            for (const a of author) if (a && a.name) out.push(trim(a.name));
          } else if (typeof author === "object" && author.name) {
            out.push(trim(author.name));
          } else if (typeof author === "string") {
            out.push(trim(author));
          }
        }
      } catch {
        /* malformed JSON-LD — skip */
      }
    }
    return out.filter(Boolean);
  }

  function extractDesigner() {
    const fromLd = readJsonLdAuthors();
    if (fromLd.length) return fromLd[0];

    // Makerworld designer link patterns observed in the rendered DOM.
    const candidates = document.querySelectorAll(
      'a[href*="/@"], a[href*="/u/"], a[href*="/profile/"], a[href*="/user/"]'
    );
    for (const a of candidates) {
      const txt = trim(a.textContent);
      if (!txt) continue;
      if (txt.length > 60) continue;
      if (/^(home|login|sign\s*up|profile|settings)$/i.test(txt)) continue;
      // Skip nav links — designer names usually appear near the title within main content.
      if (a.closest('nav, header[role="banner"], footer')) continue;
      return txt;
    }

    // og:title sometimes encodes "Title by Author"
    const og = metaContent('meta[property="og:title"]');
    const m = /\bby\s+([^|·•\-—]+?)(?:\s*[|·•\-—].*)?$/i.exec(og);
    if (m) return trim(m[1]);
    return "";
  }

  function extractThumbnail() {
    const og = metaContent('meta[property="og:image"]') || metaContent('meta[name="twitter:image"]');
    if (og && !/og-icon|default|placeholder/i.test(og)) return og;

    // Fallback: first sizable <img> outside chrome/nav.
    const imgs = Array.from(document.querySelectorAll("img"));
    for (const img of imgs) {
      if (img.closest('nav, header[role="banner"], footer')) continue;
      const src = img.currentSrc || img.src;
      if (!src || src.startsWith("data:")) continue;
      const w = img.naturalWidth || img.width || 0;
      const h = img.naturalHeight || img.height || 0;
      if (w >= 200 && h >= 200) return src;
    }
    return og || "";
  }

  function extractTitle() {
    const og = metaContent('meta[property="og:title"]');
    if (og) return og.replace(/\s*[|·•\-—]\s*Makerworld.*$/i, "").trim();

    const h1 = document.querySelector("h1");
    if (h1 && trim(h1.textContent)) return trim(h1.textContent);

    const t = trim(document.title);
    return t.replace(/\s*[|·•\-—]\s*Makerworld.*$/i, "").trim();
  }

  function canonicalUrl() {
    const link = document.querySelector('link[rel="canonical"]');
    const href = link && link.getAttribute("href");
    if (href) return href;
    // Strip tracking params from window URL.
    try {
      const u = new URL(window.location.href);
      ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "ref"].forEach((p) =>
        u.searchParams.delete(p)
      );
      return u.toString();
    } catch {
      return window.location.href;
    }
  }

  function extract() {
    return {
      title: extractTitle(),
      designer: extractDesigner(),
      thumbnailUrl: extractThumbnail(),
      sourceUrl: canonicalUrl(),
      sourcePlatform: PLATFORM,
    };
  }

  // ---------- Page-fit check ----------

  function isModelPage() {
    return MODEL_PATH_RE.test(window.location.pathname);
  }

  // ---------- HTML escaping ----------

  const escapeHtml = (s) =>
    String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  // ---------- FAB UI ----------

  function buildFab() {
    const root = document.createElement("div");
    root.id = FAB_ID;
    root.innerHTML = `
      <div class="ps-fab-toast" data-toast hidden></div>
      <button class="ps-fab-btn" type="button" data-btn>
        <span class="ps-fab-icon" data-icon>+</span>
        <span data-label>Add to PrintShelf</span>
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
      // Use textContent by default; allow safe HTML when we control the input.
      if (kind === "html") toast.innerHTML = htmlOrText;
      else toast.textContent = htmlOrText;
      // Force reflow for transition.
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
      if (!meta.title) {
        showToast("Couldn't read the model title from this page yet — wait a moment and try again.", "text");
        return;
      }
      setState("loading", "Saving…", { disabled: true });

      let resp;
      try {
        resp = await chrome.runtime.sendMessage({ type: "addPrint", payload: meta });
      } catch (err) {
        // Service worker can be dormant; sendMessage failures usually recover on retry.
        setState("error", "Try again", { icon: "!" });
        showToast(`Extension error: ${err.message || err}`, "text");
        setTimeout(() => setState("idle", "Add to PrintShelf"), 3500);
        return;
      }

      if (resp && resp.ok) {
        setState("success", "Saved to queue", { icon: "✓" });
        if (resp.printUrl) {
          showToast(
            `Saved “${escapeHtml(meta.title)}” to your queue. ` +
              `<a href="${escapeHtml(resp.printUrl)}" target="_blank" rel="noopener">View in PrintShelf →</a>`,
            "html",
            8000
          );
        } else {
          showToast(`Saved “${meta.title}” to your queue.`, "text");
        }
        setTimeout(() => setState("idle", "Add to PrintShelf"), 3500);
        return;
      }

      setState("error", "Try again", { icon: "!" });
      const errText = (resp && resp.error) || "Save failed.";
      if (resp && resp.needsApiKey) {
        showToast(
          `${errText} <a href="#" data-open-options>Open settings</a>`,
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
      setTimeout(() => setState("idle", "Add to PrintShelf"), 4500);
    });

    return root;
  }

  function ensureFab() {
    if (!isModelPage()) {
      removeFab();
      return;
    }
    if (document.getElementById(FAB_ID)) return;
    if (!document.body) return; // run_at: document_idle should guarantee body, but be safe.
    buildFab();
  }

  function removeFab() {
    const existing = document.getElementById(FAB_ID);
    if (existing) existing.remove();
  }

  // ---------- SPA URL watcher ----------
  // Makerworld is a client-rendered SPA; route changes don't reload the page.

  let lastUrl = window.location.href;
  const onUrlMaybeChanged = () => {
    if (window.location.href === lastUrl) return;
    lastUrl = window.location.href;
    ensureFab();
  };

  // popstate (Back / Forward) is a real DOM event and crosses the isolated
  // world, so we catch it for free. pushState/replaceState patches only work
  // for calls inside *our* world — Next.js router calls in the page world
  // sail past them, so a 1 Hz URL poll is the reliable fallback.
  window.addEventListener("popstate", onUrlMaybeChanged);
  setInterval(onUrlMaybeChanged, 1000);

  // Initial inject.
  ensureFab();
})();
