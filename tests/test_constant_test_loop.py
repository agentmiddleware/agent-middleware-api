"""Tests for scripts/constant_test_loop.py.

Validates configuration handling, credential validation, and negative paths.
Does not re-run the full smoke loop (that's what CI does); focuses on the
behaviors unique to constant_test_loop that aren't covered by demo_trust_plane.
"""

from __future__ import annotations

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

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT
CONSTANT_TEST_LOOP = ROOT / "scripts" / "constant_test_loop.py"
CONSTANT_TEST_SCRIPT = CONSTANT_TEST_LOOP  # Alias for compatibility with ported tests
BOOTSTRAP_SCRIPT = ROOT / "scripts" / "partner_api_key_bootstrap.py"


# Restored: two tests below take this fixture, and removing it turned them
# into collection errors rather than deleting them. It also boots a real
# server, which is what makes the bootstrap and end-to-end assertions worth
# anything — source inspection cannot show that a key never reaches a log.


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


def test_constant_test_loop_refuses_cleartext_http_non_loopback():
    """Configuration error (exit 2) when API_URL uses HTTP for non-loopback host."""
    env = {
        **os.environ,
        "API_URL": "http://api.thisisatest.tech",
        "CI_SMOKE_AGENT_KEY": "test_key_value",
    }
    result = subprocess.run(
        [sys.executable, str(CONSTANT_TEST_LOOP)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, f"Expected exit 2, got {result.returncode}"
    assert "refusing to send CI_SMOKE_AGENT_KEY over cleartext HTTP" in result.stderr
    # Ensure key is never logged
    assert "test_key_value" not in result.stdout
    assert "test_key_value" not in result.stderr


def test_constant_test_loop_allows_http_loopback():
    """HTTP is allowed for loopback addresses (localhost, 127.0.0.1, ::1).

    Points at a loopback port with no server, so the run must get past URL
    validation and fail downstream as an invariant failure (exit 1 with the
    handled FAILED signal), not as a configuration error and not as a crash.
    """
    env = {
        **os.environ,
        "API_URL": "http://localhost:9",
        "CI_SMOKE_AGENT_KEY": "",  # Will self-provision, but fail to connect
    }
    # Strip ambient CI_SMOKE_* so a developer's exported tool pin cannot flip
    # the failure into a configuration error for reasons unrelated to the URL.
    env = {k: v for k, v in env.items() if not k.startswith("CI_SMOKE_")}
    env["CI_SMOKE_AGENT_KEY"] = ""
    result = subprocess.run(
        [sys.executable, str(CONSTANT_TEST_LOOP)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    # Past URL validation means a handled downstream failure: an invariant
    # failure (exit 1, FAILED) or a handled network error (exit 2). A crash
    # (traceback, neither handled signal) or a configuration refusal both
    # fail this test.
    assert result.returncode in (1, 2), result.stdout + result.stderr
    assert ("FAILED" in result.stderr) or ("network error" in result.stderr)
    assert "Traceback" not in result.stderr
    assert "configuration error" not in result.stderr
    # Should NOT contain the cleartext refusal message
    assert (
        "refusing to send CI_SMOKE_AGENT_KEY over cleartext HTTP" not in result.stderr
    )


class _LoopFakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class _LoopFakeClient:
    """Stands in for httpx.Client for the wallet/key fetch stage."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, path, **kwargs):
        if path == "/v1/billing/wallets":
            return _LoopFakeResponse({"wallets": [{"wallet_id": "wallet_1"}]})
        if path.startswith("/v1/billing/wallets/"):
            return _LoopFakeResponse(
                {
                    "keys": [
                        {"key_prefix": "abcdefgh", "key_id": "key_1"},
                    ]
                }
            )
        if path == "/mcp/tools.json":
            return _LoopFakeResponse({"tools": []})
        return _LoopFakeResponse({}, status_code=404)

    def post(self, path, **kwargs):
        return _LoopFakeResponse({}, status_code=404)


def _load_loop_module(name="constant_test_loop_malformed"):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, CONSTANT_TEST_LOOP)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stub_loop_http(monkeypatch, module):
    """Point the loop module at the fake HTTP client without touching httpx."""
    import types

    monkeypatch.setattr(module, "httpx", types.SimpleNamespace(Client=_LoopFakeClient))


def test_constant_test_loop_rejects_malformed_key(monkeypatch):
    """A key without the <prefix>_<suffix> shape fails closed as config error.

    Runs the real fetch-and-derive path in run_constant_test with a stubbed
    HTTP layer: the wallets and keys calls succeed, so only the format check
    itself can reject the key. Deleting the check turns this into a later
    failure instead of the malformed-key refusal, which fails this test.
    """
    module = _load_loop_module()
    _stub_loop_http(monkeypatch, module)

    with pytest.raises(module.ConfigurationError, match="malformed"):
        module.run_constant_test(
            "http://127.0.0.1:9",
            "malformed-key-without-separator",
            "",
            "",
        )


def test_constant_test_loop_accepts_wellformed_key_prefix(monkeypatch):
    """Control: a well-formed key passes the format check with the same stub.

    The stubbed registry is empty, so the run must fail later at tool
    selection, never on the key format. If both tests raise the same error,
    the format check is not doing the discriminating.
    """
    module = _load_loop_module("constant_test_loop_wellformed")
    _stub_loop_http(monkeypatch, module)

    with pytest.raises(module.ConfigurationError) as exc_info:
        module.run_constant_test(
            "http://127.0.0.1:9",
            "abcdefgh_1234567890",
            "",
            "",
        )
    assert "malformed" not in str(exc_info.value).lower()


def test_constant_test_loop_never_logs_keys(capsys, monkeypatch):
    """The canary key never reaches stdout/stderr while credentials are read."""
    module = _load_loop_module("constant_test_loop_never_logs")

    # Set a canary key
    canary_key = "canary_key_must_not_appear_in_logs"
    monkeypatch.setenv("CI_SMOKE_AGENT_KEY", canary_key)
    monkeypatch.setenv("CI_SMOKE_WALLET_ID", "wallet_id")
    monkeypatch.setenv("CI_SMOKE_KEY_ID", "key_id")

    agent_key, wallet_id, key_id = module._get_agent_key()
    assert agent_key == canary_key
    assert wallet_id == "wallet_id"
    assert key_id == "key_id"

    # Actually capture the output: if _get_agent_key ever prints the key,
    # this fails instead of passing on an admission.
    captured = capsys.readouterr()
    assert canary_key not in captured.out
    assert canary_key not in captured.err


def test_constant_test_loop_self_provision_signal():
    """When no credentials provided, _get_agent_key signals self-provision."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "constant_test_loop", CONSTANT_TEST_LOOP
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)

    original_environ = os.environ.copy()
    os.environ.clear()
    os.environ.update(
        {k: v for k, v in original_environ.items() if not k.startswith("CI_SMOKE_")}
    )

    try:
        spec.loader.exec_module(module)
        agent_key, wallet_id, key_id = module._get_agent_key()
        # All empty signals self-provision path
        assert agent_key == ""
        assert wallet_id == ""
        assert key_id == ""
    finally:
        os.environ.clear()
        os.environ.update(original_environ)


def test_constant_test_loop_partial_credentials_fetch_from_api():
    """When key provided but wallet_id/key_id missing, signals API fetch."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "constant_test_loop", CONSTANT_TEST_LOOP
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)

    test_env = {
        **os.environ,
        "CI_SMOKE_AGENT_KEY": "test_key",
    }
    # Explicitly unset wallet_id and key_id
    test_env.pop("CI_SMOKE_WALLET_ID", None)
    test_env.pop("CI_SMOKE_KEY_ID", None)

    original_environ = os.environ.copy()
    os.environ.clear()
    os.environ.update(test_env)

    try:
        spec.loader.exec_module(module)
        agent_key, wallet_id, key_id = module._get_agent_key()
        # Key provided, but wallet_id/key_id empty signals fetch from API
        assert agent_key == "test_key"
        assert wallet_id == ""
        assert key_id == ""
    finally:
        os.environ.clear()
        os.environ.update(original_environ)


class _BootstrapFakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class _BootstrapFakeClient:
    """Stands in for httpx.Client; mints one canned key."""

    minted_key = "b2a_test_minted_key_for_json_path"

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, path, **kwargs):
        return _BootstrapFakeResponse({})

    def post(self, path, json=None, **kwargs):
        if path == "/v1/billing/wallets/sponsor":
            return _BootstrapFakeResponse({"wallet_id": "wal_sponsor"})
        if path == "/v1/billing/wallets/agent":
            return _BootstrapFakeResponse({"wallet_id": "wal_agent"})
        return _BootstrapFakeResponse(
            {
                "api_key": self.minted_key,
                "key_id": "key_1",
                "key_prefix": "b2a_test_",
            }
        )


def test_partner_api_key_bootstrap_json_output(monkeypatch, capsys):
    """The --json key-bearing path emits parseable JSON holding the key once.

    Runs the real provision() with a stubbed HTTP layer, so stdout must
    parse as JSON containing the minted key while stderr carries status only
    and neither stream carries the bootstrap secret. A --json run that
    prints non-JSON output, or echoes either secret to stderr, fails.
    """
    import importlib.util
    import json
    import sys

    spec = importlib.util.spec_from_file_location(
        "partner_api_key_bootstrap_json", BOOTSTRAP_SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    import types

    bootstrap_secret = "bootstrap-secret-must-not-appear"
    monkeypatch.setenv("BOOTSTRAP_KEY", bootstrap_secret)
    monkeypatch.setattr(
        module, "httpx", types.SimpleNamespace(Client=_BootstrapFakeClient)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(BOOTSTRAP_SCRIPT),
            "--api-url",
            "https://api.example.test",
            "--sponsor-name",
            "test-sponsor",
            "--agent-id",
            "test-agent",
            "--json",
        ],
    )

    # Run the real --json CLI path end to end against the stubbed transport.
    assert module.main() == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    minted_key = data["api_key"]
    assert isinstance(minted_key, str) and len(minted_key) > 0
    assert minted_key == _BootstrapFakeClient.minted_key
    assert minted_key not in captured.err
    assert bootstrap_secret not in captured.out + captured.err


def test_partner_api_key_bootstrap_failure_prints_no_key_to_stdout():
    """Without a server the bootstrap fails and stdout stays empty.

    An empty stdout is asserted (not conditionally parsed), so any future
    change that prints non-JSON output, or key material, on the error path
    fails this test instead of passing vacuously.
    """
    canary = "bootstrap-canary-must-not-appear"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "BOOTSTRAP_KEY": canary,
    }
    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP_SCRIPT),
            "--api-url",
            "http://127.0.0.1:9",
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert result.stdout == "", f"stdout must stay empty on failure: {result.stdout!r}"
    assert canary not in result.stdout + result.stderr


@pytest.mark.skipif(
    not os.environ.get("RUN_CONSTANT_TEST_LOOP_INTEGRATION"),
    reason="Set RUN_CONSTANT_TEST_LOOP_INTEGRATION=1 to run full integration test",
)
def test_constant_test_loop_full_integration():
    """Full integration test against a running server (opt-in via env var).

    This test is skipped by default. To run it:
    1. Start server: make quickstart (in terminal 1)
    2. Run test: RUN_CONSTANT_TEST_LOOP_INTEGRATION=1 pytest tests/test_constant_test_loop.py -v
    """
    result = subprocess.run(
        [sys.executable, str(CONSTANT_TEST_LOOP)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"constant_test_loop failed:\n{result.stderr}"
    assert "ALL INVARIANTS HELD" in result.stderr


def test_constant_test_loop_never_logs_api_key(test_server):
    """Agent key is never printed or logged during constant test execution."""
    import httpx

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

    # Run with explicit credentials. Ambient CI_SMOKE_* is stripped first:
    # inheriting the whole environment lets a developer's exported
    # CI_SMOKE_TOOL_ARGS reach the tool as its arguments, and the resulting
    # "unexpected keyword argument" points at the tool rather than the stray
    # variable. The same applies to an ambient wallet or key id.
    result = subprocess.run(
        [sys.executable, str(CONSTANT_TEST_SCRIPT), "--api-url", base_url],
        env={
            **{k: v for k, v in os.environ.items() if not k.startswith("CI_SMOKE")},
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
    env = {k: v for k, v in os.environ.items() if not k.startswith("CI_SMOKE")}
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


def test_tool_args_resolve_from_flag_environment_or_neither(monkeypatch):
    """--tool-args needs the env fallback --tool and --other-tool already have.

    A CI job can otherwise satisfy every part of the off-loopback guard except
    the payload, and would have to put that one remaining piece in argv.
    """
    # Cleared explicitly: the "neither set" case reads the real environment,
    # so an ambient CI_SMOKE_TOOL_ARGS would return a payload and fail the
    # assertion even though the flag path is correct.
    monkeypatch.delenv("CI_SMOKE_TOOL_ARGS", raising=False)
    resolve = _load_loop()["_resolve_tool_args"]

    # The flag wins, and is parsed.
    assert resolve('{"text": "from flag"}') == {"text": "from flag"}

    # Neither set: None, so the guard can still refuse off loopback.
    assert resolve(None) is None


def test_tool_args_environment_fallback(monkeypatch):
    monkeypatch.setenv("CI_SMOKE_TOOL_ARGS", '{"text": "from env"}')
    resolve = _load_loop()["_resolve_tool_args"]

    assert resolve(None) == {"text": "from env"}
    # An explicit flag still overrides the environment.
    assert resolve('{"text": "flag wins"}') == {"text": "flag wins"}

    # An explicitly empty payload is a decision, not an absence: it must
    # satisfy the guard rather than falling through to None.
    monkeypatch.setenv("CI_SMOKE_TOOL_ARGS", "{}")
    assert _load_loop()["_resolve_tool_args"](None) == {}


def test_malformed_tool_args_are_a_configuration_error(monkeypatch):
    """Exit 2, not 1: a bad payload means misconfiguration, not a broken plane."""
    module = _load_loop()
    resolve = module["_resolve_tool_args"]
    ConfigurationError = module["ConfigurationError"]

    with pytest.raises(ConfigurationError, match="not valid JSON"):
        resolve("{not json")

    # A list or scalar would be forwarded as the tool's arguments and rejected
    # downstream as a tool error, which reads as the product failing.
    with pytest.raises(ConfigurationError, match="must be a JSON object"):
        resolve('["a", "b"]')
    with pytest.raises(ConfigurationError, match="must be a JSON object"):
        resolve("42")

    monkeypatch.setenv("CI_SMOKE_TOOL_ARGS", "[1, 2]")
    module = _load_loop()
    with pytest.raises(module["ConfigurationError"], match=r"\$CI_SMOKE_TOOL_ARGS"):
        module["_resolve_tool_args"](None)


def test_environment_alone_satisfies_the_off_loopback_guard():
    """A CI job configured purely through secrets must get past the guard.

    Pointed at a reserved ``.invalid`` host (RFC 6761), which is non-loopback
    — so both guards apply — but never resolves. Naming a real deployment
    here would open an HTTPS session to it on every pytest run, including
    pull-request CI, which is exactly the unattended production traffic this
    guard exists to make deliberate.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("CI_SMOKE")}
    env.update(
        {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "API_URL": "https://api.invalid",
            "CI_SMOKE_AGENT_KEY": "b2a_placeholder",
            "CI_SMOKE_TOOL": "partner.echo",
            "CI_SMOKE_TOOL_ARGS": '{"text": "ci"}',
        }
    )
    result = subprocess.run(
        [sys.executable, str(CONSTANT_TEST_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    # It gets past configuration and fails on the unresolvable host instead,
    # which is the point: neither guard message appears.
    assert "refusing to auto-select a tool" not in result.stderr
    assert "refusing to send derived arguments" not in result.stderr
    assert "b2a_placeholder" not in result.stdout + result.stderr
