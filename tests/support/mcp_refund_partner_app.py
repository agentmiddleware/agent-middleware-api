"""Non-idempotent refund-style MCP partner for exactly-once reviews.

The echo tool is idempotent by construction, so it cannot show whether the
gateway's exactly-once behavior reaches a real remote side effect. This
partner exposes ``partner.refund`` and commits one durable, countable refund
effect to a dedicated SQLite file before returning.

Two behaviors are switchable so the same deployment answers both questions:

* Idempotency honoring (runtime switch, ``POST /__stress/mode``). When off, every
  dispatch commits a new effect, so any redispatch is visible as a duplicate.
  When on, a repeated forwarded idempotency key returns the first result and
  commits nothing new, which is what an upstream must do for exactly-once to
  hold end to end.
* Post-effect failure (per call, ``after_effect``). ``none`` returns normally,
  ``error`` raises after the effect is committed, and ``hang`` holds the
  response after the effect is committed so a gateway timeout lands in the
  ``delivery_uncertain`` window. ``hang_seconds`` must exceed the gateway's
  ``MCP_UPSTREAM_CALL_TIMEOUT_SECONDS`` by a safe margin (default 90 against
  the gateway default of 30).

This is a synthetic fixture, not evidence of partner-owned customer validation.
"""

from __future__ import annotations

import asyncio
import hmac
import os
import sqlite3
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse


CONTROL_HEADER = "X-MCP-Refund-Control"
REFUND_TOOL_NAME = "partner.refund"
# The gateway's MCP_UPSTREAM_CALL_TIMEOUT_SECONDS defaults to 30 and is
# configurable, so a hang must outlast that timeout by a wide margin to land in
# delivery_uncertain deterministically instead of racing the response.
DEFAULT_HANG_SECONDS = 90.0
MAX_HANG_SECONDS = 600.0
_AFTER_EFFECT_MODES = ("none", "error", "hang")
_INVOCATION_META_KEY = "io.agentmiddleware/invocation_id"
_IDEMPOTENCY_META_KEY = "io.agentmiddleware/idempotency_key"


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "")
    if not value or value != value.strip() or any(ord(char) < 32 for char in value):
        raise RuntimeError(f"{name} must be a non-empty value without whitespace")
    return value


_DATABASE_PATH = Path(_required_environment("MCP_REFUND_PARTNER_DB_PATH"))
if not _DATABASE_PATH.is_absolute():
    raise RuntimeError("MCP_REFUND_PARTNER_DB_PATH must be an absolute path")

_CONTROL_TOKEN = _required_environment("MCP_REFUND_PARTNER_CONTROL_TOKEN")
_BEARER_TOKEN = _required_environment("MCP_REFUND_PARTNER_BEARER_TOKEN")
_ALLOWED_HOST = _required_environment("MCP_REFUND_PARTNER_ALLOWED_HOST")
_DEFAULT_HONOR = os.environ.get("MCP_REFUND_PARTNER_HONOR_IDEMPOTENCY", "false")


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA synchronous = FULL")
    return connection


def _initialize_database() -> None:
    _DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS refund_effects (
                effect_id INTEGER PRIMARY KEY AUTOINCREMENT,
                refund_ref TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                invocation_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                worker_pid INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                )
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS refund_attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                refund_ref TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                effect_id INTEGER NOT NULL,
                deduplicated INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                )
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS ix_refund_effects_key "
            "ON refund_effects (idempotency_key)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS refund_settings "
            "(name TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT OR IGNORE INTO refund_settings (name, value) VALUES (?, ?)",
            ("honor_idempotency", "1" if _truthy(_DEFAULT_HONOR) else "0"),
        )
        connection.commit()


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _honor_idempotency() -> bool:
    with _connect() as connection:
        row = connection.execute(
            "SELECT value FROM refund_settings WHERE name = 'honor_idempotency'"
        ).fetchone()
    return bool(row) and row["value"] == "1"


def _set_honor_idempotency(enabled: bool) -> None:
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO refund_settings (name, value) VALUES ('honor_idempotency', ?) "
            "ON CONFLICT(name) DO UPDATE SET value = excluded.value",
            ("1" if enabled else "0",),
        )
        connection.commit()


