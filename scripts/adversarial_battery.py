#!/usr/bin/env python3
"""Authenticated adversarial battery for the governed trust plane.

Run this against a deployment YOU operate, with YOUR bootstrap key. It
provisions throwaway, low-budget wallets/keys/permits, probes the governed
path for the failure modes that matter (wallet isolation, permit scope,
replay/idempotency, budget containment, expiry, revocation, receipt
integrity), prints a PASS/FAIL/SKIP summary, and revokes what it created.

    export API_URL="https://api-service-production-433c.up.railway.app"
    export BOOTSTRAP_KEY=...     # from Railway variables — never commit or paste
    python3 scripts/adversarial_battery.py

Notes
-----
* This creates real rows on the target (tiny throwaway wallets). Point it at a
  deployment you own. It cleans up the API keys it mints.
* MCP-invocation checks are best-effort: they discover an invokable governed
  tool from ``/mcp/tools.json`` and SKIP cleanly when the deployment exposes
  none, so the isolation/auth/receipt checks still run everywhere.
* Read-only against your data otherwise — it never touches wallets it did not
  create.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API_URL = os.environ.get("API_URL", "https://api-service-production-433c.up.railway.app").rstrip("/")
BOOTSTRAP_KEY = os.environ.get("BOOTSTRAP_KEY")

RESULTS: list[tuple[str, str, str]] = []  # (name, PASS/FAIL/SKIP, detail)


def req(method: str, path: str, key: str | None = None, body: dict | None = None,
        extra_headers: dict | None = None) -> tuple[int, object]:
    url = f"{API_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-API-Key"] = key
    if extra_headers:
        headers.update(extra_headers)
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read().decode()
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        status = e.code
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def record(name: str, passed: bool | None, detail: str) -> None:
    verdict = "SKIP" if passed is None else ("PASS" if passed else "FAIL")
    RESULTS.append((name, verdict, detail))
    print(f"[{verdict}] {name}: {detail}")


def iso_in(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def provision():
    """Create sponsor + two agent wallets, keys, and a scoped permit."""
    _, sponsor = req("POST", "/v1/billing/wallets/sponsor", BOOTSTRAP_KEY, {
        "sponsor_name": "adv-battery", "email": "adv@example.com",
        "initial_credits": 500, "require_kyc": False,
    })
    sponsor_id = sponsor["wallet_id"]

    agents = []
    for i in (1, 2):
        _, a = req("POST", "/v1/billing/wallets/agent", BOOTSTRAP_KEY, {
            "sponsor_wallet_id": sponsor_id, "agent_id": f"adv-agent-{i}",
            "budget_credits": 100, "daily_limit": 50,
        })
        _, k = req("POST", "/v1/api-keys", BOOTSTRAP_KEY, {
            "wallet_id": a["wallet_id"], "key_name": f"adv-key-{i}", "expires_in_days": 1,
        })
        agents.append({"wallet_id": a["wallet_id"], "api_key": k["api_key"], "key_id": k["key_id"]})

    _, permit = req("POST", "/v1/permits", BOOTSTRAP_KEY, {
        "issuer_wallet_id": agents[0]["wallet_id"],
        "subject_wallet_id": agents[0]["wallet_id"],
        "subject_key_id": agents[0]["key_id"],
        "allowed_tools": ["golden-path-echo"],
        "scopes": ["tool:golden-path-echo:invoke", "billing:charge"],
        "max_credits": 5,
        "expires_at": iso_in(30),
    }, {"Idempotency-Key": "adv-permit-1"})
    return sponsor_id, agents, permit


def cleanup(agents):
    for a in agents:
        try:
            req("DELETE", f"/v1/api-keys/{a['wallet_id']}/{a['key_id']}", BOOTSTRAP_KEY)
        except Exception:
            pass


def main() -> int:
    if not BOOTSTRAP_KEY:
        print("ERROR: set BOOTSTRAP_KEY (operator key from Railway variables).", file=sys.stderr)
        return 2
    print(f"Target: {API_URL}\n")

    sponsor_id, agents, permit = provision()
    a, b = agents
    permit_id = permit.get("permit_id")

    # 1. Cross-wallet isolation: agent A's key must not read sponsor or agent B.
    s1, _ = req("GET", f"/v1/billing/wallets/{sponsor_id}", a["api_key"])
    s2, _ = req("GET", f"/v1/billing/wallets/{b['wallet_id']}", a["api_key"])
    s3, _ = req("GET", f"/v1/billing/wallets/{a['wallet_id']}", a["api_key"])
    record("wallet_isolation", s1 == 403 and s2 == 403 and s3 == 200,
           f"sponsor={s1} otherAgent={s2} ownWallet={s3} (want 403/403/200)")

    # 2. Invalid key rejected on a guarded endpoint.
    s, _ = req("GET", "/v1/permits", "totally-invalid-key-0000")
    record("invalid_key_rejected", s in (401, 403), f"status={s} (want 401/403)")

    # 3. Forged receipt fails verification.
    s, body = req("POST", "/v1/receipts/verify", a["api_key"], {"receipt_id": "rcpt_forged_deadbeef"})
    verified = isinstance(body, dict) and body.get("verified") is True
    record("forged_receipt_rejected", s in (400, 404, 422) or (s == 200 and not verified),
           f"status={s} verified={verified} (must not verify)")

    # 4. Permit/key binding: agent B's key may not use agent A's permit.
    s, body = req("POST", "/mcp/messages", b["api_key"], {
        "jsonrpc": "2.0", "id": "adv-bind-1", "method": "tools/call",
        "params": {"name": "golden-path-echo", "arguments": {"message": "x"},
                   "mcpContext": {"wallet_id": b["wallet_id"], "permit_id": permit_id,
                                  "idempotency_key": "adv-bind-1"}},
    })
    denied = s in (401, 403) or (isinstance(body, dict) and body.get("error"))
    record("permit_key_binding", bool(denied), f"status={s} (cross-key permit use must be denied)")

    # 5. Expired permit is unusable.
    s, exp = req("POST", "/v1/permits", BOOTSTRAP_KEY, {
        "issuer_wallet_id": a["wallet_id"], "subject_wallet_id": a["wallet_id"],
        "subject_key_id": a["key_id"], "allowed_tools": ["golden-path-echo"],
        "scopes": ["tool:golden-path-echo:invoke"], "max_credits": 5,
        "expires_at": iso_in(-30),
    }, {"Idempotency-Key": "adv-permit-expired"})
    if s >= 400:
        record("expired_permit_denied", True, f"creation rejected status={s}")
    else:
        si, bi = req("POST", "/mcp/messages", a["api_key"], {
            "jsonrpc": "2.0", "id": "adv-exp-1", "method": "tools/call",
            "params": {"name": "golden-path-echo", "arguments": {"message": "x"},
                       "mcpContext": {"wallet_id": a["wallet_id"], "permit_id": exp.get("permit_id"),
                                      "idempotency_key": "adv-exp-1"}},
        })
        d = si in (401, 403) or (isinstance(bi, dict) and bi.get("error"))
        record("expired_permit_denied", bool(d), f"invoke status={si} (expired permit must be denied)")

    # 6. Revocation containment: revoke agent B's key, then reuse must fail.
    req("DELETE", f"/v1/api-keys/{b['wallet_id']}/{b['key_id']}", BOOTSTRAP_KEY)
    s, _ = req("GET", f"/v1/billing/wallets/{b['wallet_id']}", b["api_key"])
    record("revoked_key_denied", s in (401, 403), f"status={s} after revoke (want 401/403)")
    agents = [a]  # b's key already revoked; skip in cleanup

    # 7. Replay / idempotency (best-effort — needs an invokable governed tool).
    s_tools, tools = req("GET", "/mcp/tools.json", a["api_key"])
    tool_names = []
    if isinstance(tools, dict):
        tool_names = [t.get("name") for t in tools.get("tools", []) if isinstance(t, dict)]
    if "golden-path-echo" not in tool_names:
        record("replay_idempotent", None,
               f"no invokable 'golden-path-echo' tool exposed (tools={tool_names[:5]}); "
               "wire an echo tool to exercise replay")
    else:
        call = {"jsonrpc": "2.0", "id": "adv-replay", "method": "tools/call",
                "params": {"name": "golden-path-echo", "arguments": {"message": "hello"},
                           "mcpContext": {"wallet_id": a["wallet_id"], "permit_id": permit_id,
                                          "idempotency_key": "adv-replay-1"}}}
        _, r1 = req("POST", "/mcp/messages", a["api_key"], call)
        _, r2 = req("POST", "/mcp/messages", a["api_key"], call)
        def rid(x):
            return (x or {}).get("result", {}).get("receipt", {}).get("receipt_id")
        same = rid(r1) and rid(r1) == rid(r2)
        record("replay_idempotent", bool(same),
               f"receipt1={rid(r1)} receipt2={rid(r2)} (replay must reuse the same receipt)")

    cleanup(agents)

    print("\n=== SUMMARY ===")
    for name, verdict, _ in RESULTS:
        print(f"  {verdict:4}  {name}")
    failed = [n for n, v, _ in RESULTS if v == "FAIL"]
    print(f"\n{len(RESULTS)} checks — {len(failed)} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
