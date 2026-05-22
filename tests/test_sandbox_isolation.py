"""
Regression guard for behavioral sandbox isolation.

The Docker backend is the only built-in execution boundary intended for
untrusted code. These tests assert that its hardening flags stay in place so a
future change cannot silently weaken the sandbox. They build the command only —
no Docker daemon is required.
"""

from app.services.behavioral_sandbox import BehavioralSandboxEngine


def _has_flag(cmd: list[str], flag: str) -> bool:
    return flag in cmd


def _has_pair(cmd: list[str], flag: str, value: str) -> bool:
    return any(cmd[i] == flag and cmd[i + 1] == value for i in range(len(cmd) - 1))


def _build(**overrides):
    return BehavioralSandboxEngine._build_docker_run_command(
        image=overrides.get("image", "python:3.12-slim"),
        sandbox_code=overrides.get("sandbox_code", "print('x')"),
        memory_limit_mb=overrides.get("memory_limit_mb", 128),
        env_vars=overrides.get("env_vars", {}),
    )


def test_docker_command_enforces_network_isolation():
    assert _has_pair(_build(), "--network", "none")


def test_docker_command_drops_all_capabilities_and_privileges():
    cmd = _build()
    assert _has_pair(cmd, "--cap-drop", "ALL")
    assert _has_pair(cmd, "--security-opt", "no-new-privileges")


def test_docker_command_runs_as_non_root():
    assert _has_pair(_build(), "--user", "65534:65534")


def test_docker_command_caps_memory_and_forbids_swap_escape():
    cmd = _build(memory_limit_mb=256)
    assert _has_pair(cmd, "--memory", "256m")
    assert _has_pair(cmd, "--memory-swap", "256m")


def test_docker_command_limits_processes_and_files():
    cmd = _build()
    assert _has_pair(cmd, "--pids-limit", "64")
    assert _has_pair(cmd, "--ulimit", "nofile=64:64")
    assert _has_pair(cmd, "--ulimit", "fsize=8388608:8388608")


def test_docker_command_uses_readonly_root_and_noexec_tmp():
    cmd = _build()
    assert _has_flag(cmd, "--read-only")
    assert _has_pair(cmd, "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m")


def test_docker_command_runs_isolated_python_last():
    cmd = _build(image="custom:img", sandbox_code="print(1)")
    assert cmd[-6:] == ["custom:img", "python", "-I", "-S", "-c", "print(1)"]


def test_default_docker_command_has_no_runtime_override():
    cmd = _build()
    assert "--runtime" not in cmd


def test_gvisor_backend_selects_runsc_runtime_and_keeps_hardening():
    cmd = BehavioralSandboxEngine._build_docker_run_command(
        image="python:3.12-slim",
        sandbox_code="print('x')",
        memory_limit_mb=128,
        env_vars={},
        runtime="runsc",
    )
    assert _has_pair(cmd, "--runtime", "runsc")
    # gVisor must not replace the existing isolation flags.
    assert _has_pair(cmd, "--network", "none")
    assert _has_pair(cmd, "--cap-drop", "ALL")
    assert _has_pair(cmd, "--user", "65534:65534")
    # Runtime flag precedes the image.
    assert cmd.index("--runtime") < cmd.index("python:3.12-slim")


def test_caller_env_vars_forwarded_but_reserved_and_invalid_blocked():
    cmd = _build(
        env_vars={
            "MY_VAR": "hello",
            "SANDBOX": "false",  # reserved -> must not override
            "PATH": "/evil",  # reserved -> blocked
            "bad-name": "x",  # not an identifier -> blocked
        }
    )
    assert _has_pair(cmd, "--env", "MY_VAR=hello")
    assert not _has_pair(cmd, "--env", "SANDBOX=false")
    assert not _has_pair(cmd, "--env", "PATH=/evil")
    assert not any(c == "bad-name=x" for c in cmd)
    # The hardened SANDBOX=true is still set.
    assert _has_pair(cmd, "--env", "SANDBOX=true")
