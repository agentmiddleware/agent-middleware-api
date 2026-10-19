const issueButton = document.getElementById("get-demo-key");
const copyButton = document.getElementById("copy-demo-key");
const status = document.getElementById("demo-key-status");
const result = document.getElementById("demo-key-result");
const keyInput = document.getElementById("demo-api-key");
const walletId = document.getElementById("demo-wallet-id");
const budgetCredits = document.getElementById("demo-budget-credits");
const commands = document.getElementById("demo-commands");
const commandTemplate = commands.textContent;

const UTM_PARAMS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"];
const UTM_STORAGE_KEY = "amwDemoKeyUtm";

function shellQuote(value) {
  return "'" + value.replace(/'/g, "'\"'\"'") + "'";
}

function readStoredUtm() {
  try {
    const raw = sessionStorage.getItem(UTM_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    const stored = {};
    for (const key of UTM_PARAMS) {
      const value = parsed[key];
      if (typeof value === "string" && value.trim()) stored[key] = value.trim();
    }
    return stored;
  } catch {
    return {};
  }
}

function utmFromLocation() {
  const params = new URLSearchParams(location.search || "");
  const found = {};
  for (const key of UTM_PARAMS) {
    const value = params.get(key);
    if (typeof value === "string" && value.trim()) found[key] = value.trim();
  }
  return found;
}

function mergedUtm() {
  // URL values override the same key already stored; absent URL params do not clear it.
  return { ...readStoredUtm(), ...utmFromLocation() };
}

function persistUtm(utm) {
  if (Object.keys(utm).length === 0) return;
  try {
    sessionStorage.setItem(UTM_STORAGE_KEY, JSON.stringify(utm));
  } catch {
    // Storage can be blocked; the request still sends this page's values.
  }
}

function attributionPayload() {
  const utm = mergedUtm();
  persistUtm(utm);
  const payload = { ...utm };
  const referrer = typeof document.referrer === "string" ? document.referrer.trim() : "";
  if (referrer) payload.referrer = referrer;
  return payload;
}

persistUtm(mergedUtm());

issueButton.addEventListener("click", async () => {
  issueButton.disabled = true;
  status.textContent = "Requesting a demo key…";

  const attribution = attributionPayload();
  const request = {
    method: "POST",
    credentials: "omit",
  };
  if (Object.keys(attribution).length > 0) {
    request.headers = { "Content-Type": "application/json" };
    request.body = JSON.stringify(attribution);
  }

  let response;
  try {
    response = await fetch("https://api.thisisatest.tech/v1/demo/keys", request);
  } catch {
    status.textContent = "Could not reach the demo API. Check your connection and try again.";
    issueButton.disabled = false;
    return;
  }

  if (response.status !== 201) {
    const messages = {
      403: "This page is not allowed to issue demo keys right now. Try the curl fallback below.",
      404: "The demo is off right now. Please try again later.",
      429: "Demo key requests are rate limited. Please try again later.",
      503: "Demo key issuance is temporarily unavailable. Please try again later.",
    };
    status.textContent = messages[response.status] || "Could not issue a demo key. Please try again later.";
    issueButton.disabled = false;
    return;
  }

  let data;
  try {
    data = await response.json();
  } catch {
    status.textContent = "The demo API returned an unreadable response. Please try again later.";
    issueButton.disabled = false;
    return;
  }
  if (
    !data ||
    typeof data.api_key !== "string" || !data.api_key ||
    typeof data.wallet_id !== "string" || !data.wallet_id ||
    !["number", "string"].includes(typeof data.budget_credits)
  ) {
    status.textContent = "The demo API did not return a usable key. Please try again later.";
    issueButton.disabled = false;
    return;
  }

  keyInput.value = data.api_key;
  walletId.textContent = data.wallet_id;
  budgetCredits.textContent = String(data.budget_credits);
  commands.textContent = commandTemplate
    .replace("KEY='YOUR_DEMO_KEY'", `KEY=${shellQuote(data.api_key)}`)
    .replace("WALLET='YOUR_WALLET_ID'", `WALLET=${shellQuote(data.wallet_id)}`);
  result.hidden = false;
  status.textContent = "Demo key ready. Copy and store it now.";
});

copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(keyInput.value);
    status.textContent = "Demo key copied.";
  } catch {
    keyInput.focus();
    keyInput.select();
    status.textContent = "Copy was unavailable. The key is selected so you can copy it manually.";
  }
});
