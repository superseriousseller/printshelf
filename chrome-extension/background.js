// PrintShelf background service worker.
//
// Owns:
//   - chrome.storage.sync reads for {apiKey, apiBase}
//   - All outbound /api/prints/queue + /api/filaments POSTs
//     (keeps API key out of page scope)
//   - chrome.action badge for transient success/error indication
//
// Message contract (from content scripts):
//   { type: "addPrint", payload: { title, designer?, sourceUrl, thumbnailUrl?, sourcePlatform } }
//     → { ok: true, print: {...} }
//     → { ok: false, error: "human-readable", needsApiKey?: bool, status?: number }
//
//   { type: "addFilament", payload: { sourceUrl, store?, colorName? } }
//     → { ok: true, filament: {...}, filamentUrl }
//     → { ok: false, needsManual: true, manualUrl } when server scrape is
//       too partial to auto-create — content script opens the prefilled
//       dashboard form so the user can finish two fields.
//     → { ok: false, error, needsApiKey?, status? } on real failures

const DEFAULT_API_BASE = "https://printshelf.app";

const FINISH_WORDS = [
  ["carbon fiber", "Carbon Fiber"],
  ["high speed", "High Speed"],
  ["silk", "Silk"],
  ["matte", "Matte"],
  ["glow", "Glow"],
  ["marble", "Marble"],
  ["wood", "Wood"],
  ["metal", "Metal"],
  ["translucent", "Translucent"],
  ["rainbow", "Rainbow"],
];

function extractFinish(title) {
  if (!title) return null;
  const t = title.toLowerCase();
  for (const [key, label] of FINISH_WORDS) {
    if (t.includes(key)) return label;
  }
  return null;
}

// FastAPI's HTTPException(detail=<object>) returns `detail` as a dict for
// structured errors like upgrade_required. Coerce it into a string we can
// show in a toast.
function humanizeError(detail, fallback) {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object") {
    if (detail.error === "upgrade_required") {
      const r = detail.resource || "items";
      return `Free-tier ${r} cap reached (${detail.current}/${detail.limit}). Upgrade on printshelf.app.`;
    }
    if (detail.message) return String(detail.message);
    if (detail.error) return String(detail.error);
  }
  return fallback;
}

const getConfig = () =>
  new Promise((resolve) => {
    chrome.storage.sync.get(["apiKey", "apiBase"], (out) => {
      resolve({
        apiKey: (out.apiKey || "").trim(),
        apiBase: (out.apiBase || DEFAULT_API_BASE).replace(/\/+$/, ""),
      });
    });
  });

async function addPrint(payload) {
  const { apiKey, apiBase } = await getConfig();
  if (!apiKey) {
    return { ok: false, error: "Set your PrintShelf API key in the extension popup.", needsApiKey: true };
  }

  const body = {
    title: payload.title,
    designer: payload.designer || null,
    source_url: payload.sourceUrl || null,
    thumbnail_url: payload.thumbnailUrl || null,
    source_platform: payload.sourcePlatform || "manual",
  };

  let res;
  try {
    res = await fetch(`${apiBase}/api/prints/queue`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify(body),
    });
  } catch (err) {
    return { ok: false, error: `Network error: ${err.message || err}` };
  }

  let data = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON response (HTML error page, etc.) — handled below */
  }

  if (res.ok) {
    const printUrl = data && data.id ? `${apiBase}/dashboard/prints/${data.id}/edit` : null;
    return { ok: true, print: data, printUrl };
  }

  if (res.status === 401) {
    return { ok: false, status: 401, error: "API key rejected — re-check it in the extension popup.", needsApiKey: true };
  }
  if (res.status === 402) {
    const detail = data && (data.detail || data.error || data.message);
    return { ok: false, status: 402, error: humanizeError(detail, "Free tier limit reached. Upgrade on printshelf.app.") };
  }
  const serverMsg = data && (data.detail || data.error || data.message);
  return { ok: false, status: res.status, error: humanizeError(serverMsg, `Server returned ${res.status}`) };
}

