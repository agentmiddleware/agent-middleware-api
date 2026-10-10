"""A diagnostic mounted beyond loopback must demand a token.

``serve`` refuses a non-loopback bind unless a token is configured, and the
app requires that token on every route when one is set. The loopback default
stays open (no token configured, no check), so existing behavior is
unchanged for the local case.
"""

from __future__ import annotations

import sys
import types

import pytest
from starlette.testclient import TestClient

from failure_lab.diagnostic import DiagnosticSettings, create_app
from failure_lab.diagnostic.server import main, serve

TOKEN = "test-diagnostic-token-0123456789"


def _client(**kwargs) -> TestClient:
    return TestClient(create_app(DiagnosticSettings(telemetry=False, **kwargs)))


def test_serve_refuses_non_loopback_without_a_token():
    for host in ("0.0.0.0", "192.168.1.5", "", "::"):
        with pytest.raises(ValueError, match="refusing to bind"):
            serve(host=host, port=8080)


def test_serve_allows_non_loopback_with_a_token(monkeypatch):
    calls: dict = {}

    def fake_run(app, *, host, port, log_level):  # noqa: ANN001, ANN202
        calls["host"] = host
        calls["port"] = port

    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = fake_run
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    assert serve(host="0.0.0.0", port=8099, auth_token=TOKEN) == 0
    assert calls == {"host": "0.0.0.0", "port": 8099}


def test_main_refuses_non_loopback_without_a_token():
    assert main(["--host", "0.0.0.0", "--port", "8099"]) == 2


def test_main_accepts_token_flag_and_env(monkeypatch):
    calls: dict = {}

    def fake_run(app, *, host, port, log_level):  # noqa: ANN001, ANN202
        calls["host"] = host

    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = fake_run
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    assert main(["--host", "0.0.0.0", "--port", "8099", "--auth-token", TOKEN]) == 0
    assert calls == {"host": "0.0.0.0"}

    monkeypatch.setenv("FAILURE_LAB_DIAGNOSTIC_TOKEN", TOKEN)
    assert main(["--host", "0.0.0.0", "--port", "8099"]) == 0


def test_app_without_a_token_stays_open():
    with _client() as client:
        assert client.get("/diagnostic").status_code == 200
        assert client.get("/healthz").status_code == 200


def test_app_with_a_token_rejects_anonymous_requests():
    with _client(auth_token=TOKEN) as client:
        for method, path in (
            ("GET", "/"),
            ("GET", "/diagnostic"),
            ("GET", "/healthz"),
            ("GET", "/diagnostic/deployment"),
            ("POST", "/diagnostic/run"),
        ):
            response = client.request(method, path, json={})
            assert response.status_code == 401, (method, path)


def test_app_with_a_token_rejects_wrong_tokens():
    with _client(auth_token=TOKEN) as client:
        assert (
            client.get(
                "/healthz", headers={"Authorization": "Bearer wrong-token"}
            ).status_code
            == 401
        )
        assert (
            client.get("/healthz", headers={"Authorization": TOKEN}).status_code == 401
        )
        assert client.get("/healthz").status_code == 401


def test_app_with_a_token_accepts_the_configured_bearer_token():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with _client(auth_token=TOKEN) as client:
        assert client.get("/diagnostic", headers=headers).status_code == 200
        assert client.get("/healthz", headers=headers).status_code == 200
