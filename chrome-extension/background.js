// PrintShelf background service worker.
//
// Owns:
//   - chrome.storage.sync reads for {apiKey, apiBase}
//   - All outbound /api/prints/queue POSTs (keeps API key out of page scope)
//   - chrome.action badge for transient success/error indication
//
// Message contract (from content scripts):
//   { type: "addPrint", payload: { title, designer?, sourceUrl, thumbnailUrl?, sourcePlatform } }
//     → { ok: true, print: {...} }
//     → { ok: false, error: "human-readable", needsApiKey?: bool, status?: number }

const DEFAULT_API_BASE = "https://printshelf.app";

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
    return { ok: false, status: 402, error: detail || "Free tier limit reached. Upgrade on printshelf.app." };
  }
  const serverMsg = data && (data.detail || data.error || data.message);
  return { ok: false, status: res.status, error: serverMsg || `Server returned ${res.status}` };
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
  if (msg && msg.type === "openOptions") {
    chrome.runtime.openOptionsPage();
    sendResponse({ ok: true });
    return false;
  }
  return false;
});
