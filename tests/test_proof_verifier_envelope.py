"""The standalone site/proof/verify_receipt.py accepts the bounded signing
envelope exactly as b2a_sdk.receipt_verifier does.

Signing inputs over 4096 bytes may carry a signature tagged
``Ed25519-sha256-envelope:`` that covers the canonical
``{alg, kid, payload_sha256}`` record instead of the payload. Smaller inputs
keep the untagged direct signature, and an envelope on them is rejected.
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("cryptography", reason="verifier needs it")
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives.serialization import (  # noqa: E402
    Encoding,
    PublicFormat,
)

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "site" / "proof" / "verify_receipt.py"
KID = "proof-envelope-test"
ENVELOPE_ALG = "Ed25519-sha256-envelope"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _signing_input(padding: int) -> str:
    payload: dict[str, Any] = {
        "alg": "Ed25519",
        "canonicalization": "awi-canonical-json/1",
        "kid": KID,
        "receipt_id": "rcpt_envelope_test",
        "permit_id": "pmt_envelope_test",
        "tool": "demo.echo",
        "outcome": "succeeded",
        "constraints_evaluated": {"note": "x" * padding},
    }
    payload["payload_hash"] = hashlib.sha256(_canonical(payload).encode()).hexdigest()
    return _canonical(payload)


def _sign(key: Ed25519PrivateKey, signing_input: str, envelope: bool) -> str:
    data = signing_input.encode()
    if not envelope:
        return base64.b64encode(key.sign(data)).decode()
    record = {
        "alg": ENVELOPE_ALG,
        "kid": KID,
        "payload_sha256": hashlib.sha256(data).hexdigest(),
    }
    signature = key.sign(_canonical(record).encode())
    return f"{ENVELOPE_ALG}:{base64.b64encode(signature).decode()}"


def _key_document(key: Ed25519PrivateKey) -> dict[str, Any]:
    raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {"keys": [{"kid": KID, "public_key_b64": base64.b64encode(raw).decode()}]}


def _bundle(signing_input: str, signature: str) -> dict[str, Any]:
    return {
        "kid": KID,
        "alg": "Ed25519",
        "receipt_id": "rcpt_envelope_test",
        "signing_input": signing_input,
        "signature": signature,
    }


def _run(tmp_path: Path, bundle: dict[str, Any], keys: dict[str, Any]):
    bundle_path = tmp_path / "bundle.json"
    keys_path = tmp_path / "keys.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    keys_path.write_text(json.dumps(keys), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--bundle",
            str(bundle_path),
            "--keys",
            str(keys_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _cases() -> list[tuple[str, dict[str, Any], dict[str, Any], int]]:
    key = Ed25519PrivateKey.generate()
    other = Ed25519PrivateKey.generate()
    keys = _key_document(key)
    small = _signing_input(100)
    large = _signing_input(8000)
    assert len(small.encode()) <= 4096 < len(large.encode())

    tampered = json.loads(large)
    tampered["outcome"] = "failed"
    tampered_input = _canonical(tampered)
    envelope_sig = _sign(key, large, envelope=True)

    return [
        ("small-direct", _bundle(small, _sign(key, small, False)), keys, 0),
        ("large-direct", _bundle(large, _sign(key, large, False)), keys, 0),
        ("large-envelope", _bundle(large, envelope_sig), keys, 0),
        ("large-envelope-tampered", _bundle(tampered_input, envelope_sig), keys, 1),
        (
            "large-envelope-wrong-key",
            _bundle(large, _sign(other, large, envelope=True)),
            keys,
            1,
        ),
        ("small-direct-wrong-key", _bundle(small, _sign(other, small, False)), keys, 1),
        # An envelope on an input small enough to sign directly is refused
        # even with a valid signature: one valid form per small artifact.
        ("small-envelope", _bundle(small, _sign(key, small, envelope=True)), keys, 1),
        # The envelope signature does not double as a direct one, or back.
        (
            "large-envelope-sig-untagged",
            _bundle(large, envelope_sig.split(":", 1)[1]),
            keys,
            1,
        ),
        (
            "large-direct-sig-tagged",
            _bundle(large, f"{ENVELOPE_ALG}:" + _sign(key, large, False)),
            keys,
            1,
        ),
        (
            "unknown-tag",
            _bundle(large, "Ed25519ph:" + envelope_sig.split(":", 1)[1]),
            keys,
            2,
        ),
    ]


CASES = _cases()


@pytest.mark.parametrize(
    ("bundle", "keys", "expected_exit"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_standalone_verifier_envelope(tmp_path, bundle, keys, expected_exit) -> None:
    result = _run(tmp_path, bundle, keys)
    assert result.returncode == expected_exit, (result.returncode, result.stderr)
    if expected_exit == 0:
        assert result.stdout.startswith("VERIFIED")


@pytest.mark.parametrize(
    ("bundle", "keys", "expected_exit"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_standalone_envelope_agrees_with_sdk(bundle, keys, expected_exit) -> None:
    sdk = pytest.importorskip("b2a_sdk.receipt_verifier")
    result = sdk.verify_bundle(bundle, sdk.key_set_from_document(keys))
    sdk_exit = 0 if result.ok else (1 if result.is_rejected else 2)
    assert sdk_exit == expected_exit, (result.status, result.reason)
