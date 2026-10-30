"""SEL-320: demo-key first use, the admin funnel endpoint, and migration 050."""

# Imported pytest fixtures intentionally share test parameter names.
# ruff: noqa: F811

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import create_engine, inspect, select, text

from app.db.database import get_session_factory
from app.db.models import APIKeyModel
from tests.test_demo_tenant import (
    client as _client,
    demo_headers,
    demo_settings as _demo_settings,
)
from tests.test_trust_helpers import BOOTSTRAP_HEADERS, provision_agent_wallet

# Rebind so pytest discovers the fixtures without importing those names.
# A same-named parameter would be an F811 redefinition of an unused import.
client = _client
demo_settings = _demo_settings

FUNNEL = "/v1/admin/demo-keys/funnel"


async def _issue(client: AsyncClient, **attribution: str) -> dict:
    resp = await client.post("/v1/demo/keys", json=attribution)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _key_row(key_id: str) -> APIKeyModel:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(APIKeyModel).where(APIKeyModel.key_id == key_id)
        )
        return result.scalar_one()


async def _use(client: AsyncClient, body: dict) -> None:
    resp = await client.get("/v1/me/authority", headers=demo_headers(body))
    assert resp.status_code == 200, resp.text


# --- first_used_at ------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("max_uses", [None, 10])
async def test_first_used_at_set_once_and_never_overwritten(
    client: AsyncClient, clean_database: None, demo_settings, max_uses
) -> None:
    # None = unbounded key (ORM path); 10 = guarded UPDATE path.
    demo_settings.DEMO_KEY_MAX_USES = max_uses
    body = await _issue(client)
    assert (await _key_row(body["key_id"])).first_used_at is None

    await _use(client, body)
    first = (await _key_row(body["key_id"])).first_used_at
    assert first is not None

    await _use(client, body)
    await _use(client, body)
    row = await _key_row(body["key_id"])
    assert row.first_used_at == first
    assert row.last_used_at is not None and row.last_used_at >= first


# --- funnel endpoint ----------------------------------------------------------


