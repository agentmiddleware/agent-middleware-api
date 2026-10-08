"""Pattern 11: secrets share one handling standard.

Covers the shared mechanism in app.core.secrets and each site that adopts
it: the jev redaction helpers, the war-room bootstrap-key flag, and the
preflight Stripe key field.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core import secrets as shared
from app.main import app
from app.policy import jev_guard
from app.routers.preflight import PreflightRequest

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str, filename: str):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "secret",
    [
        "sk_live_abcdefghijklmnopqrstuv",
        "sk_test_abcdefghijklmnopqrstuv",
        "ghp_ZZZZZZZZZZZZZZZZZZZZZZZZ",
        "xoxb-123456789012-abcdefghij",
        "AKIAIIIIIIIIIIIIIIII",
        "api_key=supersecretvalue123",
        "password: hunter2-hunter2-hunter2",
        "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        "0123456789abcdef0123456789abcdef",
    ],
)
def test_redact_text_removes_known_secret_shapes(secret):
    rendered = shared.redact_text(f"call failed for {secret} retrying")
    assert secret not in rendered
    assert shared.REDACTED in rendered


def test_redact_text_leaves_plain_text_alone():
    message = "Wallet frozen: anomalous_spend velocity detected"
    assert shared.redact_text(message) == message


def test_redact_text_removes_exact_known_secrets():
    minted = "b2a_test_minted_key_value"
    assert minted not in shared.redact_text(f"stored {minted}", extra=(minted,))


def test_jev_guard_uses_the_single_shared_pattern_copy():
    assert jev_guard.SECRET_PATTERNS is shared.SECRET_PATTERNS
    sample = "token=abc ghp_ZZZZZZZZZZZZZZZZZZZZZZZZ"
    assert jev_guard.strip_secrets(sample) == shared.redact_text(sample)


def test_review_script_uses_the_single_shared_pattern_copy():
    review = _load_script("jev_review", "jev_codebase_review.py")
    assert review.SECRET_PATTERNS is shared.SECRET_PATTERNS
    sample = "password: hunter2-hunter2-hunter2 done"
    assert review.strip_secrets(sample) == shared.redact_text(sample)


def test_mask_secret_hides_the_middle():
    raw = "b2a_abcdefghijklmnopqr stu"
    masked = shared.mask_secret(raw)
    assert raw not in masked
    assert masked.startswith("b2a_ab")
    assert masked.endswith(" stu"[-4:])


def test_mask_secret_accepts_secret_str_and_empty():
    assert (
        shared.mask_secret(SecretStr("b2a_abcdefghijklmnop")) != "b2a_abcdefghijklmnop"
    )
    assert shared.mask_secret("") == "<none>"
    assert shared.mask_secret(None) == "<none>"


def test_resolve_secret_prefers_environment(monkeypatch, capsys):
    monkeypatch.setenv("PAT11_KEY", "env-value")
    assert (
        shared.resolve_secret(
            env_name="PAT11_KEY",
            cli_value="cli-value",
            description="test key",
        )
        == "env-value"
    )
    assert "warning" not in capsys.readouterr().err


def test_resolve_secret_warns_on_command_line_value(monkeypatch, capsys):
    monkeypatch.delenv("PAT11_KEY", raising=False)
    assert (
        shared.resolve_secret(
            env_name="PAT11_KEY",
            cli_value="cli-value",
            description="test key",
            required=False,
        )
        == "cli-value"
    )
    assert "PAT11_KEY" in capsys.readouterr().err


def test_resolve_secret_missing_required_raises(monkeypatch):
    monkeypatch.delenv("PAT11_KEY", raising=False)
    with pytest.raises(SystemExit):
        shared.resolve_secret(env_name="PAT11_KEY", description="test key")
    assert (
        shared.resolve_secret(
            env_name="PAT11_KEY", description="test key", required=False
        )
        == ""
    )


def test_war_room_bootstrap_key_prefers_environment(monkeypatch, capsys):
    war_room = _load_script("war_room", "agent_ops_war_room_demo.py")
    monkeypatch.setenv("BOOTSTRAP_API_KEY", "env-bootstrap-key")
    assert war_room.resolve_bootstrap_api_key("flag-key") == "env-bootstrap-key"
    assert "warning" not in capsys.readouterr().err


def test_war_room_bootstrap_key_falls_back_to_local_default(monkeypatch, capsys):
    war_room = _load_script("war_room", "agent_ops_war_room_demo.py")
    monkeypatch.delenv("BOOTSTRAP_API_KEY", raising=False)
    assert war_room.resolve_bootstrap_api_key(None) == war_room.LOCAL_BOOTSTRAP_API_KEY
    assert war_room.resolve_bootstrap_api_key("flag-key") == "flag-key"
    assert "BOOTSTRAP_API_KEY" in capsys.readouterr().err


def test_preflight_request_masks_stripe_key_in_repr():
    raw = "sk_live_abc123xyz456moresecret"
    request = PreflightRequest(stripe_secret_key=raw)
    assert raw not in repr(request)
    assert request.stripe_secret_key.get_secret_value() == raw


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_preflight_response_never_echoes_stripe_key(client):
    raw = "sk_live_abc123xyz456moresecret"
    resp = await client.post(
        "/v1/launch/preflight",
        json={"stripe_secret_key": raw},
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 200
    assert raw not in resp.text
