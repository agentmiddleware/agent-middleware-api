"""OpenAPI servers must never advertise a domain the operator did not set."""

from pathlib import Path

from app.core.config import get_settings
from app.main import _openapi_servers, app

REPO_ROOT = Path(__file__).resolve().parents[1]
_UNCONFIGURED_DOMAIN = "https://api.thisisatest.tech"


def test_openapi_servers_omit_public_entry_when_public_url_unset() -> None:
    assert _openapi_servers("", "local") == [
        {"url": "http://localhost:8000", "description": "Local Development"}
    ]
    assert _openapi_servers("   ", "local") == [
        {"url": "http://localhost:8000", "description": "Local Development"}
    ]


def test_openapi_servers_use_configured_public_url() -> None:
    assert _openapi_servers("https://api.example.com", "local") == [
        {"url": "https://api.example.com", "description": "Public API"},
        {"url": "http://localhost:8000", "description": "Local Development"},
    ]
    assert _openapi_servers("https://api.example.com", "production") == [
        {"url": "https://api.example.com", "description": "Public API"}
    ]


def test_built_openapi_document_advertises_no_unconfigured_domain() -> None:
    public_url = (get_settings().PUBLIC_URL or "").strip()
    urls = [entry["url"] for entry in app.openapi().get("servers", [])]
    if public_url:
        assert urls[0] == public_url
    else:
        assert _UNCONFIGURED_DOMAIN not in urls


def test_shutdown_settle_delay_does_not_claim_request_draining() -> None:
    assert (
        "Allow in-flight requests to drain"
        not in (REPO_ROOT / "app" / "main.py").read_text()
    )
