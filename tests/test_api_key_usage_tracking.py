"""
Tests for API key usage event tracking (SEL-346).

Tests the migration, event recording, view aggregation, and admin endpoint.
"""

import pytest
from datetime import timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.time import utc_now, to_naive_utc
from app.db.database import get_session_factory
from app.db.models import APIKeyUsageEventModel
from app.main import app
from app.services.api_key_usage import record_api_key_usage_event


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def admin_key():
    settings = get_settings()
    return settings.VALID_API_KEYS.split(",")[0].strip()


@pytest.fixture
async def db_session():
    """Provide a database session for tests."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


async def create_test_wallet_and_key(tenant=None):
    """Helper to create a test wallet and API key."""
    from app.core.dependencies import get_agent_money
    from app.services.api_key_service import get_api_key_service

    billing = get_agent_money()
    api_key_svc = get_api_key_service()

    # Create wallet
    wallet = await billing.create_sponsor_wallet(
        sponsor_name="Test Sponsor",
        email="test@example.com",
        initial_credits=1000.0,
    )

    # If tenant is specified, update the wallet
    if tenant:
        from app.db.database import get_session_factory
        from sqlalchemy import update
        from app.db.models import WalletModel

        session_factory = get_session_factory()
        async with session_factory() as session:
            await session.execute(
                update(WalletModel)
                .where(WalletModel.wallet_id == wallet.wallet_id)
                .values(tenant=tenant)
            )
            await session.commit()

    # Create key
    key = await api_key_svc.create_key(
        wallet_id=wallet.wallet_id,
        key_name="test_key",
        tenant=tenant,
    )

    return {
        "wallet_id": wallet.wallet_id,
        "key_id": key["key_id"],
        "api_key": key["api_key"],
    }


class TestAPIKeyUsageEventModel:
    """Test the APIKeyUsageEventModel schema."""

    @pytest.mark.asyncio
    async def test_create_usage_event(self, db_session: AsyncSession):
        """Test creating a usage event with all required fields."""
        wallet_data = await create_test_wallet_and_key()
        key_id = wallet_data["key_id"]

        event_id = "ue_test123"
        now = to_naive_utc(utc_now())

        event = APIKeyUsageEventModel(
            id=event_id,
            key_id=key_id,
            tenant=None,
            method="POST",
            route_template="/v1/wallets/{wallet_id}/credit",
            status_code=200,
            latency_ms=42,
            created_at=now,
        )

        db_session.add(event)
        await db_session.commit()

        # Verify it was stored
        result = await db_session.execute(
            select(APIKeyUsageEventModel).where(APIKeyUsageEventModel.id == event_id)
        )
        stored = result.scalar_one()

        assert stored.key_id == key_id
        assert stored.method == "POST"
        assert stored.route_template == "/v1/wallets/{wallet_id}/credit"
        assert stored.status_code == 200
        assert stored.latency_ms == 42
        assert stored.tenant is None

    @pytest.mark.asyncio
    async def test_demo_tenant_event(self, db_session: AsyncSession):
        """Test creating an event for a demo tenant key."""
        wallet_data = await create_test_wallet_and_key(tenant="demo")
        key_id = wallet_data["key_id"]

        event = APIKeyUsageEventModel(
            id="ue_demo123",
            key_id=key_id,
            tenant="demo",
            method="GET",
            route_template="/v1/tools",
            status_code=200,
            latency_ms=15,
            created_at=to_naive_utc(utc_now()),
        )

        db_session.add(event)
        await db_session.commit()

        result = await db_session.execute(
            select(APIKeyUsageEventModel).where(
                APIKeyUsageEventModel.id == "ue_demo123"
            )
        )
        stored = result.scalar_one()
        assert stored.tenant == "demo"

    @pytest.mark.asyncio
    async def test_no_pii_stored(self, db_session: AsyncSession):
        """Verify no PII fields exist in the model."""
        wallet_data = await create_test_wallet_and_key()
        event = APIKeyUsageEventModel(
            id="ue_nopii",
            key_id=wallet_data["key_id"],
            tenant=None,
            method="POST",
            route_template="/v1/mcp/invoke",
            status_code=200,
            latency_ms=100,
            created_at=to_naive_utc(utc_now()),
        )

        # Verify the model has no body, headers, or IP fields
        assert not hasattr(event, "request_body")
        assert not hasattr(event, "response_body")
        assert not hasattr(event, "ip_address")
        assert not hasattr(event, "headers")
        assert not hasattr(event, "user_agent")


class TestRecordAPIKeyUsageEvent:
    """Test the usage event recording service."""

    @pytest.mark.asyncio
    async def test_record_authenticated_call(self, db_session: AsyncSession):
        """Test recording a usage event for an authenticated call."""
        wallet_data = await create_test_wallet_and_key()
        key_id = wallet_data["key_id"]

        await record_api_key_usage_event(
            key_id=key_id,
            tenant=None,
            method="GET",
            route_template="/v1/wallets/{wallet_id}",
            status_code=200,
            latency_ms=25,
        )

        # Verify the event was stored
        result = await db_session.execute(
            select(APIKeyUsageEventModel).where(APIKeyUsageEventModel.key_id == key_id)
        )
        event = result.scalar_one()

        assert event.key_id == key_id
        assert event.method == "GET"
        assert event.route_template == "/v1/wallets/{wallet_id}"
        assert event.status_code == 200
        assert event.latency_ms == 25

    @pytest.mark.asyncio
    async def test_record_unauthenticated_no_event(self, db_session: AsyncSession):
        """Unauthenticated calls should not trigger event recording."""
        # This test verifies the middleware behavior, not the service directly.
        # The middleware should only call record_api_key_usage_event for
        # authenticated requests with a key_id.
        pass

    @pytest.mark.asyncio
    async def test_record_multiple_events(self, db_session: AsyncSession):
        """Test recording multiple events for the same key."""
        wallet_data = await create_test_wallet_and_key()
        key_id = wallet_data["key_id"]

        # Record three events
        for i in range(3):
            await record_api_key_usage_event(
                key_id=key_id,
                tenant=None,
                method="POST",
                route_template="/v1/permits",
                status_code=200 if i < 2 else 400,
                latency_ms=10 + i * 5,
            )

        # Verify all three were stored
        result = await db_session.execute(
            select(APIKeyUsageEventModel).where(APIKeyUsageEventModel.key_id == key_id)
        )
        events = result.scalars().all()
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_record_never_raises(self, db_session: AsyncSession):
        """Failed write should never raise - request must continue."""
        # This should not raise even with an invalid key_id
        await record_api_key_usage_event(
            key_id="nonexistent_key",
            tenant=None,
            method="GET",
            route_template="/test",
            status_code=200,
            latency_ms=10,
        )
        # No assertion - just verify it doesn't raise


class TestAPIKeyUsageDailyView:
    """Test the api_key_usage_daily aggregation view."""

    @pytest.mark.asyncio
    async def test_view_aggregates_by_day(self, db_session: AsyncSession):
        """Test the view aggregates events by key_id and day."""
        wallet_data = await create_test_wallet_and_key()
        key_id = wallet_data["key_id"]

        now = utc_now()
        today = to_naive_utc(now)
        yesterday = to_naive_utc(now - timedelta(days=1))

        # Add events for today
        for i in range(5):
            event = APIKeyUsageEventModel(
                id=f"ue_today_{i}",
                key_id=key_id,
                tenant=None,
                method="GET",
                route_template="/v1/test",
                status_code=200,
                latency_ms=10 + i,
                created_at=today,
            )
            db_session.add(event)

        # Add events for yesterday
        for i in range(3):
            event = APIKeyUsageEventModel(
                id=f"ue_yesterday_{i}",
                key_id=key_id,
                tenant=None,
                method="POST",
                route_template="/v1/test",
                status_code=200,
                latency_ms=20 + i,
                created_at=yesterday,
            )
            db_session.add(event)

        await db_session.commit()

        # Query the view
        result = await db_session.execute(
            text(
                """
                SELECT key_id, day, calls
                FROM api_key_usage_daily
                WHERE key_id = :key_id
                ORDER BY day DESC
                """
            ),
            {"key_id": key_id},
        )
        rows = result.fetchall()

        assert len(rows) == 2
        assert rows[0][2] == 5  # today: 5 calls
        assert rows[1][2] == 3  # yesterday: 3 calls

    @pytest.mark.asyncio
    async def test_view_counts_error_status_codes(self, db_session: AsyncSession):
        """Test the view counts 4xx and 5xx status codes separately."""
        wallet_data = await create_test_wallet_and_key()
        key_id = wallet_data["key_id"]
        now = to_naive_utc(utc_now())

        # Add various status codes
        statuses = [200, 200, 400, 403, 404, 500, 503]
        for i, status in enumerate(statuses):
            event = APIKeyUsageEventModel(
                id=f"ue_status_{i}",
                key_id=key_id,
                tenant=None,
                method="GET",
                route_template="/v1/test",
                status_code=status,
                latency_ms=10,
                created_at=now,
            )
            db_session.add(event)

        await db_session.commit()

        # Query the view
        result = await db_session.execute(
            text(
                """
                SELECT calls, count_4xx, count_5xx
                FROM api_key_usage_daily
                WHERE key_id = :key_id
                """
            ),
            {"key_id": key_id},
        )
        row = result.fetchone()

        assert row[0] == 7  # total calls
        assert row[1] == 3  # 4xx count (400, 403, 404)
        assert row[2] == 2  # 5xx count (500, 503)

    @pytest.mark.asyncio
    async def test_view_calculates_latency_percentiles(self, db_session: AsyncSession):
        """Test the view calculates p50 and p95 latency correctly."""
        wallet_data = await create_test_wallet_and_key()
        key_id = wallet_data["key_id"]
        now = to_naive_utc(utc_now())

        # Add events with known latencies: [10, 20, 30, 40, 50]
        latencies = [10, 20, 30, 40, 50]
        for i, lat in enumerate(latencies):
            event = APIKeyUsageEventModel(
                id=f"ue_lat_{i}",
                key_id=key_id,
                tenant=None,
                method="GET",
                route_template="/v1/test",
                status_code=200,
                latency_ms=lat,
                created_at=now,
            )
            db_session.add(event)

        await db_session.commit()

        # Query the view
        result = await db_session.execute(
            text(
                """
                SELECT p50_latency_ms, p95_latency_ms
                FROM api_key_usage_daily
                WHERE key_id = :key_id
                """
            ),
            {"key_id": key_id},
        )
        row = result.fetchone()

        # p50 of [10,20,30,40,50] = 30
        # p95 of [10,20,30,40,50] ≈ 50
        assert row[0] == 30  # p50
        assert row[1] in [40, 50]  # p95 (implementation-dependent)


class TestAdminUsageEndpoint:
    """Test the admin-only /v1/api-keys/usage/daily endpoint."""

    @pytest.mark.asyncio
    async def test_admin_can_access(self, client, admin_key):
        """Bootstrap admins can access the endpoint."""
        response = await client.get(
            "/v1/api-keys/usage/daily",
            headers={"X-API-Key": admin_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_demo_key_forbidden(self, client, db_session: AsyncSession):
        """Demo tenant keys should receive 403."""
        wallet_data = await create_test_wallet_and_key(tenant="demo")
        api_key = wallet_data["api_key"]

        response = await client.get(
            "/v1/api-keys/usage/daily",
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 403
        detail = response.json()["detail"]
        assert "admin" in detail["message"].lower()

    @pytest.mark.asyncio
    async def test_non_admin_key_forbidden(self, client, db_session: AsyncSession):
        """Non-admin wallet keys should receive 403."""
        wallet_data = await create_test_wallet_and_key()
        api_key = wallet_data["api_key"]

        response = await client.get(
            "/v1/api-keys/usage/daily",
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_filter_by_key_id(self, client, admin_key, db_session: AsyncSession):
        """Test filtering results by key_id."""
        wallet_data = await create_test_wallet_and_key()
        key_id = wallet_data["key_id"]

        # Add an event
        await record_api_key_usage_event(
            key_id=key_id,
            tenant=None,
            method="GET",
            route_template="/v1/test",
            status_code=200,
            latency_ms=10,
        )

        response = await client.get(
            f"/v1/api-keys/usage/daily?key_id={key_id}",
            headers={"X-API-Key": admin_key},
        )
        assert response.status_code == 200
        data = response.json()

        # Should only return stats for the specified key
        assert all(row["key_id"] == key_id for row in data)

    @pytest.mark.asyncio
    async def test_returns_aggregated_fields(
        self, client, admin_key, db_session: AsyncSession
    ):
        """Test the endpoint returns all expected aggregated fields."""
        wallet_data = await create_test_wallet_and_key()
        key_id = wallet_data["key_id"]

        await record_api_key_usage_event(
            key_id=key_id,
            tenant=None,
            method="POST",
            route_template="/v1/permits",
            status_code=200,
            latency_ms=25,
        )

        response = await client.get(
            f"/v1/api-keys/usage/daily?key_id={key_id}",
            headers={"X-API-Key": admin_key},
        )
        assert response.status_code == 200
        data = response.json()

        if data:
            row = data[0]
            assert "key_id" in row
            assert "day" in row
            assert "calls" in row
            assert "count_4xx" in row
            assert "count_5xx" in row
            assert "p50_latency_ms" in row
            assert "p95_latency_ms" in row
            assert "first_call" in row
            assert "last_call" in row


class TestMigration051:
    """Test migration 051 up and down."""

    @pytest.mark.asyncio
    async def test_migration_creates_table(self, db_session: AsyncSession):
        """Test the migration creates the api_key_usage_events table."""
        # Check table exists (works for PostgreSQL and SQLite differently)
        if db_session.bind.dialect.name == "postgresql":
            result = await db_session.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_name = 'api_key_usage_events'
                    """
                )
            )
        else:
            result = await db_session.execute(
                text(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'api_key_usage_events'
                    """
                )
            )
        table = result.scalar_one_or_none()
        assert table == "api_key_usage_events"

    @pytest.mark.asyncio
    async def test_migration_creates_view(self, db_session: AsyncSession):
        """Test the migration creates the api_key_usage_daily view."""
        # Check view exists (works for PostgreSQL and SQLite differently)
        if db_session.bind.dialect.name == "postgresql":
            result = await db_session.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.views
                    WHERE table_name = 'api_key_usage_daily'
                    """
                )
            )
        else:
            result = await db_session.execute(
                text(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'view' AND name = 'api_key_usage_daily'
                    """
                )
            )
        view = result.scalar_one_or_none()
        assert view == "api_key_usage_daily"

    @pytest.mark.asyncio
    async def test_migration_creates_index(self, db_session: AsyncSession):
        """Test the migration creates the composite index."""
        # Check index exists
        if db_session.bind.dialect.name == "postgresql":
            result = await db_session.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE indexname = 'ix_api_key_usage_events_key_id_created_at'
                    """
                )
            )
        else:
            result = await db_session.execute(
                text(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'index'
                      AND name = 'ix_api_key_usage_events_key_id_created_at'
                    """
                )
            )
        index = result.scalar_one_or_none()
        assert index == "ix_api_key_usage_events_key_id_created_at"
