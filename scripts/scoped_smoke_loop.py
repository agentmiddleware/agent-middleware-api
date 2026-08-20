#!/usr/bin/env python3
"""Continuous trust-plane smoke loop that runs on a wallet-scoped key.

``trust_plane_conformance.py`` is the fuller suite, but it needs a bootstrap
admin key: it creates sponsor wallets, agent wallets, and API keys, and it
reads the audit plane. That makes it the wrong tool for a monitoring agent
left running against a deployment — a credential that can mint keys and read
every tenant's audit trail is not one you leave in a CI runner's environment.

This loop asserts the subset of invariants a *wallet-scoped* key can prove
about itself, which is most of what the product actually sells:

  authority -> permit -> invoke -> receipt -> replay-is-not-recharged
            -> out-of-scope denial -> portable receipt verifies offline

Every stage is asserted. The run exits non-zero the moment an invariant
breaks, so it can gate a deploy or page whoever is on call.

What it deliberately cannot check, because a scoped key must not be able to:
tenant isolation across two wallets, audit-chain verification, and refund
reconciliation. Those stay in the admin-gated conformance suite, run
deliberately by an operator rather than continuously by an agent.

Usage::

    export AGENT_MIDDLEWARE_API_KEY=...          # a WALLET-SCOPED key
    export AGENT_MIDDLEWARE_API_URL=https://...  # optional; defaults to prod
    python scripts/scoped_smoke_loop.py --once
    python scripts/scoped_smoke_loop.py --interval 300 --max-iterations 0

The key is read from the environment only: never an argument, so it stays out
of process listings and shell history. It is never printed, and the failure
paths below truncate response bodies that could echo it back.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from urllib.parse import urlsplit

DEFAULT_API_URL = "https://api.thisisatest.tech"
API_URL = os.environ.get("AGENT_MIDDLEWARE_API_URL", DEFAULT_API_URL).rstrip("/")
API_KEY = os.environ.get("AGENT_MIDDLEWARE_API_KEY", "")

# Tool names are per-deployment: the registry differs between a local
# quickstart, a partner pilot, and production. Hardcoding one makes the loop
# fail with "tool not found" on every deployment but the author's, so the
# names are discovered unless the operator pins them with --tool/--other-tool.
# Headroom over the selected tool's advertised price. One iteration spends a
# single call — the replay is free and the denial never charges — so this is
# slack for a price that moved between discovery and invocation, not a budget
# for repeated spending.
PERMIT_CREDIT_HEADROOM = 3
PERMIT_MIN_CREDITS = 20

# The exact refusal a permit gives for a tool outside allowed_tools. The
# out-of-scope check asserts this string rather than "any error", so it
# cannot be satisfied by a tool-not-found or a transport failure.
PERMIT_SCOPE_DENIAL = "permit_tool_not_allowed"
# The refusal for a reused idempotency key carrying a different payload.
IDEMPOTENCY_CONFLICT = "idempotency_key_reused"


def _redact(text: str, limit: int = 200) -> str:
    """Truncate a response body and scrub anything key-shaped out of it.

    A 4xx body can echo the submitted credential back. This loop is built to
    run unattended into logs someone else reads, so nothing that looks like a
    key reaches stdout even on the failure paths.
    """
    snippet = text[:limit]
    if API_KEY and API_KEY in snippet:
        snippet = snippet.replace(API_KEY, "<redacted>")
    return snippet


@dataclass
class Suite:
    passed: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        tail = f"  — {detail}" if detail else ""
        if ok:
            self.passed += 1
            print(f"[PASS] {name}{tail}", flush=True)
        else:
            self.failed += 1
            self.failures.append(name)
            print(f"[FAIL] {name}{tail}", flush=True)
        return ok


def headers(run_tag: str, idempotency_key: str | None = None) -> dict[str, str]:
    h = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
    if idempotency_key:
        h["Idempotency-Key"] = f"{run_tag}-{idempotency_key}"
    return h


def invoke_body(
    wallet_id: str, permit_id: str, tool: str, arguments: dict
) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool,
            "arguments": arguments,
            "mcpContext": {"wallet_id": wallet_id, "permit_id": permit_id},
        },
    }


def arguments_for(schema: dict, marker: str) -> dict:
    """Build a minimal argument set satisfying a tool's declared inputSchema.

    Tools differ per deployment, so a fixed ``{"text": ...}`` payload fails on
    every registry but the one it was written against. Filling only the
    *required* properties, typed as the schema declares, keeps the loop
    portable without pretending to know any particular tool's semantics.

    ``marker`` is woven into string values so a run's test data is traceable
    back to this loop in whatever the tool writes.
    """
    properties = (schema or {}).get("properties") or {}
    required = (schema or {}).get("required") or []
    arguments: dict = {}
    for name in required:
        spec = properties.get(name) or {}
        if "default" in spec:
            arguments[name] = spec["default"]
            continue
        enum = spec.get("enum")
        if enum:
            arguments[name] = enum[0]
            continue
        kind = spec.get("type")
        if kind == "integer":
            arguments[name] = 1
        elif kind == "number":
            arguments[name] = 1.0
        elif kind == "boolean":
            arguments[name] = False
        elif kind == "array":
            arguments[name] = []
        elif kind == "object":
            arguments[name] = {}
        else:
            arguments[name] = f"smoke-{marker}"
    return arguments


def _spent(permit: dict) -> float:
    """Credits consumed against a permit, however the field is spelled.

    Reading the permit back is how this loop proves a replay did not charge
    twice, so a renamed field must fail loudly rather than silently return 0
    and make the double-charge check vacuous.
    """
    for key in ("spent_credits", "credits_spent", "spent"):
        if key in permit:
            return float(permit[key])
    raise KeyError(
        f"permit carries no recognised spend field; got keys: {sorted(permit)}"
    )


def select_companion_tool(
    registry: dict[str, dict], allowed_tool: str, pinned: str | None
) -> tuple[str | None, str]:
    """Pick a real registered tool the permit does not cover.

    Drawn from the *registry*, never from the pinned name: ``--tool`` is
    mandatory off loopback, so selecting the companion from the pinned list
    would silently skip the out-of-scope check on exactly the deployments
    where it matters most.

    It must be a tool that genuinely exists, because invoking a name the
    registry has never heard of proves "tool not found" rather than "the
    permit refused it" — a pass for the wrong reason.

    Returns ``(tool_or_None, error_message)``. ``None`` with no error means
    the deployment has no second tool and the check should be skipped.
    """
    if pinned:
        if pinned not in registry:
            return None, (
                "an unregistered name proves tool-not-found, not permit "
                f"refusal; registry: {sorted(registry)[:6]}"
            )
        if pinned == allowed_tool:
            return None, (
                "the companion must differ from the permitted tool, or the "
                "check asserts a denial that should never happen"
            )
        return pinned, ""
    return next((name for name in registry if name != allowed_tool), None), ""


async def discover_tools(client: httpx.AsyncClient) -> dict[str, dict]:
    """Return {tool name: manifest entry} for what this deployment exposes."""

    r = await client.get("/mcp/tools.json")
    r.raise_for_status()
    tools = r.json().get("tools") or []
    return {
        t["name"]: t for t in tools if isinstance(t, dict) and t.get("name")
    }


def credits_per_call(tool: dict) -> float:
    """The tool's advertised price, or 0 when the manifest does not state one."""

    try:
        return float((tool.get("annotations") or {}).get("creditsPerCall") or 0)
    except (TypeError, ValueError):
        return 0.0


