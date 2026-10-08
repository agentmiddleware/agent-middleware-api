"""Startup posture summary for the human approval (Sentinel) gate.

The boot log must name the active approval mode and which Sentinel settings
are still missing, so an operator can see from one line why approval gated
permits would fail closed. The summary must never carry key material.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.services.human_approval import describe_human_approval_posture


def _configure(monkeypatch, *, simulated, url, key, environment="local"):
    settings = get_settings()
    monkeypatch.setattr(settings, "SIMULATION_MODE_HUMAN_APPROVAL", simulated)
    monkeypatch.setattr(settings, "SENTINEL_API_URL", url)
    monkeypatch.setattr(settings, "SENTINEL_API_KEY", key)
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    monkeypatch.setattr(settings, "SENTINEL_WAIT_SECONDS", 0.0)
    return settings


def test_simulated_local_reports_simulated_mode(monkeypatch):
    _configure(monkeypatch, simulated=True, url="", key="")
    posture = describe_human_approval_posture()
    assert posture["mode"] == "simulated"
    assert posture["failure_reason"] is None
    assert posture["sentinel_url_configured"] is False
    assert posture["sentinel_key_configured"] is False


def test_simulated_production_like_reports_blocked(monkeypatch):
    _configure(monkeypatch, simulated=True, url="", key="", environment="production")
    posture = describe_human_approval_posture()
    assert posture["mode"] == "simulated_blocked"
    assert posture["failure_reason"] == "human_approval_not_configured"


def test_configured_real_mode_reports_live(monkeypatch):
    _configure(
        monkeypatch,
        simulated=False,
        url="https://sentinel.test",
        key="sk_test_" + "0" * 64,
    )
    posture = describe_human_approval_posture()
    assert posture["mode"] == "live"
    assert posture["failure_reason"] is None
    assert posture["sentinel_url_configured"] is True
    assert posture["sentinel_key_configured"] is True
    assert posture["sentinel_origin_valid"] is True


def test_unconfigured_real_mode_reports_unconfigured(monkeypatch):
    _configure(monkeypatch, simulated=False, url="", key="")
    posture = describe_human_approval_posture()
    assert posture["mode"] == "unconfigured"
    assert posture["failure_reason"] == "human_approval_not_configured"


def test_unsafe_origin_reports_invalid_but_modes_fail_closed(monkeypatch):
    _configure(
        monkeypatch,
        simulated=False,
        url="http://sentinel.test/collect",
        key="sk_test_" + "0" * 64,
    )
    posture = describe_human_approval_posture()
    assert posture["sentinel_origin_valid"] is False
    assert posture["mode"] == "unconfigured"


def test_posture_never_carries_key_material(monkeypatch):
    secret_url = "https://sentinel.test"
    secret_key = "sk_live_" + "9" * 64
    _configure(monkeypatch, simulated=False, url=secret_url, key=secret_key)
    posture = describe_human_approval_posture()
    rendered = " ".join(str(value) for value in posture.values())
    assert secret_key not in rendered
    assert secret_url not in rendered
