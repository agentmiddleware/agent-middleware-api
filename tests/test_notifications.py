"""Focused tests for app.services.notifications.NotificationService.

Uses httpx.MockTransport so no real network or external service is touched.
"""

import json
from decimal import Decimal

import httpx
import pytest

from app.services.notifications import (
    NotificationService,
    _failure_status,
    get_notification_service,
)


def _make_service(
    handler, slack_url="https://hooks.slack.com/services/T/B/K", api_key="re_test_key"
):
    service = NotificationService()
    service._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service._slack_webhook_url = slack_url
    service._resend_api_key = api_key
    return service


@pytest.mark.anyio
async def test_wallet_frozen_alert_sends_slack_with_mapped_reason():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    service = _make_service(handler)
    try:
        await service.send_wallet_frozen_alert(
            wallet_id="w-1",
            reason="anomalous_spend",
            sponsor_email=None,
        )
    finally:
        await service.close()

    assert len(seen) == 1
    payload = json.loads(seen[0].content.decode())
    assert "w-1" in payload["text"]
    assert ":rotating_light:" in payload["text"]
    section_text = payload["blocks"][1]["text"]["text"]
    assert section_text == "Anomalous spend velocity detected"


@pytest.mark.anyio
async def test_wallet_frozen_alert_unknown_reason_and_email_body():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    service = _make_service(handler)
    try:
        await service.send_wallet_frozen_alert(
            wallet_id="w-2",
            reason="something_new",
            sponsor_email="sponsor@example.com",
        )
    finally:
        await service.close()

    assert len(seen) == 2
    slack_payload = json.loads(seen[0].content.decode())
    assert slack_payload["blocks"][1]["text"]["text"] == "Wallet frozen: something_new"
    email_payload = json.loads(seen[1].content.decode())
    assert seen[1].url.host == "api.resend.com"
    assert email_payload["to"] == "sponsor@example.com"
    assert "w-2" in email_payload["text"]
    assert "N/A" in email_payload["text"]


@pytest.mark.anyio
async def test_low_balance_warning_sends_slack_and_email():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    service = _make_service(handler)
    try:
        await service.send_low_balance_warning(
            wallet_id="w-3",
            current_balance=Decimal("100"),
            threshold=Decimal("500"),
            sponsor_email="owner@example.com",
        )
    finally:
        await service.close()

    assert len(seen) == 2
    slack_payload = json.loads(seen[0].content.decode())
    assert ":warning:" in slack_payload["text"]
    assert "100" in slack_payload["blocks"][1]["text"]["text"]
    email_payload = json.loads(seen[1].content.decode())
    assert email_payload["subject"].startswith("[B2A] Low Balance Warning")


@pytest.mark.anyio
async def test_payment_failed_alert_is_slack_only_with_intent_id():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    service = _make_service(handler)
    try:
        await service.send_payment_failed_alert(
            wallet_id="w-4",
            error_message="card declined",
            payment_intent_id="pi_123",
        )
    finally:
        await service.close()

    assert len(seen) == 1
    payload = json.loads(seen[0].content.decode())
    context_texts = [e["text"] for e in payload["blocks"][2]["elements"]]
    assert any("pi_123" in t for t in context_texts)
    assert any("w-4" in t for t in context_texts)


@pytest.mark.anyio
async def test_kyc_rejected_alert_sends_both_channels():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    service = _make_service(handler)
    try:
        await service.send_kyc_rejected_alert(
            wallet_id="w-5",
            reason="blurry document",
            sponsor_email="owner@example.com",
        )
    finally:
        await service.close()

    assert len(seen) == 2
    slack_payload = json.loads(seen[0].content.decode())
    assert "blurry document" in slack_payload["blocks"][1]["text"]["text"]
    email_payload = json.loads(seen[1].content.decode())
    assert "blurry document" in email_payload["text"]


@pytest.mark.anyio
async def test_send_email_includes_html_and_from():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["authorization"] == "Bearer re_test_key"
        return httpx.Response(200, json={"id": "msg-1"})

    service = _make_service(handler)
    try:
        await service.send_email(
            to="a@example.com",
            subject="hello",
            body="plain",
            html="<p>plain</p>",
        )
    finally:
        await service.close()

    assert len(seen) == 1
    payload = json.loads(seen[0].content.decode())
    assert payload["text"] == "plain"
    assert payload["html"] == "<p>plain</p>"
    assert payload["from"] == service._from_email


@pytest.mark.anyio
async def test_security_alert_sends_slack_only():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    service = _make_service(handler)
    try:
        await service.send_security_alert(
            wallet_id="w-6",
            alert_type="api_key_leaked",
            message="key seen in logs",
        )
    finally:
        await service.close()

    assert len(seen) == 1
    payload = json.loads(seen[0].content.decode())
    assert "Api Key Leaked" in payload["text"]
    assert payload["blocks"][1]["text"]["text"] == "key seen in logs"


@pytest.mark.anyio
async def test_no_channels_configured_sends_nothing():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    service = _make_service(handler, slack_url="", api_key="")
    try:
        await service.send_wallet_frozen_alert(wallet_id="w-7", reason="fraud_detected")
        await service.send_low_balance_warning(
            wallet_id="w-7",
            current_balance=Decimal("1"),
            threshold=Decimal("10"),
        )
        await service.send_payment_failed_alert(
            wallet_id="w-7", error_message="x", payment_intent_id="pi_x"
        )
        await service.send_email(to="a@example.com", subject="s", body="b")
    finally:
        await service.close()

    assert seen == []


@pytest.mark.anyio
async def test_failed_sends_are_swallowed_not_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    service = _make_service(handler)
    try:
        await service.send_wallet_frozen_alert(
            wallet_id="w-8",
            reason="manual_freeze",
            sponsor_email="sponsor@example.com",
        )
        await service.send_payment_failed_alert(
            wallet_id="w-8", error_message="e", payment_intent_id="pi_8"
        )
    finally:
        await service.close()


def test_failure_status_helper():
    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(503, request=request)
    err = httpx.HTTPStatusError("err", request=request, response=response)
    assert _failure_status(err) == 503
    assert _failure_status(ValueError("nope")) is None


def test_get_notification_service_singleton():
    first = get_notification_service()
    second = get_notification_service()
    assert first is second
