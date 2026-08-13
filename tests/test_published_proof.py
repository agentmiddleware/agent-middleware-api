"""The marketing proof must remain cryptographically consistent and exact."""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

from b2a_sdk.receipt_verifier import (
    VerificationStatus,
    key_set_from_document,
    verify_bundle,
)
from b2a_sdk.verify_cli import main as verify_cli


ROOT = Path(__file__).resolve().parents[1]
RECEIPT_PATH = ROOT / "site" / "proof" / "receipt.json"
KEYS_PATH = ROOT / "site" / "proof" / "trust-keys.json"
EXPECTED_ISSUER = "https://api.thisisatest.tech"


def _artifacts() -> tuple[dict, dict]:
    return (
        json.loads(RECEIPT_PATH.read_text(encoding="utf-8")),
        json.loads(KEYS_PATH.read_text(encoding="utf-8")),
    )


def test_published_live_receipt_verifies_fully_offline() -> None:
    bundle, key_document = _artifacts()

    result = verify_bundle(
        bundle,
        key_set_from_document(key_document),
        expected_issuer=EXPECTED_ISSUER,
    )

    assert result.status is VerificationStatus.VERIFIED, result.reason
    assert result.receipt_id == "rcpt-9daf745e477d45ab"
    assert result.claims["permit_id"] == "permit-c73a0b621c244831"
    assert result.claims["tool"] == "partner.echo"
    assert result.claims["outcome"] == "success"
    assert result.claims["credits_charged"] == "1"
    assert bundle["issuer"] == key_document["issuer"] == EXPECTED_ISSUER


def test_existing_offline_cli_verifies_the_published_artifact(capsys) -> None:
    exit_code = verify_cli(
        ["--bundle", str(RECEIPT_PATH), "--keys", str(KEYS_PATH), "--json"]
    )

    assert exit_code == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["status"] == "verified"
    assert emitted["claims"]["tool"] == "partner.echo"


def test_one_byte_payload_modification_is_rejected() -> None:
    bundle, key_document = _artifacts()
    tampered = dict(bundle)
    original = tampered["signing_input"]
    tampered["signing_input"] = original.replace("partner.echo", "partner.echp", 1)
    assert len(tampered["signing_input"].encode()) == len(original.encode())

    result = verify_bundle(tampered, key_set_from_document(key_document))

    assert result.status is VerificationStatus.INVALID
    assert result.is_tampered


def test_modified_signature_is_rejected() -> None:
    bundle, key_document = _artifacts()
    tampered = dict(bundle)
    signature = tampered["signature"]
    tampered["signature"] = ("A" if signature[0] != "A" else "B") + signature[1:]

    result = verify_bundle(tampered, key_set_from_document(key_document))

    assert result.status is VerificationStatus.INVALID
    assert result.is_tampered


def test_modified_or_unexpected_issuer_is_rejected() -> None:
    bundle, key_document = _artifacts()
    relabelled = dict(bundle)
    relabelled["issuer"] = "https://attacker.example"

    result = verify_bundle(
        relabelled,
        key_set_from_document(key_document),
        expected_issuer=EXPECTED_ISSUER,
    )

    assert result.status is VerificationStatus.MISMATCH


def test_modified_public_key_is_rejected() -> None:
    bundle, key_document = _artifacts()
    wrong_keys = copy.deepcopy(key_document)
    raw = bytearray(base64.b64decode(wrong_keys["keys"][0]["public_key_b64"]))
    raw[0] ^= 0x01
    wrong_keys["keys"][0]["public_key_b64"] = base64.b64encode(raw).decode()
    wrong_keys["keys"][0].pop("jwk", None)

    result = verify_bundle(bundle, key_set_from_document(wrong_keys))

    assert result.status is VerificationStatus.INVALID
    assert result.is_tampered


def test_public_artifacts_contain_no_credentials() -> None:
    lowered = (RECEIPT_PATH.read_text() + KEYS_PATH.read_text()).casefold()
    for forbidden in ("api_key", "password", "private_key", "bearer_token"):
        assert forbidden not in lowered