@pytest.mark.anyio
async def test_funnel_counts_issued_vs_used_by_source(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    # Five keys from one test client exceed the default per-IP cap of 3.
    demo_settings.DEMO_ISSUE_PER_IP_PER_DAY = 10
    ph_used = await _issue(
        client, utm_source="producthunt", utm_medium="launch", utm_campaign="ph1"
    )
    await _issue(
        client, utm_source="producthunt", utm_medium="launch", utm_campaign="ph1"
    )
    # Same referrer host, different paths: one row.
    hn_used = await _issue(client, referrer="https://news.ycombinator.com/item?id=1")
    await _issue(client, referrer="https://news.ycombinator.com/newest")
    await _issue(client)
    # A non-demo key must never be counted.
    await provision_agent_wallet(client)

    await _use(client, ph_used)
    await _use(client, ph_used)
    await _use(client, hn_used)

    resp = await client.get(FUNNEL, headers=BOOTSTRAP_HEADERS)
    assert resp.status_code == 200, resp.text
    rows = {
        (r["utm_source"], r["utm_campaign"], r["referrer_host"]): r
        for r in resp.json()["rows"]
    }
    assert set(rows) == {
        ("producthunt", "ph1", None),
        ("(none)", None, "news.ycombinator.com"),
        ("(none)", None, None),
    }
    ph = rows[("producthunt", "ph1", None)]
    assert (ph["keys_issued"], ph["keys_used"], ph["utm_medium"]) == (2, 1, "launch")
    hn = rows[("(none)", None, "news.ycombinator.com")]
    assert (hn["keys_issued"], hn["keys_used"]) == (2, 1)
    none = rows[("(none)", None, None)]
    assert (none["keys_issued"], none["keys_used"]) == (1, 0)
    assert ph["first_issued_at"] <= ph["last_issued_at"]


@pytest.mark.anyio
async def test_funnel_since_until_filter_on_issuance_time(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    await _issue(client, utm_source="a")
    now = datetime.now(timezone.utc)

    future = (now + timedelta(hours=1)).isoformat()
    past = (now - timedelta(hours=1)).isoformat()
    later = await client.get(
        FUNNEL, params={"since": future}, headers=BOOTSTRAP_HEADERS
    )
    assert later.status_code == 200
    assert later.json()["rows"] == []

    window = await client.get(
        FUNNEL, params={"since": past, "until": future}, headers=BOOTSTRAP_HEADERS
    )
    assert [r["keys_issued"] for r in window.json()["rows"]] == [1]

    earlier = await client.get(
        FUNNEL, params={"until": past}, headers=BOOTSTRAP_HEADERS
    )
    assert earlier.json()["rows"] == []


@pytest.mark.anyio
async def test_funnel_requires_bootstrap_admin(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    demo = await _issue(client)
    normal = await provision_agent_wallet(client)

    assert (await client.get(FUNNEL)).status_code == 401
    unknown = await client.get(FUNNEL, headers={"X-API-Key": "not-a-real-key"})
    assert unknown.status_code == 403
    assert unknown.json()["detail"]["error"] == "invalid_api_key"
    wallet = await client.get(FUNNEL, headers=normal["agent_headers"])
    assert wallet.status_code == 403
    assert wallet.json()["detail"]["error"] == "admin_access_denied"
    denied = await client.get(FUNNEL, headers=demo_headers(demo))
    assert denied.status_code == 403
    # Demo callers are stopped at the route denylist before the admin check.
    assert denied.json()["detail"]["error"] == "demo_key_route_forbidden"


@pytest.mark.anyio
async def test_funnel_works_with_kill_switch_off(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    await _issue(client, utm_source="a")
    demo_settings.ENABLE_DEMO_TENANT = False
    resp = await client.get(FUNNEL, headers=BOOTSTRAP_HEADERS)
    assert resp.status_code == 200
    assert [r["utm_source"] for r in resp.json()["rows"]] == ["a"]


# --- migration 050 ------------------------------------------------------------


def test_050_revision_chain_and_file() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script.get_revision("050_demo_key_first_used")
    assert revision.down_revision == "049_demo_key_attribution"
    assert script.get_heads() == ["051_api_key_usage_events"]
    assert Path(revision.path).name == "050_demo_key_first_used.py"


def test_050_upgrade_backfills_creates_view_and_downgrades(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "demo-funnel-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    config = Config("alembic.ini")

    command.upgrade(config, "049_demo_key_attribution")
    engine = create_engine(f"sqlite:///{db_path}")
    insert = text(
        "INSERT INTO api_keys (key_id, wallet_id, key_hash, key_prefix, status, "
        "rotation_count, created_at, use_count, tenant, utm_source, referrer, "
        "last_used_at) VALUES (:key_id, 'w', :key_id, 'b2a_xxxx', 'active', 0, "
        ":created, 0, :tenant, :source, :referrer, :last_used)"
    )
    with engine.begin() as connection:
        for key_id, tenant, source, referrer, last_used in (
            ("k-used", "demo", "ph", None, "2026-10-10 00:00:00"),
            ("k-unused", "demo", "ph", None, None),
            ("k-ref", "demo", None, "https://x.example/a", None),
            ("k-normal", None, None, None, "2026-10-11 00:00:00"),
        ):
            connection.execute(
                insert,
                {
                    "key_id": key_id,
                    "created": "2026-10-01 00:00:00",
                    "tenant": tenant,
                    "source": source,
                    "referrer": referrer,
                    "last_used": last_used,
                },
            )
    engine.dispose()

    command.upgrade(config, "050_demo_key_first_used")
    engine = create_engine(f"sqlite:///{db_path}")
    assert "first_used_at" in {
        c["name"] for c in inspect(engine).get_columns("api_keys")
    }
    assert "demo_key_funnel_by_source" in inspect(engine).get_view_names()
    with engine.begin() as connection:
        backfilled = dict(
            connection.execute(text("SELECT key_id, first_used_at FROM api_keys")).all()
        )
        view_rows = connection.execute(
            text(
                "SELECT utm_source, referrer_host, keys_issued, keys_used "
                "FROM demo_key_funnel_by_source ORDER BY utm_source, referrer_host"
            )
        ).all()
    engine.dispose()
    assert backfilled["k-used"] is not None
    assert backfilled["k-normal"] is not None
    assert backfilled["k-unused"] is None
    assert backfilled["k-ref"] is None
    # Non-demo keys are excluded; SQLite groups by the raw referrer.
    assert [tuple(r) for r in view_rows] == [
        ("(none)", "https://x.example/a", 1, 0),
        ("ph", None, 2, 1),
    ]

    command.downgrade(config, "049_demo_key_attribution")
    engine = create_engine(f"sqlite:///{db_path}")
    assert "first_used_at" not in {
        c["name"] for c in inspect(engine).get_columns("api_keys")
    }
    assert "demo_key_funnel_by_source" not in inspect(engine).get_view_names()
    with engine.begin() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM api_keys")).scalar_one()
    engine.dispose()
    assert count == 4
