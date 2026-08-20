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