async function addFilament(payload) {
  const { apiKey, apiBase } = await getConfig();
  if (!apiKey) {
    return { ok: false, error: "Set your PrintShelf API key in the extension popup.", needsApiKey: true };
  }

  const sourceUrl = (payload.sourceUrl || "").trim();
  if (!sourceUrl) return { ok: false, error: "No URL on this page." };

  // 1) Ask the server to scrape brand / material / color / price from the page.
  let meta = null;
  try {
    const r = await fetch(`${apiBase}/api/filaments/import-url`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({ url: sourceUrl }),
    });
    if (r.status === 401) {
      return { ok: false, status: 401, error: "API key rejected — re-check it in the extension popup.", needsApiKey: true };
    }
    if (r.ok) {
      meta = await r.json().catch(() => null);
    } else {
      const data = await r.json().catch(() => null);
      const detail = data && (data.detail || data.error || data.message);
      // Don't bail — fall through to the manual-fallback path.
      console.warn("PrintShelf filament import-url failed:", r.status, detail);
    }
  } catch (err) {
    return { ok: false, error: `Network error: ${err.message || err}` };
  }

  // 2) Variant-aware override: the user's currently-selected color beats the
  //    server's default-variant scrape. colorHex only comes from the DOM —
  //    the server scrape doesn't currently extract hex codes.
  const colorName = (payload.colorName && payload.colorName.trim()) || (meta && meta.colorName) || null;
  const colorHex = (payload.colorHex && payload.colorHex.trim()) || null;
  const colorHexSource = payload.colorHexSource || null;
  const brand = meta && meta.brand;
  const material = meta && meta.material;
  const finish = extractFinish((meta && meta.title) || "");

  // If we don't have the minimum to auto-create (brand + material), fall back
  // to the prefilled dashboard form. The user finishes 1-2 fields and saves.
  if (!brand || !material) {
    const manualUrl = `${apiBase}/dashboard/filaments/new?import_url=${encodeURIComponent(sourceUrl)}`;
    return { ok: false, needsManual: true, manualUrl };
  }

  // 3) Create the filament. Default to "want" status — one-click adds from
  //    a buy page are almost always future-purchase intent. ("want" is the
  //    wishlist value in FilamentStatus.)
  const body = {
    brand,
    material,
    color_name: colorName,
    color_hex: colorHex,
    color_hex_source: colorHexSource,
    finish,
    source_url: sourceUrl,
    price_at_save: meta && typeof meta.price === "number" ? meta.price : null,
    status: "want",
  };

  let res;
  try {
    res = await fetch(`${apiBase}/api/filaments`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify(body),
    });
  } catch (err) {
    return { ok: false, error: `Network error: ${err.message || err}` };
  }

  let data = null;
  try { data = await res.json(); } catch { /* non-JSON — handled below */ }

  if (res.ok) {
    const filamentUrl = data && data.id ? `${apiBase}/dashboard/filaments/${data.id}/edit` : null;
    return {
      ok: true,
      filament: {
        id: data && data.id,
        brand: data && data.brand,
        material: data && data.material,
        colorName: data && data.colorName,
      },
      filamentUrl,
    };
  }

  if (res.status === 401) {
    return { ok: false, status: 401, error: "API key rejected — re-check it in the extension popup.", needsApiKey: true };
  }
  if (res.status === 402) {
    const detail = data && (data.detail || data.error || data.message);
    return { ok: false, status: 402, error: humanizeError(detail, "Free tier limit reached. Upgrade on printshelf.app.") };
  }
  const serverMsg = data && (data.detail || data.error || data.message);
  return { ok: false, status: res.status, error: humanizeError(serverMsg, `Server returned ${res.status}`) };
}

async function flashBadge(result) {
  try {
    if (result.ok) {
      await chrome.action.setBadgeBackgroundColor({ color: "#1f7a3a" });
      await chrome.action.setBadgeText({ text: "✓" });
    } else {
      await chrome.action.setBadgeBackgroundColor({ color: "#a13a2a" });
      await chrome.action.setBadgeText({ text: "!" });
    }
    setTimeout(() => chrome.action.setBadgeText({ text: "" }), 3500);
  } catch {
    /* setBadge can throw if the action isn't attached to a tab — non-fatal */
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "addPrint") {
    (async () => {
      const result = await addPrint(msg.payload || {});
      flashBadge(result);
      sendResponse(result);
    })();
    return true; // keep the channel open for the async sendResponse
  }
  if (msg && msg.type === "addFilament") {
    (async () => {
      const result = await addFilament(msg.payload || {});
      flashBadge(result);
      sendResponse(result);
    })();
    return true;
  }
  if (msg && msg.type === "openOptions") {
    chrome.runtime.openOptionsPage();
    sendResponse({ ok: true });
    return false;
  }
  return false;
});