def _apply_refund(
    *,
    refund_ref: str,
    amount_cents: int,
    invocation_id: str,
    idempotency_key: str,
    honor_idempotency: bool,
) -> dict[str, Any]:
    """Commit one refund effect, or return the first one for a repeated key."""
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if honor_idempotency:
            existing = connection.execute(
                "SELECT effect_id, refund_ref, amount_cents FROM refund_effects "
                "WHERE idempotency_key = ? ORDER BY effect_id LIMIT 1",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["refund_ref"] != refund_ref
                    or existing["amount_cents"] != amount_cents
                ):
                    raise ValueError("idempotency key reused with different arguments")
                connection.execute(
                    "INSERT INTO refund_attempts "
                    "(refund_ref, idempotency_key, effect_id, deduplicated) "
                    "VALUES (?, ?, ?, 1)",
                    (refund_ref, idempotency_key, existing["effect_id"]),
                )
                connection.commit()
                return {
                    "effect_id": int(existing["effect_id"]),
                    "deduplicated": True,
                }
        cursor = connection.execute(
            "INSERT INTO refund_effects "
            "(refund_ref, amount_cents, invocation_id, idempotency_key, worker_pid) "
            "VALUES (?, ?, ?, ?, ?)",
            (refund_ref, amount_cents, invocation_id, idempotency_key, os.getpid()),
        )
        effect_id = cursor.lastrowid
        if effect_id is None:
            raise RuntimeError("refund_effect_id_missing")
        connection.execute(
            "INSERT INTO refund_attempts "
            "(refund_ref, idempotency_key, effect_id, deduplicated) "
            "VALUES (?, ?, ?, 0)",
            (refund_ref, idempotency_key, effect_id),
        )
        connection.commit()
    return {"effect_id": int(effect_id), "deduplicated": False}


def _effect_rows(refund_ref: str | None = None) -> tuple[list[dict[str, Any]], int]:
    """Return up to 1000 effect rows plus the true total for the same filter."""
    where = ""
    parameters: tuple[str, ...] = ()
    if refund_ref is not None:
        where = " WHERE refund_ref = ?"
        parameters = (refund_ref,)
    with _connect() as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM refund_effects" + where, parameters
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT effect_id, refund_ref, amount_cents, invocation_id, "
            "idempotency_key, worker_pid, created_at FROM refund_effects"
            + where
            + " ORDER BY effect_id LIMIT 1000",
            parameters,
        ).fetchall()
    return [dict(row) for row in rows], int(total)


def _totals() -> dict[str, int]:
    with _connect() as connection:
        effects = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount_cents), 0) FROM refund_effects"
        ).fetchone()
        attempts = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(deduplicated), 0) FROM refund_attempts"
        ).fetchone()
    return {
        "effect_count": int(effects[0]),
        "total_refunded_cents": int(effects[1]),
        "attempt_count": int(attempts[0]),
        "deduplicated_attempt_count": int(attempts[1]),
    }


def _control_authorized(request: Request) -> bool:
    provided = request.headers.get(CONTROL_HEADER)
    return provided is not None and hmac.compare_digest(provided, _CONTROL_TOKEN)


_initialize_database()

server = FastMCP(
    "agent-middleware-refund-partner",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(allowed_hosts=[_ALLOWED_HOST]),
)