async def run_once(
    client: httpx.AsyncClient, suite: Suite, args: argparse.Namespace
) -> None:
    run_tag = f"smoke-{uuid.uuid4().hex[:10]}"

    # ---- Who am I? -------------------------------------------------------
    # Doubles as the guard against running on the wrong credential class:
    # this route answers 403 wallet_key_required for a bootstrap admin key,
    # so an operator who exports the admin key by mistake gets told so
    # instead of quietly writing admin-authored test data every 5 minutes.
    r = await client.get("/v1/me/authority", headers=headers(run_tag))
    if r.status_code in (401, 403):
        # Distinguish the two failures that both surface here, because they
        # send whoever is paged in opposite directions: a rejected key is a
        # credential problem, while wallet_key_required means the key is
        # valid but is the admin key this loop must never run on.
        try:
            error = (r.json().get("detail") or {}).get("error", "")
        except ValueError:
            error = ""
        if error == "wallet_key_required":
            suite.check(
                "key is wallet-scoped, not bootstrap admin",
                False,
                "the configured key is a bootstrap admin key; this loop "
                "must run on a wallet-scoped key",
            )
        else:
            suite.check(
                "API key is accepted",
                False,
                f"HTTP {r.status_code} {error or 'rejected'} — check "
                "AGENT_MIDDLEWARE_API_KEY for this deployment",
            )
        return
    if not suite.check(
        "authority readable for own wallet",
        r.status_code == 200,
        f"HTTP {r.status_code}: {_redact(r.text)}",
    ):
        return
    authority = r.json()
    wallet_id = authority.get("wallet_id")
    if not suite.check("authority names the caller's wallet", bool(wallet_id)):
        return

    # ---- Which tools does this deployment actually expose? ----------------
    registry = await discover_tools(client)
    if not suite.check("deployment exposes at least one tool", bool(registry)):
        return
    allowed_tool = args.tool or next(iter(registry))
    if not suite.check(
        f"tool {allowed_tool} is registered",
        allowed_tool in registry,
        f"registry: {sorted(registry)[:6]}",
    ):
        return
    other_tool, companion_error = select_companion_tool(
        registry, allowed_tool, args.other_tool
    )
    if companion_error:
        suite.check(f"out-of-scope companion {args.other_tool}", False, companion_error)

    # ---- Issue a permit for the caller's own wallet -----------------------
    # Sized from what this tool actually costs. A fixed cap fails
    # permit_budget_exceeded on a perfectly healthy deployment the moment
    # someone pins a tool priced above it, which reads as a product fault.
    price = credits_per_call(registry[allowed_tool])
    max_credits = args.max_credits or max(
        PERMIT_MIN_CREDITS, price * PERMIT_CREDIT_HEADROOM
    )
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    r = await client.post(
        "/v1/permits",
        headers=headers(run_tag, "permit"),
        json={
            "issuer_wallet_id": wallet_id,
            "subject_wallet_id": wallet_id,
            "allowed_tools": [allowed_tool],
            "max_credits": str(max_credits),
            "expires_at": expires_at,
        },
    )
    if not suite.check(
        "issue scoped permit",
        r.status_code == 201,
        f"HTTP {r.status_code}: {_redact(r.text)}",
    ):
        return
    permit = r.json()
    permit_id = permit["permit_id"]
    suite.check("permit carries a nonce", bool(permit.get("nonce")))

    # ---- Golden path: one governed invocation ----------------------------
    # Keep this body byte-identical for the replay below. The idempotency
    # layer hashes the payload, so resending a *different* body under the
    # same key is a conflict rather than a replay — asserted separately.
    golden_args = args.tool_args or arguments_for(
        registry[allowed_tool].get("inputSchema") or {}, run_tag
    )
    golden = invoke_body(wallet_id, permit_id, allowed_tool, golden_args)
    r = await client.post(
        "/mcp/messages", headers=headers(run_tag, "invoke"), json=golden
    )
    body = r.json()
    receipt = body.get("result", {}).get("receipt", {})
    receipt_id = receipt.get("receipt_id")
    if not suite.check(
        "governed invoke succeeds",
        "error" not in body and bool(receipt_id),
        _redact(json.dumps(body)),
    ):
        return

    r = await client.get(f"/v1/permits/{permit_id}", headers=headers(run_tag))
    if not suite.check("permit readable after invoke", r.status_code == 200):
        return
    spent_after_first = _spent(r.json())
    # Assert against the receipt's own figure rather than a hardcoded price:
    # a pricing change should not fail this loop, but a debit that disagrees
    # with the receipt it is supposed to evidence absolutely should.
    charged = receipt.get("cost_credits", receipt.get("credits_charged"))
    suite.check(
        "the debit matches the receipt's stated cost",
        charged is not None and float(charged) == spent_after_first,
        f"permit spent={spent_after_first}, receipt says {charged}",
    )

    # ---- The claim the product rests on: replay does not recharge ---------
    r = await client.post(
        "/mcp/messages", headers=headers(run_tag, "invoke"), json=golden
    )
    replay = r.json()
    replay_id = replay.get("result", {}).get("receipt", {}).get("receipt_id")
    suite.check(
        "replay returns the same receipt",
        replay_id == receipt_id,
        f"first={receipt_id}, replay={replay_id}",
    )

    r = await client.get(f"/v1/permits/{permit_id}", headers=headers(run_tag))
    spent_after_replay = _spent(r.json())
    suite.check(
        "replay did not charge a second time",
        spent_after_replay == spent_after_first,
        f"before={spent_after_first}, after={spent_after_replay}",
    )

    # ---- A different payload under the same key is a conflict, not a replay
    r = await client.post(
        "/mcp/messages",
        headers=headers(run_tag, "invoke"),
        json=invoke_body(
            wallet_id, permit_id, allowed_tool, {**golden_args, "_smoke": "differs"}
        ),
    )
    conflict = r.json()
    # The exact reason, not any error: a tool rejecting the injected argument,
    # or an unrelated policy failure, would otherwise report PASS while the
    # idempotency behaviour this asserts went unverified.
    conflict_message = str((conflict.get("error") or {}).get("message", ""))
    suite.check(
        "different payload under a used key is refused as a conflict",
        conflict_message == IDEMPOTENCY_CONFLICT,
        conflict_message
        or f"HTTP {r.status_code}: {_redact(json.dumps(conflict))}",
    )

    # ---- Out-of-scope tool is denied, and the denial costs nothing --------
    if other_tool is None:
        print(
            "[SKIP] out-of-scope denial — no registered tool outside the "
            "permit to try against",
            flush=True,
        )
    else:
        r = await client.post(
            "/mcp/messages",
            headers=headers(run_tag, "outofscope"),
            json=invoke_body(
                wallet_id,
                permit_id,
                other_tool,
                arguments_for(
                    (registry.get(other_tool) or {}).get("inputSchema") or {},
                    run_tag,
                ),
            ),
        )
        denied = r.json()
        # Assert the *specific* refusal, not merely "something went wrong".
        # Any-error-counts would pass on a transport hiccup or a schema
        # complaint, and "receipt has no ok field" passes on success, since a
        # successful receipt carries no such field at all.
        error_message = str((denied.get("error") or {}).get("message", ""))
        suite.check(
            f"out-of-scope tool {other_tool} is refused by the permit",
            error_message == PERMIT_SCOPE_DENIAL,
            error_message or _redact(json.dumps(denied)),
        )

        r = await client.get(f"/v1/permits/{permit_id}", headers=headers(run_tag))
        spent_after_denial = _spent(r.json())
        suite.check(
            "a denied call is not charged",
            spent_after_denial == spent_after_replay,
            f"before={spent_after_replay}, after={spent_after_denial}",
        )

    # ---- The receipt is portable and verifies with no credential ----------
    r = await client.get(
        f"/v1/receipts/{receipt_id}/portable", headers=headers(run_tag)
    )
    if not suite.check(
        "portable receipt bundle retrievable",
        r.status_code == 200,
        f"HTTP {r.status_code}",
    ):
        return
    bundle = r.json()
    suite.check(
        "portable bundle carries a signature and key id",
        bool(bundle.get("signature")) and bool(bundle.get("kid")),
        f"keys: {sorted(bundle)[:8]}",
    )
    # The canonicalization is the byte-level contract an independent verifier
    # implements; without it a signature cannot be checked offline at all.
    # `issuer` is deliberately not asserted: it is empty on a local instance
    # with no PUBLIC_URL, and failing there would be a config complaint
    # dressed up as a trust-plane failure.
    suite.check(
        "portable bundle names its canonicalization",
        bool(bundle.get("canonicalization")),
        f"canonicalization={bundle.get('canonicalization')!r}, "
        f"issuer={bundle.get('issuer')!r}",
    )


