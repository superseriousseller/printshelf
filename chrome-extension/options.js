const DEFAULT_API_BASE = "https://printshelf.app";
const PRESETS = new Set([
  "https://printshelf.app",
  "https://staging.printshelf.app",
  "http://127.0.0.1:8765",
]);

const el = (id) => document.getElementById(id);
const feedback = (msg, kind = "info") => {
  const node = el("ps-feedback");
  node.textContent = msg || "";
  node.dataset.kind = kind;
};

function getConfig() {
  return new Promise((resolve) =>
    chrome.storage.sync.get(["apiKey", "apiBase"], (out) =>
      resolve({
        apiKey: out.apiKey || "",
        apiBase: (out.apiBase || DEFAULT_API_BASE).replace(/\/+$/, ""),
      })
    )
  );
}

function applyPreset(value) {
  const preset = el("ps-api-base-preset");
  const input = el("ps-api-base");
  if (value === "__custom__") {
    input.disabled = false;
    input.focus();
    return;
  }
  input.value = value;
  input.disabled = true;
  preset.value = value;
}

function initPresetFromValue(value) {
  if (PRESETS.has(value)) applyPreset(value);
  else {
    el("ps-api-base-preset").value = "__custom__";
    el("ps-api-base").disabled = false;
    el("ps-api-base").value = value;
  }
}

async function load() {
  const { apiKey, apiBase } = await getConfig();
  el("ps-dashboard-link").href = `${apiBase}/dashboard`;
  el("ps-api-key").value = apiKey ? "" : "";
  el("ps-api-key").placeholder = apiKey ? "(saved — paste again to replace)" : "Paste your PrintShelf API key";
  initPresetFromValue(apiBase);
}

async function save() {
  const apiKey = el("ps-api-key").value.trim();
  const apiBase = el("ps-api-base").value.trim().replace(/\/+$/, "") || DEFAULT_API_BASE;
  const update = { apiBase };
  if (apiKey) update.apiKey = apiKey;
  await new Promise((r) => chrome.storage.sync.set(update, r));
  el("ps-api-key").value = "";
  el("ps-api-key").placeholder = "(saved — paste again to replace)";
  el("ps-dashboard-link").href = `${apiBase}/dashboard`;
  feedback(apiKey ? "Saved key and API base." : "Saved API base.", "success");
}

async function test() {
  const { apiKey, apiBase } = await getConfig();
  const enteredKey = el("ps-api-key").value.trim();
  const key = enteredKey || apiKey;
  const base = (el("ps-api-base").value.trim() || apiBase).replace(/\/+$/, "");
  if (!key) {
    feedback("Paste or save a key first.", "error");
    return;
  }
  feedback("Testing…", "info");
  try {
    const res = await fetch(`${base}/api/auth/me`, {
      headers: { Authorization: `Bearer ${key}` },
    });
    if (res.ok) {
      const me = await res.json();
      feedback(`Connected as ${me.username || me.email || "you"} (${me.tier || "free"}).`, "success");
    } else if (res.status === 401) {
      feedback("Key rejected. Re-copy it from your dashboard.", "error");
    } else {
      feedback(`Server returned ${res.status}.`, "error");
    }
  } catch (e) {
    feedback(`Network error: ${e.message || e}`, "error");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  load();
  el("ps-api-base-preset").addEventListener("change", (e) => applyPreset(e.target.value));
  el("ps-save").addEventListener("click", save);
  el("ps-test").addEventListener("click", test);
});
