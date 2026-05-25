// PrintShelf — model-platform content script.
//
// Injects a floating "Add to PrintShelf" button on model pages and pulls
// metadata (title, designer, thumbnail, source URL) from the rendered DOM
// when the button is clicked. Reading on click (rather than on inject)
// keeps us safe against late hydration.
//
// One script handles all four platforms — only the path pattern and the
// per-site author-link selectors really differ. Title/thumbnail use the
// generic OG-tag fallbacks.

(() => {
  const FAB_ID = "printshelf-fab";

  const PLATFORMS = [
    {
      platform: "makerworld",
      hosts: ["makerworld.com", "www.makerworld.com"],
      siteName: "Makerworld",
      // /en/models/<id>-<slug>, /models/<anything>, etc.
      pathPattern: /^\/([a-z]{2,3}\/)?models\/[^/]+/i,
      designerSelectors: [
        'a[href*="/@"]',
        'a[href*="/u/"]',
        'a[href*="/profile/"]',
        'a[href*="/user/"]',
      ],
      // Makerworld's og:title is "<name> - Free 3D Print Model" — strip the boilerplate suffix.
      titleSuffixRe: /\s*[-–—]\s*Free 3D Print Model\s*$/i,
    },
    {
      platform: "printables",
      hosts: ["printables.com", "www.printables.com"],
      siteName: "Printables",
      // /en/model/123456-foo or /model/123456-foo
      pathPattern: /^\/([a-z]{2,3}\/)?model\/\d+/i,
      designerSelectors: [
        'a[href^="/@"]',
        'a[href*="/social/"]',
        'a[href*="/users/"]',
      ],
    },
    {
      platform: "cults3d",
      hosts: ["cults3d.com", "www.cults3d.com"],
      siteName: "Cults3D",
      // /en/3d-model/<category>/<slug>
      pathPattern: /^\/([a-z]{2,3}\/)?3d-model\/[^/]+\/[^/]+/i,
      designerSelectors: ['a[href*="/users/"]'],
    },
    {
      platform: "thingiverse",
      hosts: ["thingiverse.com", "www.thingiverse.com"],
      siteName: "Thingiverse",
      // /thing:1234567
      pathPattern: /^\/thing:\d+/i,
      designerSelectors: ['a[href$="/designs"]', 'a[href*="/users/"]'],
    },
  ];

  const HOST = (window.location.hostname || "").toLowerCase();
  const CONFIG = PLATFORMS.find((p) => p.hosts.includes(HOST));
  if (!CONFIG) return; // host not in our list — should never happen given the manifest match, but safe.

  // ---------- Metadata extraction ----------

  const trim = (s) => (typeof s === "string" ? s.replace(/\s+/g, " ").trim() : "");

  const metaContent = (selector) => {
    const el = document.querySelector(selector);
    return el ? trim(el.getAttribute("content")) : "";
  };

  // Walk every JSON-LD <script>, including @graph children. Returns a flat
  // list of node objects.
  function readJsonLdNodes() {
    const out = [];
    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
    for (const s of scripts) {
      try {
        const raw = JSON.parse(s.textContent || "null");
        const stack = Array.isArray(raw) ? [...raw] : [raw];
        while (stack.length) {
          const node = stack.shift();
          if (!node || typeof node !== "object") continue;
          out.push(node);
          if (Array.isArray(node["@graph"])) stack.push(...node["@graph"]);
        }
      } catch {
        /* malformed JSON-LD — skip */
      }
    }
    return out;
  }

  function readJsonLdAuthors() {
    const out = [];
    for (const node of readJsonLdNodes()) {
      // Thingiverse uses brand.name for the uploader; others use author / creator.
      const author = node.author || node.creator || node.brand;
      if (!author) continue;
      if (Array.isArray(author)) {
        for (const a of author) if (a && a.name) out.push(trim(a.name));
      } else if (typeof author === "object" && author.name) {
        out.push(trim(author.name));
      } else if (typeof author === "string") {
        out.push(trim(author));
      }
    }
    return out.filter(Boolean);
  }

  // BreadcrumbList / ItemList / Person etc. nodes also carry `name` but it's
  // never the model title — skip them when hunting for the product name.
  const NAME_TYPE_BLOCKLIST = new Set([
    "breadcrumblist",
    "itemlist",
    "person",
    "organization",
    "webpage",
    "website",
    "imageobject",
    "siteNavigationElement".toLowerCase(),
  ]);

  function readJsonLdName() {
    for (const node of readJsonLdNodes()) {
      const t = Array.isArray(node["@type"]) ? node["@type"][0] : node["@type"];
      if (t && NAME_TYPE_BLOCKLIST.has(String(t).toLowerCase())) continue;
      if (node.name && typeof node.name === "string") {
        const n = trim(node.name);
        if (n) return n;
      }
    }
    return "";
  }

  function extractDesigner() {
    const fromLd = readJsonLdAuthors();
    if (fromLd.length) return fromLd[0];

    const selector = CONFIG.designerSelectors.join(", ");
    const candidates = document.querySelectorAll(selector);
    for (const a of candidates) {
      const txt = trim(a.textContent);
      if (!txt) continue;
      if (txt.length > 60) continue;
      if (/^(home|login|sign\s*up|profile|settings|follow|message|share)$/i.test(txt)) continue;
      if (a.closest('nav, header[role="banner"], footer')) continue;
      return txt;
    }

    // Last resort: og:title sometimes encodes "Title by Author"
    const og = metaContent('meta[property="og:title"], meta[name="og:title"]');
    const m = /\bby\s+([^|·•\-—]+?)(?:\s*[|·•\-—].*)?$/i.exec(og);
    if (m) return trim(m[1]);
    return "";
  }

  function extractThumbnail() {
    const og =
      metaContent('meta[property="og:image"], meta[name="og:image"]') ||
      metaContent('meta[name="twitter:image"], meta[property="twitter:image"]');
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

  const escapeRe = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  // Normalize a raw title (from JSON-LD, og:title, h1, or document.title) by
  // stripping the common forms of page-title pollution we've seen in QA:
  //   • Trailing " | <anything>" — pipe-separated cruft (Printables: "| Download free STL model | Printables.com")
  //   • A platform-specific dash suffix (Makerworld: " - Free 3D Print Model")
  //   • The platform site name joined by a separator (" - Thingiverse")
  //   • A trailing " by <…designer…>" attribution when designer is known
  //     (handles Thingiverse's doubled "by CreativeTools.se by CreativeTools").
  function cleanTitle(raw, designer) {
    if (!raw) return "";
    let cleaned = raw.trim();

    const pipeIdx = cleaned.indexOf(" | ");
    if (pipeIdx !== -1) cleaned = cleaned.slice(0, pipeIdx).trim();

    // Site-name suffix comes off first — it's always the outermost tail.
    // Makerworld's og:title is "<name> - Free 3D Print Model - MakerWorld";
    // peeling the site name first exposes the inner boilerplate suffix
    // to titleSuffixRe.
    const siteRe = new RegExp(`\\s*[·•\\-–—]\\s*${escapeRe(CONFIG.siteName)}\\s*$`, "i");
    cleaned = cleaned.replace(siteRe, "").trim();

    if (CONFIG.titleSuffixRe) cleaned = cleaned.replace(CONFIG.titleSuffixRe, "").trim();

    if (designer) {
      // Greedy `[^|]*` lets us strip a doubled "by X by Y" tail as long as the
      // designer string appears somewhere in it.
      const byRe = new RegExp(`\\s+by\\s+[^|]*${escapeRe(designer)}[^|]*\\s*$`, "i");
      const stripped = cleaned.replace(byRe, "").trim();
      if (stripped.length >= 3) cleaned = stripped;
    }

    return cleaned;
  }

  function extractTitle(designer) {
    // JSON-LD `name` is the cleanest source when present — sites populate it
    // with the model name and nothing else. Skip non-product node types.
    const ldName = readJsonLdName();
    if (ldName) return cleanTitle(ldName, designer);

    const og = metaContent('meta[property="og:title"], meta[name="og:title"]');
    if (og) return cleanTitle(og, designer);

    const h1 = document.querySelector("h1");
    if (h1 && trim(h1.textContent)) return cleanTitle(trim(h1.textContent), designer);

    return cleanTitle(trim(document.title), designer);
  }

  function canonicalUrl() {
    const link = document.querySelector('link[rel="canonical"]');
    const href = link && link.getAttribute("href");
    if (href) return href;
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
    // Designer first so extractTitle can strip a trailing " by <designer>".
    const designer = extractDesigner();
    return {
      title: extractTitle(designer),
      designer,
      thumbnailUrl: extractThumbnail(),
      sourceUrl: canonicalUrl(),
      sourcePlatform: CONFIG.platform,
    };
  }

  // ---------- Page-fit check ----------

  function isModelPage() {
    return CONFIG.pathPattern.test(window.location.pathname);
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
      if (!meta.title) {
        showToast("Couldn't read the model title from this page yet — wait a moment and try again.", "text");
        return;
      }
      setState("loading", "Saving…", { disabled: true });

      let resp;
      try {
        resp = await chrome.runtime.sendMessage({ type: "addPrint", payload: meta });
      } catch (err) {
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
    if (!document.body) return;
    buildFab();
  }

  function removeFab() {
    const existing = document.getElementById(FAB_ID);
    if (existing) existing.remove();
  }

  // ---------- SPA URL watcher ----------
  // popstate (Back / Forward) is a real DOM event and crosses the isolated
  // world, so we catch it for free. SPA router pushState/replaceState calls
  // happen in the page world, out of reach of an isolated-world patch — a
  // 1 Hz URL poll is the reliable fallback.

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