@server.tool(
    name=REFUND_TOOL_NAME,
    description="Commit one countable refund effect (non-idempotent unless enabled)",
)
async def partner_refund(
    refund_ref: str,
    amount_cents: int,
    ctx: Context,
    after_effect: str = "none",
    hang_seconds: float = DEFAULT_HANG_SECONDS,
) -> dict[str, Any]:
    if not refund_ref or len(refund_ref) > 512:
        raise ValueError("refund_ref must contain between 1 and 512 characters")
    if amount_cents <= 0 or amount_cents > 1_000_000:
        raise ValueError("amount_cents must be between 1 and 1000000")
    if after_effect not in _AFTER_EFFECT_MODES:
        raise ValueError(f"after_effect must be one of {_AFTER_EFFECT_MODES}")
    if not 0 < hang_seconds <= MAX_HANG_SECONDS:
        raise ValueError(f"hang_seconds must be in (0, {MAX_HANG_SECONDS}]")

    metadata = ctx.request_context.meta
    metadata_payload = (
        metadata.model_dump(mode="json", by_alias=True, exclude_none=True)
        if metadata is not None
        else {}
    )
    invocation_id = metadata_payload.get(_INVOCATION_META_KEY)
    idempotency_key = metadata_payload.get(_IDEMPOTENCY_META_KEY)
    if not isinstance(invocation_id, str) or not invocation_id:
        raise ValueError("forwarded invocation metadata is required")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise ValueError("forwarded idempotency metadata is required")

    honor = await asyncio.to_thread(_honor_idempotency)
    result = await asyncio.to_thread(
        _apply_refund,
        refund_ref=refund_ref,
        amount_cents=amount_cents,
        invocation_id=invocation_id,
        idempotency_key=idempotency_key,
        honor_idempotency=honor,
    )
    # The effect is durable from here on; everything below is response loss.
    if after_effect == "error":
        raise RuntimeError("refund_partner_error_after_effect")
    if after_effect == "hang":
        await asyncio.sleep(hang_seconds)
    return {
        "refund_ref": refund_ref,
        "effect_id": result["effect_id"],
        "deduplicated": result["deduplicated"],
        "honor_idempotency": honor,
        "partner_pid": os.getpid(),
    }


@server.custom_route("/__stress/health", methods=["GET"], include_in_schema=False)
async def stress_health(request: Request) -> JSONResponse:
    if not _control_authorized(request):
        return JSONResponse({"detail": "refund_partner_control_denied"}, status_code=403)
    totals = await asyncio.to_thread(_totals)
    honor = await asyncio.to_thread(_honor_idempotency)
    return JSONResponse(
        {
            "status": "ok",
            "pid": os.getpid(),
            "tool_name": REFUND_TOOL_NAME,
            "honor_idempotency": honor,
            **totals,
        }
    )


@server.custom_route("/__stress/effects", methods=["GET"], include_in_schema=False)
async def stress_effects(request: Request) -> JSONResponse:
    if not _control_authorized(request):
        return JSONResponse({"detail": "refund_partner_control_denied"}, status_code=403)
    refund_ref = request.query_params.get("refund_ref")
    if refund_ref is not None and (not refund_ref or len(refund_ref) > 512):
        return JSONResponse(
            {"detail": "refund_partner_refund_ref_invalid"}, status_code=400
        )
    rows, total = await asyncio.to_thread(_effect_rows, refund_ref)
    return JSONResponse(
        {
            "count": total,
            "returned": len(rows),
            "truncated": len(rows) < total,
            "effects": rows,
        }
    )


@server.custom_route("/__stress/mode", methods=["POST"], include_in_schema=False)
async def stress_mode(request: Request) -> JSONResponse:
    if not _control_authorized(request):
        return JSONResponse({"detail": "refund_partner_control_denied"}, status_code=403)
    try:
        payload = await request.json()
    except ValueError:
        payload = None
    enabled = payload.get("honor_idempotency") if isinstance(payload, dict) else None
    if not isinstance(enabled, bool):
        return JSONResponse(
            {"detail": "refund_partner_honor_idempotency_must_be_boolean"},
            status_code=400,
        )
    await asyncio.to_thread(_set_honor_idempotency, enabled)
    return JSONResponse({"honor_idempotency": enabled})


class _BearerAuthMiddleware:
    """Require the configured gateway credential only on the MCP transport."""

    def __init__(self, wrapped_app: Any) -> None:
        self._wrapped_app = wrapped_app
        self._expected = f"Bearer {_BEARER_TOKEN}".encode("utf-8")

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        path = str(scope.get("path", ""))
        if scope.get("type") == "http" and (path == "/mcp" or path.startswith("/mcp/")):
            authorization_values = [
                value
                for key, value in scope.get("headers", [])
                if key.lower() == b"authorization"
            ]
            authorized = len(authorization_values) == 1 and hmac.compare_digest(
                authorization_values[0],
                self._expected,
            )
            if not authorized:
                response = JSONResponse(
                    {"detail": "refund_partner_unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self._wrapped_app(scope, receive, send)


app = _BearerAuthMiddleware(server.streamable_http_app())