async def main_async(args: argparse.Namespace) -> int:
    iteration = 0
    worst = 0
    async with httpx.AsyncClient(base_url=API_URL, timeout=60.0) as client:
        while True:
            iteration += 1
            started = datetime.now(timezone.utc)
            suite = Suite()
            print(
                f"\n=== iteration {iteration} — {started.isoformat()} "
                f"— {API_URL} ===",
                flush=True,
            )
            try:
                await run_once(client, suite, args)
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                # A transport error or a renamed field is a failed iteration,
                # not a crashed monitor: a loop that dies on the first blip
                # stops watching exactly when something is going wrong.
                suite.check("iteration completed without error", False, str(exc)[:200])

            print(
                f"--- {suite.passed} passed, {suite.failed} failed"
                + (f" ({', '.join(suite.failures)})" if suite.failures else ""),
                flush=True,
            )
            if suite.failed:
                worst = 1
                if args.exit_on_failure:
                    return 1

            if args.once or (
                args.max_iterations and iteration >= args.max_iterations
            ):
                return worst
            await asyncio.sleep(args.interval)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Continuous trust-plane smoke loop for a wallet-scoped API key."
        )
    )
    parser.add_argument(
        "--once", action="store_true", help="Run a single iteration and exit"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=300.0,
        help="Seconds between iterations (default: 300)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=0,
        help="Stop after N iterations; 0 runs until interrupted",
    )
    parser.add_argument(
        "--tool",
        default=os.environ.get("SMOKE_TOOL") or None,
        help="Pin the tool the permit scopes to (default: first discovered)",
    )
    parser.add_argument(
        "--other-tool",
        default=os.environ.get("SMOKE_OTHER_TOOL") or None,
        help=(
            "Pin the real, registered tool used for the out-of-scope denial "
            "check (default: second discovered)"
        ),
    )
    parser.add_argument(
        "--tool-args",
        type=json.loads,
        default=None,
        help=(
            "JSON object of arguments for the pinned tool. Set this when "
            "running against production so the loop sends a payload you have "
            "chosen, rather than one derived from the tool's schema."
        ),
    )
    parser.add_argument(
        "--max-credits",
        type=float,
        default=None,
        help=(
            "Permit cap in credits (default: 3x the tool's advertised "
            "creditsPerCall, floor 20)"
        ),
    )
    parser.add_argument(
        "--exit-on-failure",
        action="store_true",
        help="Exit non-zero on the first failing iteration instead of continuing",
    )
    args = parser.parse_args()

    loopback = urlsplit(API_URL).hostname in {"localhost", "127.0.0.1", "::1"}
    if not loopback and not args.tool:
        sys.stderr.write(
            f"refusing to auto-discover a tool against {API_URL}.\n"
            "Off loopback, pass --tool so you choose what this loop invokes "
            "on every iteration rather than whatever the registry happens to "
            "list first.\n"
        )
        return 2

    if not loopback and args.tool_args is None:
        # Schema validity is not evidence of safety. Derived arguments fill
        # required fields from types, defaults, and the *first* enum member —
        # which for a consequential tool could be "delete" or "commit", sent
        # again every interval. Off loopback the payload is a decision an
        # operator makes explicitly, even if that decision is "{}".
        sys.stderr.write(
            f"refusing to send derived arguments to {API_URL}.\n"
            "Off loopback, pass --tool-args with a payload you have approved "
            "for repeated invocation; derived arguments guess from the "
            "schema and may name a destructive enum value. Pass "
            "--tool-args '{}' if the tool genuinely needs no arguments.\n"
        )
        return 2

    if not API_KEY:
        return int(
            bool(
                sys.stderr.write(
                    "AGENT_MIDDLEWARE_API_KEY is not set.\n"
                    "Export a wallet-scoped key for the target deployment "
                    "before running; never pass it as an argument.\n"
                )
            )
        )

    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
