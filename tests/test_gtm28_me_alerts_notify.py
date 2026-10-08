from __future__ import annotations

import logging

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.notifications import NotificationService
from tests.test_trust_helpers import BOOTSTRAP_HEADERS, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _service_with_routes(slack_handler=None, resend_handler=None):
    """NotificationService whose HTTP calls are captured, never sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if "slack" in host:
            assert slack_handler is not None, "unexpected Slack call"
            return slack_handler(request)
        assert resend_handler is not None, f"unexpected HTTP call to {host}"
        return resend_handler(request)

    service = NotificationService()
    service._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service._slack_webhook_url = ""
    service._resend_api_key = ""
    return service


@pytest.mark.anyio
async def test_critical_urgency_renders_an_emoji():
    """emergency_key_revocation used urgency critical, which had no emoji."""
    seen = {}

    def slack(request: httpx.Request) -> httpx.Response:
        seen["payload"] = request.read().decode()
        return httpx.Response(200, text="ok")

    service = _service_with_routes(slack_handler=slack)
    service._slack_webhook_url = "https://hooks.slack.com/services/x"
    try:
        await service.send_security_alert(
            wallet_id="w1",
            alert_type="emergency_key_revocation",
            message="revoked",
        )
    finally:
        await service.close()
    assert ":bangbang:" in seen["payload"]


@pytest.mark.anyio
async def test_payment_failed_alert_emails_sponsor():
    """Payment failures previously reached Slack only, or nobody at all."""
    sent = {}

    def resend(request: httpx.Request) -> httpx.Response:
        import json

        sent["payload"] = json.loads(request.read().decode())
        return httpx.Response(200, json={"id": "email-1"})

    service = _service_with_routes(resend_handler=resend)
    service._resend_api_key = "re_test_key"
    try:
        await service.send_payment_failed_alert(
            wallet_id="w1",
            error_message="card declined",
            payment_intent_id="pi_123",
            sponsor_email="sponsor@example.com",
        )
    finally:
        await service.close()
    assert sent["payload"]["to"] == "sponsor@example.com"
    assert "pi_123" in sent["payload"]["text"]
    assert "card declined" in sent["payload"]["text"]


@pytest.mark.anyio
async def test_payment_failed_alert_skips_email_without_resend_key():
    """No Resend key means no HTTP call at all, not a failed send."""

    def fail(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"should not send: {request.url.host}")

    service = _service_with_routes(slack_handler=fail, resend_handler=fail)
    try:
        await service.send_payment_failed_alert(
            wallet_id="w1",
            error_message="card declined",
            payment_intent_id="pi_123",
            sponsor_email="sponsor@example.com",
        )
    finally:
        await service.close()


@pytest.mark.anyio
async def test_security_alert_emails_sponsor():
    """Key revocation events previously had no email path."""
    sent = {}

    def resend(request: httpx.Request) -> httpx.Response:
        import json

        sent["payload"] = json.loads(request.read().decode())
        return httpx.Response(200, json={"id": "email-1"})

    service = _service_with_routes(resend_handler=resend)
    service._resend_api_key = "re_test_key"
    try:
        await service.send_security_alert(
            wallet_id="w1",
            alert_type="emergency_key_revocation",
            message="all keys revoked",
            sponsor_email="sponsor@example.com",
        )
    finally:
        await service.close()
    assert sent["payload"]["to"] == "sponsor@example.com"
    assert "Emergency Key Revocation" in sent["payload"]["subject"]


@pytest.mark.anyio
async def test_unconfigured_service_warns_at_init(caplog):
    """Silent no-ops hid the fact that no pilot alert could ever arrive."""
    service = NotificationService()
    service._slack_webhook_url = ""
    service._resend_api_key = ""
    try:
        with caplog.at_level(logging.WARNING, logger="app.services.notifications"):
            # Re-run the misconfiguration check the constructor performs.
            NotificationService.__init__(service)
    finally:
        await service.close()
    assert "notifications_unconfigured" in caplog.text


def test_channel_status_reports_each_channel():
    service = NotificationService()
    service._slack_webhook_url = ""
    service._resend_api_key = ""
    assert service.channel_status() == {
        "slack_configured": False,
        "email_configured": False,
        "configured": False,
    }
    service._slack_webhook_url = "https://hooks.slack.com/services/x"
    assert service.channel_status()["configured"] is True
    assert service.channel_status()["email_configured"] is False


@pytest.mark.anyio
async def test_health_check_reports_notification_channels(monkeypatch):
    from app.core import health as health_module
    from app.services.notifications import get_notification_service

    service = get_notification_service()
    monkeypatch.setattr(service, "_slack_webhook_url", "")
    monkeypatch.setattr(service, "_resend_api_key", "")
    result = await health_module._check_notifications()
    assert result["status"] == "not_configured"

    monkeypatch.setattr(
        service, "_slack_webhook_url", "https://hooks.slack.com/services/x"
    )
    result = await health_module._check_notifications()
    assert result["status"] == "up"
    assert result["slack_configured"] is True
    assert result["email_configured"] is False


async def _seed_alerts(wallet_id: str, count: int) -> None:
    from app.db.database import get_session_factory
    from app.db.models import BillingAlertModel
    from app.schemas.billing import AlertType

    factory = get_session_factory()
    async with factory() as session:
        for i in range(count):
            session.add(
                BillingAlertModel(
                    alert_id=f"gtm28-{i}",
                    wallet_id=wallet_id,
                    alert_type=AlertType.LOW_BALANCE.value,
                    message=f"low balance {i}",
                    acknowledged=(i == 0),
                )
            )
        await session.commit()


@pytest.mark.anyio
async def test_me_alerts_paginate_in_query(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    await _seed_alerts(wallet_id, 5)

    first = await client.get(
        "/v1/me/alerts",
        params={"limit": 2, "offset": 0},
        headers=provisioned["agent_headers"],
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["total"] == 5
    assert first_body["unacknowledged"] == 4
    assert len(first_body["alerts"]) == 2

    second = await client.get(
        "/v1/me/alerts",
        params={"limit": 2, "offset": 2},
        headers=provisioned["agent_headers"],
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["total"] == 5
    assert len(second_body["alerts"]) == 2

    last = await client.get(
        "/v1/me/alerts",
        params={"limit": 2, "offset": 4},
        headers=provisioned["agent_headers"],
    )
    assert last.status_code == 200
    assert len(last.json()["alerts"]) == 1

    seen = first_body["alerts"] + second_body["alerts"] + last.json()["alerts"]
    assert len({a["alert_id"] for a in seen}) == 5


@pytest.mark.anyio
async def test_me_403_names_the_key_to_use(client, clean_database):
    response = await client.get("/v1/me/alerts", headers=BOOTSTRAP_HEADERS)
    assert response.status_code == 403
    body = response.json()
    assert body["detail"]["error"] == "wallet_key_required"
    assert "wallet-scoped" in body["detail"]["message"]
