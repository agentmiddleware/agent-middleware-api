"""Operator bounds on partner_api_key_bootstrap: --daily-limit,
--expires-in-days, --max-uses reach the right request bodies, and stay
absent when not requested (so older servers see unchanged payloads)."""

from __future__ import annotations

import scripts.partner_api_key_bootstrap as bootstrap


class _FakeResponse:
    def __init__(self, payload: dict):
        self.status_code = 200
        self._payload = payload
        self.text = ""

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Stands in for httpx.Client; records every POST body by path."""

    def __init__(self, **kwargs):
        self.posts: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, path):
        return _FakeResponse({})

    def post(self, path, json):
        self.posts.append((path, json))
        if path == "/v1/billing/wallets/sponsor":
            return _FakeResponse({"wallet_id": "wal_sponsor"})
        if path == "/v1/billing/wallets/agent":
            return _FakeResponse({"wallet_id": "wal_agent"})
        return _FakeResponse(
            {"api_key": "b2a_test", "key_id": "key_1", "key_prefix": "b2a_test"}
        )


def _provision(monkeypatch, **overrides):
    captured = {}

    def factory(**kwargs):
        client = _FakeClient(**kwargs)
        captured["client"] = client
        return client

    monkeypatch.setattr(bootstrap.httpx, "Client", factory)
    result = bootstrap.provision(
        api_url="https://api.example.test",
        bootstrap_key="amw_live_test",
        sponsor_name="Partner Co",
        agent_id="partner-agent-001",
        budget_credits=1000.0,
        initial_credits=10000.0,
        key_name="partner-agent",
        sponsor_wallet_id=None,
        agent_wallet_id=None,
        **overrides,
    )
    return result, dict(captured["client"].posts)


def test_bounds_flags_reach_request_bodies(monkeypatch):
    result, posts = _provision(
        monkeypatch,
        daily_limit=250.0,
        expires_in_days=30,
        max_uses=1000,
    )
    assert posts["/v1/billing/wallets/agent"]["daily_limit"] == 250.0
    assert posts["/v1/api-keys"]["expires_in_days"] == 30
    assert posts["/v1/api-keys"]["max_uses"] == 1000
    assert result["api_key"] == "b2a_test"


def test_bounds_default_to_absent(monkeypatch):
    _, posts = _provision(monkeypatch)
    assert "daily_limit" not in posts["/v1/billing/wallets/agent"]
    assert "expires_in_days" not in posts["/v1/api-keys"]
    assert "max_uses" not in posts["/v1/api-keys"]
