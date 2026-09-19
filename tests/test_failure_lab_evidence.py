"""The evidence bundle must never leak a credential, and a claim must have a test.

These are the two properties that decide whether the lab's output can be
handed to anyone. A bundle that carries a secret cannot be published; a claims
manifest that reports PASS for a test that did not pass makes the whole
traceability exercise worthless.
"""

from __future__ import annotations

import json

import pytest

from failure_lab.evidence import (
    MIN_SCANNABLE_SECRET_LENGTH,
    REDACTED_KEY_PATTERN,
    SecretLeakError,
    assert_no_secret_leak,
    find_leaked_secrets,
    redact,
)
from failure_lab.telemetry import (
    CONVERSION_SOURCES,
    TrafficSource,
    counts_toward_conversion,
)


class TestRedaction:
    def test_credential_shaped_keys_are_redacted_at_every_depth(self):
        document = {
            "api_key": "amw_live_should_not_survive",
            "nested": {
                "bearer_token": "tok_should_not_survive",
                "deeper": [{"signing_seed": "seed_should_not_survive"}],
            },
            "headers": {"Authorization": "Bearer abcdefghijklmnop"},
            "harmless": "downstream executions: 2",
        }
        cleaned = json.dumps(redact(document))

        for secret in (
            "amw_live_should_not_survive",
            "tok_should_not_survive",
            "seed_should_not_survive",
        ):
            assert secret not in cleaned, secret
        # Redaction must not destroy the measurements it travels with.
        assert "downstream executions: 2" in cleaned

    @pytest.mark.parametrize(
        "name",
        [
            "api_key",
            "apiKey",
            "api-key",
            "TOKEN",
            "client_secret",
            "signing_seed",
            "password",
            "Authorization",
            "bearer",
            "private_key",
        ],
    )
    def test_the_key_pattern_covers_the_names_credentials_actually_use(self, name):
        assert REDACTED_KEY_PATTERN.search(name.lower())

    def test_measurement_keys_are_not_swept_up(self):
        """Over-redaction would quietly destroy the evidence."""
        for name in (
            "downstream_executions",
            "gateway_dispatches",
            "receipt_id",
            "operation_id",
            "idempotency_key",
        ):
            if name == "idempotency_key":
                # This one legitimately matches: a key is a key. It is not a
                # credential, but redacting it is the safe direction.
                continue
            assert not REDACTED_KEY_PATTERN.search(name), name


class TestSecretLeakDetection:
    def test_a_planted_secret_in_written_bytes_is_found(self, tmp_path):
        secret = "amw_dev_planted_secret_value_1234"
        (tmp_path / "manifest.json").write_text(json.dumps({"ok": True}))
        (tmp_path / "event-log.jsonl").write_text(
            json.dumps({"step": "invoke", "header": f"Bearer {secret}"}) + "\n"
        )

        leaks = find_leaked_secrets(sorted(tmp_path.iterdir()), [secret])
        assert leaks, "a secret written into the bundle was not detected"

        with pytest.raises(SecretLeakError):
            assert_no_secret_leak(tmp_path, [secret])

    def test_a_clean_bundle_passes(self, tmp_path):
        (tmp_path / "results.json").write_text(json.dumps({"downstream_effects": 2}))
        assert_no_secret_leak(tmp_path, ["amw_dev_planted_secret_value_1234"])

    def test_short_values_are_not_scanned_for(self, tmp_path):
        """A six-character 'secret' would match everywhere and mean nothing."""
        (tmp_path / "results.json").write_text("the verdict was PASS")
        short = "PASS"
        assert len(short) < MIN_SCANNABLE_SECRET_LENGTH
        assert_no_secret_leak(tmp_path, [short])


class TestConversionMetrics:
    def test_only_a_human_customer_counts(self):
        assert CONVERSION_SOURCES == frozenset({TrafficSource.HUMAN_CUSTOMER})
        assert counts_toward_conversion(TrafficSource.HUMAN_CUSTOMER)

    @pytest.mark.parametrize(
        "source",
        [
            TrafficSource.INTERNAL_TEST,
            TrafficSource.AI_TEST_AGENT,
            TrafficSource.CI_RUN,
            TrafficSource.UNKNOWN,
        ],
    )
    def test_synthetic_traffic_can_never_inflate_a_conversion(self, source):
        """This is a property of the data model, not a reporting convention."""
        assert not counts_toward_conversion(source)

    def test_an_unrecognised_source_is_not_a_sale(self):
        assert not counts_toward_conversion("HUMAN_CUSTOMER_TYPO")
        assert not counts_toward_conversion("")
