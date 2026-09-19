"""Test 12 -- Redis / cache failure."""

from __future__ import annotations

import socket
from decimal import Decimal
from typing import Any

from failure_lab.configurations import (
    GATEWAY_CONFIGURATIONS,
    AttemptOutcome,
    Configuration,
    Target,
)
from failure_lab.gateway import GATEWAY_TOOL_ID
from failure_lab.identity import OperationIdentity
from failure_lab.scenarios.base import (
    REFUSED_STATUSES,
    ConfigurationResult,
    EventLog,
    Scenario,
    Verdict,
)

#: The unauthenticated operator surface that publishes dependency truth. It is
#: not in the rate limiter's skip list, so reading it also exercises the
#: limiter against whatever cache is configured.
HEALTH_PATH = "/health/dependencies"

#: A tool id the gateway does not serve. A permit whose only allowed tool is
#: this one turns the governed refund call into an out-of-scope destination.
UNPERMITTED_TOOL = "lab.t12.unpermitted.tool"

#: Refund amount, in minor units, used by every call here.
PROBE_AMOUNT = 5000

#: Client patience. Nothing here is expected to be slow; this only keeps the
#: harness from being the thing that times out.
SUBMIT_TIMEOUT_SECONDS = 30.0


def _closed_loopback_url() -> str:
    """A ``redis://`` URL naming a loopback port with nothing listening on it."""
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    finally:
        probe.close()
    return f"redis://127.0.0.1:{port}/0"


def _added(
    before: list[dict[str, Any]], after: list[dict[str, Any]], key: str
) -> list[dict[str, Any]]:
    """Rows in ``after`` that were not in ``before``, matched on ``key``."""
    seen = {row[key] for row in before}
    return [row for row in after if row[key] not in seen]


def _credits(rows: list[dict[str, Any]]) -> Decimal:
    """Signed credit total of a set of ledger rows (debits are negative)."""
    total = Decimal("0")
    for row in rows:
        amount = row.get("amount")
        if amount is not None:
            total += Decimal(str(amount))
    return total


def _credit_text(value: Decimal) -> str:
    """Render a credit total without exponent or signed-zero noise."""
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _live_rate_limiters(app: Any, middleware_class: Any) -> list[Any]:
    """The rate-limiter instances inside an already-built middleware stack.

    Starlette builds the stack lazily on the first request, so this is only
    non-empty once something has been served. The instances matter because
    ``RateLimitMiddleware`` copies ``REDIS_URL`` into instance state when it is
    constructed: changing the cached settings object afterwards does not reach
    a limiter that is already running. That is measured here, not assumed.
    """
    found: list[Any] = []
    node = getattr(app, "middleware_stack", None)
    depth = 0
    while node is not None and depth < 64:
        depth += 1
        if isinstance(node, middleware_class):
            found.append(node)
        node = getattr(node, "app", None)
    return found


def _dig(document: Any, *path: str) -> Any:
    current = document
    for step in path:
        if not isinstance(current, dict):
            return None
        current = current.get(step)
    return current


def _health_summary(document: Any) -> dict[str, Any]:
    """The part of the dependency report this scenario is asking about."""
    if not isinstance(document, dict):
        return {"unreadable": str(document)[:200]}
    return {
        "status": document.get("status"),
        "unhealthy": document.get("unhealthy"),
        "environment": document.get("environment"),
        "production_like": document.get("production_like"),
        "redis": _dig(document, "dependencies", "redis"),
        "runtime_degradation": document.get("runtime_degradation"),
    }


