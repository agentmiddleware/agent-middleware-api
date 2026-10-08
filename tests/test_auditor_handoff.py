"""Pin the auditor handoff and the verify endpoint's stated scope.

The go-to-market review found two evidence problems: no one page told an
auditor which files to ask for and what each result means, and the server
verify endpoint's `valid: true` reads as full validity while it checks the
receipt signature only. This pins both fixes: the handoff document must name
the real endpoints and commands, and the verify route must state its
signature-only scope in its served OpenAPI description.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HANDOFF = REPO_ROOT / "docs" / "auditor-handoff.md"


def test_handoff_document_exists() -> None:
    assert HANDOFF.is_file(), (
        "docs/auditor-handoff.md must exist: it is the one page handed to an "
        "auditor with a portable receipt bundle."
    )


def test_handoff_names_the_real_handoff_artifacts() -> None:
    text = HANDOFF.read_text(encoding="utf-8")
    for anchor in (
        "/v1/receipts/{receipt_id}/portable",
        "/.well-known/trust-keys.json",
        "b2a-verify-receipt",
        "signing_input",
    ):
        assert anchor in text, (
            f"auditor handoff should name {anchor} so the auditor gets working "
            "files and commands, not stale pointers."
        )


def test_handoff_states_the_honest_limits() -> None:
    text = HANDOFF.read_text(encoding="utf-8").lower()
    for anchor in (
        "revocation",
        "verbatim",
        "retired",
        "disabled",
    ):
        assert anchor in text, (
            f"auditor handoff should state the limit around {anchor}: an "
            "auditor who is not told will misread a valid check."
        )


def test_verify_endpoint_states_signature_only_scope() -> None:
    from app.main import app

    spec = app.openapi()
    operation = spec["paths"]["/v1/receipts/verify"]["post"]
    description = operation.get("description", "")
    assert "signature only" in description, (
        "POST /v1/receipts/verify must say it checks the receipt signature "
        "only, so a valid result is not misread as full evidence validity."
    )
    assert "/v1/evidence/" in description or "/evidence" in description, (
        "POST /v1/receipts/verify must point at the evidence endpoints for "
        "the chained permit, ledger, audit, and dispatch checks."
    )
