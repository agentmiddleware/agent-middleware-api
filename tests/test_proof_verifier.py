"""The /proof/ page must be verifiable by a stranger: no private repo, no
PyPI package, only public downloads plus a standalone script.

Covers the standalone verifier (site/proof/verify_receipt.py) and the built
page contract: every command a stranger is told to run must run without
private access.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
VERIFIER = SITE / "proof" / "verify_receipt.py"
BUNDLE = SITE / "proof" / "receipt.json"
KEYS = SITE / "proof" / "trust-keys.json"
ISSUER = "https://api.thisisatest.tech"

CONTACTS = {
    "PUBLIC_DISPLAY_NAME": "Design Partner Labs LLC",
    "PUBLIC_CONTACT_EMAIL": "operator@design-partner-labs.org",
}


def _run_verifier(bundle: Path, keys: Path, issuer: str | None = ISSUER):
    command = [
        sys.executable,
        str(VERIFIER),
        "--bundle",
        str(bundle),
        "--keys",
        str(keys),
    ]
    if issuer is not None:
        command += ["--expect-issuer", issuer]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _needs_cryptography():
    return pytest.importorskip("cryptography", reason="verifier needs it")


def _tampered_bundle(path: Path) -> None:
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    payload = json.loads(bundle["signing_input"])
    payload["credits_charged"] = "999"
    bundle["signing_input"] = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    path.write_text(json.dumps(bundle), encoding="utf-8")


def test_verifier_accepts_published_bundle() -> None:
    _needs_cryptography()
    result = _run_verifier(BUNDLE, KEYS)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("VERIFIED")


def test_verifier_rejects_tampered_bundle(tmp_path) -> None:
    _needs_cryptography()
    tampered = tmp_path / "tampered.json"
    _tampered_bundle(tampered)
    result = _run_verifier(tampered, KEYS)
    assert result.returncode == 1, (result.returncode, result.stderr)


def test_verifier_wrong_issuer_and_missing_kid(tmp_path) -> None:
    _needs_cryptography()
    wrong_issuer = _run_verifier(BUNDLE, KEYS, issuer="https://evil.example.com")
    assert wrong_issuer.returncode == 1, (
        wrong_issuer.returncode,
        wrong_issuer.stderr,
    )
    empty_keys = tmp_path / "empty-keys.json"
    empty_keys.write_text(json.dumps({"keys": []}), encoding="utf-8")
    missing_kid = _run_verifier(BUNDLE, empty_keys)
    assert missing_kid.returncode == 2, (
        missing_kid.returncode,
        missing_kid.stderr,
    )


def test_verifier_agrees_with_sdk_verifier(tmp_path) -> None:
    b2a = pytest.importorskip("b2a_sdk.receipt_verifier")
    _needs_cryptography()
    key_document = json.loads(KEYS.read_text(encoding="utf-8"))
    key_set = b2a.key_set_from_document(key_document)

    tampered = tmp_path / "tampered.json"
    _tampered_bundle(tampered)
    tampered_bundle = json.loads(tampered.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))

    cases = [
        ("good", bundle, key_set, ISSUER),
        ("tampered", tampered_bundle, key_set, ISSUER),
        ("wrong-issuer", bundle, key_set, "https://evil.example.com"),
        ("unknown-key", bundle, {}, ISSUER),
    ]
    for name, candidate, keys, issuer in cases:
        expected = b2a.verify_bundle(candidate, keys, expected_issuer=issuer)
        expected_exit = 0 if expected.ok else (1 if expected.is_rejected else 2)
        case_bundle = tmp_path / f"{name}-bundle.json"
        case_bundle.write_text(json.dumps(candidate), encoding="utf-8")
        case_keys = tmp_path / f"{name}-keys.json"
        case_keys.write_text(
            json.dumps(
                {
                    "keys": [
                        {
                            "kid": kid,
                            "public_key_b64": __import__("base64")
                            .b64encode(raw)
                            .decode(),
                        }
                        for kid, raw in keys.items()
                    ]
                }
            ),
            encoding="utf-8",
        )
        result = _run_verifier(case_bundle, case_keys, issuer=issuer)
        assert result.returncode == expected_exit, (
            f"{name}: standalone exits {result.returncode}, "
            f"SDK maps {expected.status.value} to {expected_exit}"
        )


def _render_site(output: Path):
    environment = dict(os.environ)
    environment.update(CONTACTS)
    environment.pop("PUBLIC_BOOKING_URL", None)
    environment.pop("PUBLIC_ENABLE_VERCEL_ANALYTICS", None)
    return subprocess.run(
        [sys.executable, str(SITE / "build_site.py"), "--output", str(output)],
        cwd=SITE,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_built_proof_page_needs_no_private_access(tmp_path) -> None:
    output = tmp_path / "site"
    result = _render_site(output)
    assert result.returncode == 0, result.stderr
    proof = (output / "proof" / "index.html").read_text(encoding="utf-8")

    assert "git clone" not in proof
    assert "PetrefiedThunder" not in proof
    assert "pip install ./" not in proof
    assert "\u2014" not in proof and "\u2013" not in proof
    assert "curl -fsSLO https://www.thisisatest.tech/proof/verify_receipt.py" in proof
    assert "python3 -m pip install cryptography" in proof
    assert "python3 verify_receipt.py" in proof
    assert "--expect-issuer https://api.thisisatest.tech" in proof
    assert "b2a-verify-receipt" in proof
    assert "no account" in proof
    assert "networking disabled" in proof


def test_build_publishes_the_standalone_verifier(tmp_path) -> None:
    output = tmp_path / "site"
    result = _render_site(output)
    assert result.returncode == 0, result.stderr
    published = output / "proof" / "verify_receipt.py"
    assert published.is_file()
    assert published.read_bytes() == VERIFIER.read_bytes()

    config = json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))
    rule = next(
        entry
        for entry in config["headers"]
        if entry["source"] == "/proof/verify_receipt.py"
    )
    content_type = next(
        header["value"] for header in rule["headers"] if header["key"] == "Content-Type"
    )
    assert content_type.startswith("text/plain")