class CacheFailure(Scenario):
    """If the cache participates in enforcement, kill it and see what degrades.

    WHAT TO IMPLEMENT
    -----------------
    1. Establish whether the cache is in the correctness path at all, by
       measurement rather than by reading the source. Point ``REDIS_URL`` at a
       closed loopback port (``app.core.config.get_settings()`` is cached --
       mutate the settings object and, where the rate limiter holds its own
       module-level ``settings``, patch ``app.core.rate_limiter.settings``
       too; restore both in a ``finally``).
    2. With the cache unreachable, drive the full governed loop: one clean
       call, one replay of the same key, one out-of-scope denial. Assert the
       correctness invariants are untouched -- one downstream execution, one
       debit, one receipt, the replay returning the same receipt id, and the
       denial still denied.
    3. Assert the degradation is SURFACED rather than silent: read
       ``GET /health/dependencies`` (and
       ``app.core.runtime_degradation``) and record whether the run reports a
       memory fallback. Correctness-critical state must not silently degrade
       into unsafe behaviour; a limiter that quietly falls back is acceptable
       only if it says so.
    4. Record in ``extra["participates_in_enforcement"]`` whether any
       correctness invariant changed with the cache down, and in
       ``extra["degradation_surfaced"]`` whether the runtime reported it.
    5. Verdict: ``PASS`` iff no correctness invariant changed AND the
       degradation was surfaced. ``FAIL`` if a correctness invariant changed
       with the cache down, or if the fallback happened silently.
    6. In the observation, state plainly which components use the cache in
       this configuration (rate limiting and optional durable state) and that
       the permit, idempotency, dispatch, debit and receipt path is backed by
       the relational database alone -- as demonstrated by the run, not
       asserted from the source.
    """

    test_id = "T12"
    title = "Cache failure"
    claim = (
        "Correctness does not depend on the cache, and a cache outage "
        "degrades loudly rather than silently."
    )
    tier = "fast"
    configurations = GATEWAY_CONFIGURATIONS
    inapplicable_reason = "a direct integration has no gateway cache in the path"
    expected = {
        Configuration.DIRECT_NAIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.DIRECT_NATIVE.value: Verdict.NOT_APPLICABLE.value,
        Configuration.GATEWAY_NATIVE.value: Verdict.PASS.value,
        Configuration.GATEWAY_NAIVE.value: Verdict.PASS.value,
    }
    limitations = (
        "Exercises an unreachable cache in a local-environment posture. The "
        "production-like fail-closed rate-limiter path is a separate "
        "configuration and is not driven here.",
    )

    async def run_configuration(self, target: Target, log: EventLog) -> ConfigurationResult:
        import app.core.rate_limiter as rate_limiter_module
        from app.core.config import get_settings
        from app.core.durable_state import get_durable_state
        from app.core.runtime_degradation import (
            get_runtime_degradation,
            reset_runtime_degradation,
        )

        gateway, tenant, _ = target.require_gateway()
        configuration = target.configuration.value
        settings = get_settings()
        dead_url = _closed_loopback_url()

        log.emit(
            "t12.start",
            f"{configuration}: pointing the cache at a closed loopback port and "
            f"driving the whole governed loop through it",
            scenario=self.test_id,
            configuration=configuration,
            cache_url=dead_url,
            tool=GATEWAY_TOOL_ID,
        )

        # Read the operator surface before anything is touched. This also
        # forces the ASGI app to build its middleware stack, so the running
        # limiter exists to be found below.
        health_before = await self._health(gateway, log, target, stage="cache_up")
        degradation_before = get_runtime_degradation()

        limiters = _live_rate_limiters(
            gateway.app, rate_limiter_module.RateLimitMiddleware
        )
        module_settings_is_cached_settings = rate_limiter_module.settings is settings
        saved_module_settings = rate_limiter_module.settings
        saved_redis_url = settings.REDIS_URL
        saved_limiters = [
            (limiter, limiter._redis_url, limiter._redis, limiter._redis_warned)
            for limiter in limiters
        ]

        try:
            # -- stage 1: change the configuration, nothing else ----------
            settings.REDIS_URL = dead_url
            rate_limiter_module.settings = settings
            reset_runtime_degradation()
            health_settings_only = await self._health(
                gateway, log, target, stage="settings_patched_only"
            )
            degradation_settings_only = get_runtime_degradation()
            settings_patch_reached_limiter = bool(
                _dig(
                    degradation_settings_only,
                    "rate_limiter",
                    "using_memory_fallback",
                )
            )

            # -- stage 2: the running limiter loses its cache -------------
            for limiter in limiters:
                limiter._redis_url = dead_url
                limiter._redis = None
                limiter._redis_warned = False
            reset_runtime_degradation()
            log.emit(
                "t12.cache_down",
                f"{configuration}: cache unreachable at {dead_url}; "
                f"{len(limiters)} live rate limiter(s) rebound "
                f"(settings patch alone reached the limiter: "
                f"{settings_patch_reached_limiter})",
                scenario=self.test_id,
                configuration=configuration,
                cache_url=dead_url,
                live_rate_limiters=len(limiters),
                settings_patch_reached_limiter=settings_patch_reached_limiter,
                rate_limiter_module_settings_is_cached_settings=(
                    module_settings_is_cached_settings
                ),
            )

            # -- the governed loop, with the cache down -------------------
            op_clean, refund_clean = self.refund("pay_t12_clean", amount=PROBE_AMOUNT)
            identity = OperationIdentity.first_attempt(op_clean)

            snap_start = await gateway.snapshot(tenant)
            clean = await target.agent.submit(
                identity, refund_clean, timeout_seconds=SUBMIT_TIMEOUT_SECONDS
            )
            snap_clean = await gateway.snapshot(tenant)
            clean_row = self._movement(
                target, before=snap_start, after=snap_clean, operation_id=op_clean
            )
            self._log_call(log, target, "clean", clean, clean_row)

            replay = await target.agent.submit(
                identity.retry(), refund_clean, timeout_seconds=SUBMIT_TIMEOUT_SECONDS
            )
            snap_replay = await gateway.snapshot(tenant)
            replay_row = self._movement(
                target, before=snap_clean, after=snap_replay, operation_id=op_clean
            )
            self._log_call(log, target, "replay", replay, replay_row)

            denial_permit = await gateway.issue_permit(
                tenant,
                max_credits=Decimal(gateway.credits_per_call) * 10,
                tool=UNPERMITTED_TOOL,
            )
            op_denied, refund_denied = self.refund(
                "pay_t12_denied", amount=PROBE_AMOUNT
            )
            denial_agent = target.gateway_agent(str(denial_permit["permit_id"]))
            denial = await denial_agent.submit(
                OperationIdentity.first_attempt(op_denied),
                refund_denied,
                timeout_seconds=SUBMIT_TIMEOUT_SECONDS,
            )
            snap_denial = await gateway.snapshot(tenant)
            denial_row = self._movement(
                target, before=snap_replay, after=snap_denial, operation_id=op_denied
            )
            self._log_call(log, target, "denial", denial, denial_row)

            health_after = await self._health(gateway, log, target, stage="cache_down")
            degradation_after = get_runtime_degradation()
            state_backend_configured = settings.STATE_BACKEND
            durable_backend = get_durable_state().backend
        finally:
            settings.REDIS_URL = saved_redis_url
            rate_limiter_module.settings = saved_module_settings
            for limiter, url, client, warned in saved_limiters:
                limiter._redis_url = url
                limiter._redis = client
                limiter._redis_warned = warned
            reset_runtime_degradation()

        attempts: list[AttemptOutcome] = [clean, replay, denial]
        measurements = await self.measure(
            target, attempts, operation_ids=[op_clean, op_denied]
        )

        replay_new_executions = (
            replay_row["executions_total"] - clean_row["executions_total"]
        )
        replay_new_dispatches = (
            replay_row["dispatches_total"] - clean_row["dispatches_total"]
        )
        clean_receipt_outcomes = [row["outcome"] for row in clean_row["receipts"]]

        invariants = {
            "clean_call_succeeded": clean.status == "success",
            "one_downstream_execution": clean_row["executions_total"] == 1,
            "one_debit": clean_row["debits"] == 1 and clean_row["refunds"] == 0,
            "one_receipt": len(clean_row["receipts"]) == 1,
            "clean_receipt_outcome_success": clean_receipt_outcomes == ["success"],
            "replay_added_no_execution": replay_new_executions == 0,
            "replay_added_no_dispatch": replay_new_dispatches == 0,
            "replay_added_no_net_debit": replay_row["net_debits"] == 0,
            "replay_returned_the_same_receipt_id": (
                clean.receipt_id is not None and replay.receipt_id == clean.receipt_id
            ),
            "denial_still_denied": (
                denial.status in REFUSED_STATUSES
                and denial.client_visible_state == "confirmed_rejected"
            ),
            "denial_executed_nothing": denial_row["executions_total"] == 0,
            "denial_dispatched_nothing": denial_row["dispatches_total"] == 0,
            "denial_cost_nothing": denial_row["net_debits"] == 0,
        }
        broken = sorted(name for name, held in invariants.items() if not held)
        participates_in_enforcement = bool(broken)

        runtime_says_fallback = bool(
            _dig(degradation_after, "rate_limiter", "using_memory_fallback")
        )
        health_says_fallback = bool(
            _dig(
                health_after,
                "runtime_degradation",
                "rate_limiter",
                "using_memory_fallback",
            )
        )
        health_status = _dig(health_after, "status")
        unhealthy = _dig(health_after, "unhealthy") or []
        redis_probe_status = _dig(health_after, "dependencies", "redis", "status")
        degradation_surfaced = bool(
            runtime_says_fallback and health_says_fallback and health_status == "degraded"
        )

        problems = [f"correctness invariant broken: {name}" for name in broken]
        if not degradation_surfaced:
            problems.append(
                "the cache outage was not surfaced: "
                f"{HEALTH_PATH} answered status={health_status!r} with "
                f"runtime_degradation.rate_limiter.using_memory_fallback="
                f"{health_says_fallback} while the limiter was in fact serving "
                "from memory"
            )
        verdict = Verdict.PASS if not problems else Verdict.FAIL

        observation = self._observation(
            clean=clean,
            replay=replay,
            denial=denial,
            clean_row=clean_row,
            replay_row=replay_row,
            denial_row=denial_row,
            snapshot=snap_denial,
            durable_backend=durable_backend,
            state_backend_configured=state_backend_configured,
            live_limiters=len(limiters),
            settings_patch_reached_limiter=settings_patch_reached_limiter,
            settings_only_redis_status=_dig(
                health_settings_only, "dependencies", "redis", "status"
            ),
            health_status=health_status,
            unhealthy=list(unhealthy),
            redis_probe_status=redis_probe_status,
            health_says_fallback=health_says_fallback,
            problems=problems,
        )

        log.emit(
            "t12.verdict",
            f"{configuration} -> {verdict.value}",
            scenario=self.test_id,
            configuration=configuration,
            participates_in_enforcement=participates_in_enforcement,
            degradation_surfaced=degradation_surfaced,
            broken_invariants=broken,
            health_status=health_status,
            unhealthy=list(unhealthy),
            problems=problems,
        )

        return self.result(
            target,
            verdict=verdict,
            observation=observation,
            measurements=measurements,
            attempts=attempts,
            remaining_risks=self._remaining_risks(
                durable_backend=durable_backend,
                state_backend_configured=state_backend_configured,
            ),
            extra={
                "participates_in_enforcement": participates_in_enforcement,
                "degradation_surfaced": degradation_surfaced,
                "tool": GATEWAY_TOOL_ID,
                "cache_outage": {
                    "redis_url": dead_url,
                    "live_rate_limiters_rebound": len(limiters),
                    "rate_limiter_module_settings_is_cached_settings": (
                        module_settings_is_cached_settings
                    ),
                    "settings_patch_alone_reached_the_limiter": (
                        settings_patch_reached_limiter
                    ),
                },
                "components_using_cache": {
                    "rate_limiter": (
                        "redis when REDIS_URL is set; in-memory fallback when it "
                        "is not, or when it is unreachable outside a "
                        "production-like environment"
                    ),
                    "durable_state_configured": state_backend_configured,
                    "durable_state_resolved": durable_backend,
                },
                "invariants": invariants,
                "broken_invariants": broken,
                "calls": {
                    "clean": {
                        **clean_row,
                        "status": clean.status,
                        "client_visible_state": clean.client_visible_state,
                        "receipt_id": clean.receipt_id,
                        "reason": clean.reason,
                    },
                    "replay": {
                        **replay_row,
                        "status": replay.status,
                        "client_visible_state": replay.client_visible_state,
                        "receipt_id": replay.receipt_id,
                        "reason": replay.reason,
                        "new_executions": replay_new_executions,
                        "new_dispatches": replay_new_dispatches,
                        "same_receipt_id_as_clean": (
                            replay.receipt_id == clean.receipt_id
                        ),
                    },
                    "denial": {
                        **denial_row,
                        "status": denial.status,
                        "client_visible_state": denial.client_visible_state,
                        "receipt_id": denial.receipt_id,
                        "reason": denial.reason,
                        "permit_id": str(denial_permit["permit_id"]),
                        "permit_allowed_tool": UNPERMITTED_TOOL,
                    },
                },
                "health": {
                    "cache_up": _health_summary(health_before),
                    "settings_patched_only": _health_summary(health_settings_only),
                    "cache_down": _health_summary(health_after),
                },
                "runtime_degradation": {
                    "cache_up": degradation_before,
                    "settings_patched_only": degradation_settings_only,
                    "cache_down": degradation_after,
                },
                "gateway_state_read_back_from_the_relational_database": {
                    "idempotency_records": len(snap_denial.idempotency_records),
                    "dispatch_attempts": len(snap_denial.attempts),
                    "debits": snap_denial.debit_count,
                    "refunds": snap_denial.refund_count,
                    "receipts": snap_denial.receipt_count,
                    "receipt_outcomes": snap_denial.receipt_outcomes(),
                    "permits": len(snap_denial.permits),
                    "wallet_balance": snap_denial.wallet_balance,
                },
                "problems": problems,
            },
        )

    # -- instruments ------------------------------------------------------

    async def _health(
        self, gateway: Any, log: EventLog, target: Target, *, stage: str
    ) -> Any:
        """Read the operator dependency surface and record what it said."""
        response = await gateway.client.get(HEALTH_PATH)
        try:
            document = response.json()
        except ValueError:
            document = {"unreadable": response.text[:200]}
        log.emit(
            "t12.health",
            f"{stage}: {HEALTH_PATH} -> {response.status_code} "
            f"status={_dig(document, 'status')} "
            f"redis={_dig(document, 'dependencies', 'redis', 'status')} "
            f"rate_limiter_memory_fallback="
            f"{_dig(document, 'runtime_degradation', 'rate_limiter', 'using_memory_fallback')}",
            scenario=self.test_id,
            configuration=target.configuration.value,
            stage=stage,
            http_status=response.status_code,
            health=_health_summary(document),
        )
        return document

    def _movement(
        self, target: Target, *, before: Any, after: Any, operation_id: str
    ) -> dict[str, Any]:
        """What one call moved, from the gateway tables, ledger and fault layer."""
        added_debits = _added(before.debits, after.debits, "entry_id")
        added_refunds = _added(before.refunds, after.refunds, "entry_id")
        added_receipts = _added(before.receipts, after.receipts, "receipt_id")
        return {
            "operation_id": operation_id,
            "debits": len(added_debits),
            "refunds": len(added_refunds),
            "net_debits": len(added_debits) - len(added_refunds),
            "net_charge_credits": _credit_text(
                -(_credits(added_debits) + _credits(added_refunds))
            ),
            "receipts": [
                {
                    "receipt_id": row["receipt_id"],
                    "outcome": row["outcome"],
                    "reason_code": row["reason_code"],
                }
                for row in added_receipts
            ],
            "executions_total": target.ledger.execution_count(
                operation_id=operation_id
            ),
            "dispatches_total": target.injector.dispatch_count(
                operation_id=operation_id
            ),
        }

    def _log_call(
        self,
        log: EventLog,
        target: Target,
        label: str,
        outcome: AttemptOutcome,
        row: dict[str, Any],
    ) -> None:
        log.emit(
            "t12.call",
            f"{label}: status={outcome.status} "
            f"({outcome.client_visible_state}) receipt={outcome.receipt_id} "
            f"executions={row['executions_total']} "
            f"dispatches={row['dispatches_total']} "
            f"net_debits={row['net_debits']}",
            scenario=self.test_id,
            configuration=target.configuration.value,
            call=label,
            status=outcome.status,
            client_visible_state=outcome.client_visible_state,
            reason=outcome.reason,
            receipt_id=outcome.receipt_id,
            **row,
        )

    # -- prose ------------------------------------------------------------

    def _observation(
        self,
        *,
        clean: AttemptOutcome,
        replay: AttemptOutcome,
        denial: AttemptOutcome,
        clean_row: dict[str, Any],
        replay_row: dict[str, Any],
        denial_row: dict[str, Any],
        snapshot: Any,
        durable_backend: str,
        state_backend_configured: str,
        live_limiters: int,
        settings_patch_reached_limiter: bool,
        settings_only_redis_status: Any,
        health_status: Any,
        unhealthy: list[Any],
        redis_probe_status: Any,
        health_says_fallback: bool,
        problems: list[str],
    ) -> str:
        same_receipt = (
            "the same receipt id"
            if replay.receipt_id == clean.receipt_id and clean.receipt_id is not None
            else f"a different receipt id ({replay.receipt_id})"
        )
        text = (
            f"With REDIS_URL pointed at a closed loopback port, the governed "
            f"loop ran unchanged. The clean call returned '{clean.status}' "
            f"({clean.client_visible_state}); the independent effect ledger "
            f"recorded {clean_row['executions_total']} downstream execution(s), "
            f"the gateway took {clean_row['debits']} debit(s) and "
            f"{clean_row['refunds']} refund(s) "
            f"({clean_row['net_charge_credits']} credits net) and wrote "
            f"{len(clean_row['receipts'])} receipt(s) "
            f"{[row['outcome'] for row in clean_row['receipts']]}. The replay "
            f"of the same key returned '{replay.status}' with {same_receipt}, "
            f"adding {replay_row['executions_total'] - clean_row['executions_total']} "
            f"execution(s), "
            f"{replay_row['dispatches_total'] - clean_row['dispatches_total']} "
            f"dispatch(es) and {replay_row['net_debits']} net debit(s). The "
            f"out-of-permit call was still refused as '{denial.status}' "
            f"({denial.reason}) with {denial_row['dispatches_total']} "
            f"dispatch(es), {denial_row['executions_total']} execution(s) and "
            f"{denial_row['net_charge_credits']} credits charged. "
            f"The components that use the cache in this configuration are rate "
            f"limiting and, where an operator sets STATE_BACKEND=redis, durable "
            f"state; this posture has STATE_BACKEND={state_backend_configured!r} "
            f"resolving to {durable_backend!r}, so the rate limiter was the only "
            f"cache participant in the path. The permit, idempotency, dispatch, "
            f"debit and receipt state the loop depended on was read back out of "
            f"the gateway's relational database with the cache still "
            f"unreachable -- {len(snapshot.idempotency_records)} idempotency "
            f"record(s), {len(snapshot.attempts)} dispatch attempt(s), "
            f"{snapshot.debit_count} debit(s), {snapshot.refund_count} refund(s) "
            f"and {snapshot.receipt_count} receipt(s) "
            f"{snapshot.receipt_outcomes()} -- which is what the run shows that "
            f"path to be backed by. "
            f"The degradation was not silent: {HEALTH_PATH} answered "
            f"status={health_status!r}, listed {unhealthy} as unhealthy, "
            f"reported the redis probe as {redis_probe_status!r} and named the "
            f"rate limiter's memory fallback "
            f"(using_memory_fallback={health_says_fallback}). "
            f"Getting there took two steps, and the first one is worth "
            f"reporting: changing the cached settings object alone left the "
            f"running limiter untouched -- it reported "
            f"using_memory_fallback={settings_patch_reached_limiter} while the "
            f"dependency probe already showed redis "
            f"{settings_only_redis_status!r} -- because REDIS_URL is copied into "
            f"the middleware when the stack is built. Rebinding the "
            f"{live_limiters} live limiter instance(s) is what made the outage "
            f"reach the limiter, and it models the real shape of this failure: "
            f"a cache that was reachable at boot and then died."
        )
        if problems:
            text += " Problems: " + "; ".join(problems) + "."
        return text

    def _remaining_risks(
        self, *, durable_backend: str, state_backend_configured: str
    ) -> list[str]:
        return [
            "Rate limiting served the whole run from its in-memory fallback, so "
            "the ceiling it enforced was per process rather than shared. In a "
            "multi-instance deployment that is a materially weaker ceiling -- "
            "which is precisely the degradation the health surface is reporting, "
            "not a second failure.",
            f"Durable state resolved to {durable_backend!r} here "
            f"(STATE_BACKEND={state_backend_configured!r}), so the cache was "
            "never in that path. A deployment that sets STATE_BACKEND=redis puts "
            "dispatch bookkeeping in the cache, and nothing measured here says "
            "what a cache outage does to it.",
            "The cache URL is read once, when the middleware stack is built, so "
            "the harness had to rebind the running limiter to make a configured "
            "cache unreachable. A deployment cannot re-point its cache without a "
            "restart either; a cache moved at runtime is outside what this run "
            "covers.",
        ]
