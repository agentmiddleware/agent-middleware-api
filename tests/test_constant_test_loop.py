"""Tests for the constant smoke test loop and machine-readable bootstrap output.

Covers:
1. partner_api_key_bootstrap.py --json mode produces pipeable JSON to stdout
2. Human/status text goes to stderr, never stdout (in --json mode)
3. Bootstrap key is never printed to stdout or stderr
4. constant_test_loop.py executes the full loop against a local instance
5. API key is never logged or printed
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import runpy

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP_SCRIPT = REPO_ROOT / "scripts" / "partner_api_key_bootstrap.py"
CONSTANT_TEST_SCRIPT = REPO_ROOT / "scripts" / "constant_test_loop.py"


def _free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def test_server(tmp_path_factory):
    """Boot a minimal test server with a static dev key for bootstrap tests."""
    import base64
    import secrets
    
    state_dir = tmp_path_factory.mktemp("bootstrap-test-state")
    port = _free_port()
    static_dev_key = f"amw_dev_{secrets.token_urlsafe(32)}"
    signing_seed = base64.b64encode(secrets.token_bytes(32)).decode()
    
    # Boot uvicorn directly with minimal env for testing
    test_env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT),
        "ENVIRONMENT": "local",
        "DATABASE_URL": f"sqlite+aiosqlite:///{state_dir / 'api.db'}",
        "STATE_BACKEND": "sqlite",
        "SQLITE_URL": str(state_dir / "state.db"),
        "STATIC_DEV_API_KEYS": static_dev_key,
        "VALID_API_KEYS": "",
        "TRUST_MODE_ENABLED": "true",
        "TRUST_SIGNING_KEY_ID": "test-ed25519",
        "TRUST_SIGNING_PRIVATE_KEY_B64": signing_seed,
        "ENABLE_DEV_KEY_SELF_PROVISION": "true",
        "ENABLE_DOGFOOD_TOOL": "true",
        "MCP_UPSTREAM_ENABLED": "false",
        "ALLOW_LEGACY_UNPERMITTED_MCP": "false",
        "ENABLE_PROOF_SURFACES": "false",
    }
    
    log_path = state_dir / "server.log"
    with log_path.open("wb") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=REPO_ROOT,
            env=test_env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    "test server exited early:\n"
                    + log_path.read_text(encoding="utf-8", errors="replace")
                )
            try:
                if httpx.get(f"{base_url}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("test server never became healthy")
        yield (base_url, static_dev_key)
    finally:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)


def test_bootstrap_json_mode_produces_pipeable_stdout(test_server):
    """partner_api_key_bootstrap.py --json prints JSON to stdout, status to stderr."""
    base_url, static_dev_key = test_server
    bootstrap_key = static_dev_key

    # Run bootstrap script in --json mode
    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP_SCRIPT),
            "--api-url",
            base_url,
            "--agent-id",
            "json-test-agent",
            "--key-name",
            "json-test-key",
            "--budget-credits",
            "100",
            "--json",
        ],
        env={**os.environ, "BOOTSTRAP_KEY": bootstrap_key},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, f"bootstrap failed: {result.stderr}"

    # stdout must be valid JSON
    stdout_data = json.loads(result.stdout)
    assert "api_key" in stdout_data, "JSON output missing api_key"
    assert "wallet_id" in stdout_data or "agent_wallet_id" in stdout_data
    assert "key_id" in stdout_data

    # stderr should contain human-readable status (or be empty)
    # Key invariant: bootstrap_key must NOT appear in stdout or stderr
    assert bootstrap_key not in result.stdout, "bootstrap key leaked to stdout"
    assert bootstrap_key not in result.stderr, "bootstrap key leaked to stderr"


def test_bootstrap_json_mode_jq_pipeable(test_server):
    """--json output can be piped to `jq -r .api_key`."""
    base_url, static_dev_key = test_server
    bootstrap_key = static_dev_key

    # Run bootstrap --json and pipe to jq
    bootstrap_proc = subprocess.Popen(
        [
            sys.executable,
            str(BOOTSTRAP_SCRIPT),
            "--api-url",
            base_url,
            "--agent-id",
            "jq-pipeable-agent",
            "--key-name",
            "jq-pipeable-key",
            "--budget-credits",
            "50",
            "--json",
        ],
        env={**os.environ, "BOOTSTRAP_KEY": bootstrap_key},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    jq_proc = subprocess.Popen(
        ["jq", "-r", ".api_key"],
        stdin=bootstrap_proc.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    bootstrap_proc.stdout.close()  # type: ignore
    jq_stdout, jq_stderr = jq_proc.communicate(timeout=30)
    bootstrap_proc.wait(timeout=5)

    assert jq_proc.returncode == 0, f"jq failed: {jq_stderr}"
    extracted_key = jq_stdout.strip()
    assert extracted_key, "jq extracted empty api_key"
    # Keys can have amw_ or b2a_ prefix depending on the API version
    assert extracted_key.startswith(("amw_", "b2a_")), f"unexpected key prefix: {extracted_key[:10]}"

    # The extracted key should work - test by listing wallets
    wallets_response = httpx.get(
        f"{base_url}/v1/billing/wallets",
        headers={"X-API-Key": extracted_key},
        timeout=10,
    )
    assert wallets_response.status_code == 200, "extracted key is not valid"
    assert "wallets" in wallets_response.json(), "wallets response malformed"


def test_bootstrap_json_never_prints_bootstrap_key(test_server):
    """Bootstrap key must never appear in stdout or stderr, even in --json mode."""
    base_url, static_dev_key = test_server
    bootstrap_key = static_dev_key

    for json_flag in (True, False):
        args = [
            sys.executable,
            str(BOOTSTRAP_SCRIPT),
            "--api-url",
            base_url,
            "--agent-id",
            f"no-leak-{json_flag}",
            "--key-name",
            "no-leak-key",
            "--budget-credits",
            "10",
        ]
        if json_flag:
            args.append("--json")

        result = subprocess.run(
            args,
            env={**os.environ, "BOOTSTRAP_KEY": bootstrap_key},
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        assert bootstrap_key not in result.stdout, (
            f"bootstrap key leaked to stdout (json={json_flag})"
        )
        assert bootstrap_key not in result.stderr, (
            f"bootstrap key leaked to stderr (json={json_flag})"
        )


def test_constant_test_loop_against_local_instance(test_server):
    """constant_test_loop.py runs the full loop against a local instance."""
    base_url, _ = test_server

    # Run the constant test loop - it will self-provision its own key
    # Remove CI_SMOKE_AGENT_KEY from env so it self-provisions
    env = {k: v for k, v in os.environ.items() 
           if not k.startswith("CI_SMOKE")}
    result = subprocess.run(
        [sys.executable, str(CONSTANT_TEST_SCRIPT), "--api-url", base_url],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, (
        f"constant test loop failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "ALL INVARIANTS HELD" in result.stderr


def test_constant_test_loop_self_provisions_when_no_key_provided(test_server):
    """constant_test_loop.py self-provisions when CI_SMOKE_AGENT_KEY is not set."""
    base_url, _ = test_server
    env = {k: v for k, v in os.environ.items() 
           if not k.startswith("CI_SMOKE")}
    result = subprocess.run(
        [sys.executable, str(CONSTANT_TEST_SCRIPT), "--api-url", base_url],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, f"self-provision flow failed: {result.stderr}"
    assert "self-provisioning agent key" in result.stderr
    assert "ALL INVARIANTS HELD" in result.stderr


def test_constant_test_loop_never_logs_api_key(test_server):
    """Agent key is never printed or logged during constant test execution."""
    base_url, _ = test_server
    # Pre-provision a key to test that it's never logged
    provision_response = httpx.post(
        f"{base_url}/v1/dev-keys/self-provision",
        json={"agent_id": "no-log-test"},
        timeout=10,
    )
    assert provision_response.status_code in (200, 201)
    provision_data = provision_response.json()
    agent_key = provision_data["api_key"]
    wallet_id = provision_data["wallet_id"]
    key_id = provision_data["key_id"]

    # Run with explicit credentials
    result = subprocess.run(
        [sys.executable, str(CONSTANT_TEST_SCRIPT), "--api-url", base_url],
        env={
            **os.environ,
            "CI_SMOKE_AGENT_KEY": agent_key,
            "CI_SMOKE_WALLET_ID": wallet_id,
            "CI_SMOKE_KEY_ID": key_id,
        },
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, f"failed: {result.stderr}"
    # The agent key must never appear anywhere in the output
    assert agent_key not in result.stdout, "agent key in stdout"
    assert agent_key not in result.stderr, "agent key in stderr"


# --- Tool selection, argument derivation, and the production guards -------
#
# Ported from the scoped-smoke-loop work (#325) when the two loops were
# consolidated. These need no server, so they run in the fast path.


def _load_loop():
    return runpy.run_path(str(CONSTANT_TEST_SCRIPT))


def test_companion_tool_comes_from_the_registry_not_the_governed_name():
    """Regression: pinning the governed tool must not skip the denial check.

    Selecting the companion from the pinned value rather than the registry
    made the out-of-scope check skip silently on exactly the deployments
    where a pin is mandatory.
    """
    select = _load_loop()["select_companion_tool"]
    registry = {"alpha": {}, "beta": {}, "gamma": {}}

    companion, error = select(registry, "alpha", None)
    assert companion in {"beta", "gamma"}
    assert not error

    companion, error = select(registry, "gamma", None)
    assert companion in {"alpha", "beta"}
    assert not error


def test_companion_tool_must_be_registered_and_distinct():
    """Both ways the denial check could pass without proving permit scoping."""
    select = _load_loop()["select_companion_tool"]
    registry = {"alpha": {}, "beta": {}}

    # An unregistered name yields tool-not-found, not a permit refusal.
    companion, error = select(registry, "alpha", "does-not-exist")
    assert companion == ""
    assert "tool-not-found" in error

    # A companion equal to the permitted tool asserts a denial that should
    # never happen.
    companion, error = select(registry, "alpha", "alpha")
    assert companion == ""
    assert "differ" in error

    assert select(registry, "alpha", "beta") == ("beta", "")


def test_single_tool_deployment_skips_rather_than_false_passes():
    select = _load_loop()["select_companion_tool"]
    assert select({"only": {}}, "only", None) == ("", "")


def test_governed_tool_selection_asks_rather_than_guessing():
    """No "just use the first one" fallback.

    Schema-derived arguments satisfy a tool's declared shape but not its
    semantics, so an arbitrary pick can be refused by the tool itself — a
    failure that reads as a broken trust plane rather than a bad choice.
    """
    select = _load_loop()["select_governed_tool"]

    assert select({"partner.echo": {}, "other": {}}, None) == ("partner.echo", "")
    assert select({"partner.notes.write": {}}, None) == ("partner.notes.write", "")

    tool, error = select({"alpha": {}, "beta": {}}, None)
    assert tool == ""
    assert "--tool" in error and "alpha" in error

    tool, error = select({"alpha": {}}, "nope")
    assert tool == ""
    assert "not registered" in error

    assert select({"alpha": {}}, "alpha") == ("alpha", "")


def test_arguments_are_derived_from_each_tool_schema():
    """A fixed payload shape only ever fits the registry it was written for."""
    arguments_for = _load_loop()["arguments_for"]

    built = arguments_for(
        {
            "required": ["session_id", "count", "ratio", "flag", "items", "meta"],
            "properties": {
                "session_id": {"type": "string"},
                "count": {"type": "integer"},
                "ratio": {"type": "number"},
                "flag": {"type": "boolean"},
                "items": {"type": "array"},
                "meta": {"type": "object"},
                "ignored": {"type": "string"},
            },
        },
        "run1",
    )
    # Only required properties: sending optional ones invents intent the
    # caller never expressed.
    assert set(built) == {"session_id", "count", "ratio", "flag", "items", "meta"}
    assert built["session_id"] == "smoke-run1"
    assert built["count"] == 1
    assert built["ratio"] == 1.0
    assert built["flag"] is False
    assert built["items"] == []
    assert built["meta"] == {}

    # A schema that states an acceptable value beats a guess.
    built = arguments_for(
        {
            "required": ["mode", "region"],
            "properties": {
                "mode": {"type": "string", "enum": ["preview", "commit"]},
                "region": {"type": "string", "default": "us-east-1"},
            },
        },
        "run2",
    )
    assert built["mode"] == "preview"
    assert built["region"] == "us-east-1"

    assert arguments_for({}, "run3") == {}
    assert arguments_for(None, "run3") == {}


def test_advertised_price_is_read_from_the_manifest():
    """A fixed permit cap fails permit_budget_exceeded on a healthy deployment.

    Tool prices in this repo span 1-200 credits, so a cap chosen for one tool
    refuses the golden invocation the moment another is selected.
    """
    credits_per_call = _load_loop()["credits_per_call"]

    assert credits_per_call({"annotations": {"creditsPerCall": 25.0}}) == 25.0
    assert credits_per_call({"annotations": {"creditsPerCall": "15"}}) == 15.0
    # No stated price must not raise; the floor applies instead.
    assert credits_per_call({}) == 0.0
    assert credits_per_call({"annotations": {}}) == 0.0
    assert credits_per_call({"annotations": {"creditsPerCall": "free"}}) == 0.0


def test_off_loopback_runs_require_a_pinned_tool_and_approved_payload():
    """Nobody should discover their way into invoking production every run.

    Derived arguments fill required fields from types, defaults, and the first
    enum member -- which for a consequential tool could be "delete".
    """
    env = {
        k: v for k, v in os.environ.items() if not k.startswith("CI_SMOKE")
    }
    env["PATH"] = os.environ.get("PATH", "/usr/bin:/bin")
    env["CI_SMOKE_AGENT_KEY"] = "b2a_placeholder"

    result = subprocess.run(
        [
            sys.executable,
            str(CONSTANT_TEST_SCRIPT),
            "--api-url",
            "https://api.thisisatest.tech",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "refusing to auto-select a tool" in result.stderr
    # The guard fires before any network call, and leaks no credential.
    assert "b2a_placeholder" not in result.stdout + result.stderr

    result = subprocess.run(
        [
            sys.executable,
            str(CONSTANT_TEST_SCRIPT),
            "--api-url",
            "https://api.thisisatest.tech",
            "--tool",
            "partner.echo",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "refusing to send derived arguments" in result.stderr
    assert "b2a_placeholder" not in result.stdout + result.stderr


def test_bootstrap_key_only_pipes_without_jq():
    """--key-only and --json both write stdout, so they cannot both apply."""
    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP_SCRIPT),
            "--api-url",
            "https://api.example.org",
            "--key-only",
            "--json",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "BOOTSTRAP_KEY": "placeholder"},
    )
    assert result.returncode != 0
    assert "mutually exclusive" in result.stderr

    # --key-only must not have opened a path around the fail-closed check.
    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP_SCRIPT),
            "--api-url",
            "https://api.example.org",
            "--key-only",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0
    assert "BOOTSTRAP_KEY" in result.stderr


def test_unusable_tool_pin_exits_as_configuration_not_invariant_failure(
    test_server,
):
    """A bad pin must not page with the same signal as a broken trust plane.

    Exit 1 means an invariant failed; exit 2 means the loop was configured
    wrong. Conflating them makes a typo in $CI_SMOKE_TOOL indistinguishable
    from the product actually breaking.
    """
    base_url, _ = test_server
    env = {k: v for k, v in os.environ.items() if not k.startswith("CI_SMOKE")}

    result = subprocess.run(
        [
            sys.executable,
            str(CONSTANT_TEST_SCRIPT),
            "--api-url",
            base_url,
            "--tool",
            "no-such-tool",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "configuration error" in result.stderr
    assert "FAILED" not in result.stderr

    result = subprocess.run(
        [
            sys.executable,
            str(CONSTANT_TEST_SCRIPT),
            "--api-url",
            base_url,
            "--other-tool",
            "no-such-tool",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "configuration error" in result.stderr
