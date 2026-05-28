const DEFAULT_API_BASE = "https://printshelf.app";

const el = (id) => document.getElementById(id);
const feedback = (msg, kind = "info") => {
  const node = el("ps-feedback");
  node.textContent = msg || "";
  node.dataset.kind = kind;
};

function getConfig() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["apiKey", "apiBase"], (out) =>
      resolve({
        apiKey: out.apiKey || "",
        apiBase: (out.apiBase || DEFAULT_API_BASE).replace(/\/+$/, ""),
      })
    );
  });
}

function setStatusPill(state, label) {
  const pill = el("ps-status-pill");
  pill.className = `ps-status-pill ps-status-${state}`;
  pill.textContent = label;
}

function flashSaveButton(text = "✓ Saved", revertAfter = 1800) {
  const btn = el("ps-save");
  if (!btn) return;
  const original = btn.dataset.originalLabel || btn.textContent;
  btn.dataset.originalLabel = original;
  btn.classList.add("ps-btn-flash");
  btn.textContent = text;
  clearTimeout(btn._flashT);
  btn._flashT = setTimeout(() => {
    btn.classList.remove("ps-btn-flash");
    btn.textContent = original;
  }, revertAfter);
}

async function refreshStatusFromStorage() {
  const { apiKey, apiBase } = await getConfig();
  el("ps-dashboard-link").href = `${apiBase}/dashboard#api-key`;
  const input = el("ps-api-key");
  if (!apiKey) {
    setStatusPill("unset", "No key");
    input.placeholder = "Paste your PrintShelf API key";
    return;
  }
  setStatusPill("set", "Key saved");
  input.placeholder = "(saved — paste again to replace)";
}

async function testConnection({ silent = false } = {}) {
  const { apiKey, apiBase } = await getConfig();
  if (!apiKey) {
    if (!silent) feedback("Save a key first.", "error");
    return { ok: false };
  }
  if (!silent) feedback("Testing connection…", "info");
  try {
    const res = await fetch(`${apiBase}/api/auth/me`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    if (res.ok) {
      const me = await res.json();
      const who = me.username || me.email || "you";
      feedback(`✓ Connected as ${who}.`, "success");
      setStatusPill("set", "Connected");
      return { ok: true, me };
    }
    if (res.status === 401) {
      feedback("Key rejected. Re-copy it from your dashboard.", "error");
      setStatusPill("error", "Invalid");
      return { ok: false, status: 401 };
    }
    feedback(`Server returned ${res.status}.`, "error");
    return { ok: false, status: res.status };
  } catch (e) {
    feedback(`Network error: ${e.message || e}`, "error");
    return { ok: false, error: e };
  }
}

async function saveKey() {
  const input = el("ps-api-key");
  const apiKey = input.value.trim();
  if (!apiKey) {
    feedback("Paste a key first.", "error");
    input.focus();
    return;
  }
  await new Promise((r) => chrome.storage.sync.set({ apiKey }, r));
  input.value = "";
  flashSaveButton("✓ Saved");
  setStatusPill("set", "Saving…");
  feedback("Saved. Verifying with PrintShelf…", "success");
  // Chain into a live verification so the user sees a concrete confirmation.
  await testConnection({ silent: true });
  refreshStatusFromStorage();
}

function setVersionFooter() {
  const node = el("ps-version");
  if (!node) return;
  try {
    const v = chrome.runtime.getManifest().version;
    node.textContent = `v${v}`;
  } catch {
    node.textContent = "";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  setVersionFooter();
  refreshStatusFromStorage();
  el("ps-save").addEventListener("click", saveKey);
  el("ps-test").addEventListener("click", () => testConnection());
  el("ps-options").addEventListener("click", () => chrome.runtime.openOptionsPage());
  el("ps-api-key").addEventListener("keydown", (e) => {
    if (e.key === "Enter") saveKey();
  });
});
