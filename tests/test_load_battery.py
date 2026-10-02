"""Synthetic lifecycle and verdict checks for the legacy load script."""

import subprocess

import pytest


@pytest.fixture
def battery(monkeypatch):
    # Its legacy CLI defaults must not leak into other tests on import.
    monkeypatch.setenv("VALID_API_KEYS", "synthetic-unused")
    monkeypatch.setenv("TRUST_MODE_ENABLED", "false")
    monkeypatch.setenv("ALLOW_LEGACY_UNPERMITTED_MCP", "true")
    from scripts import load_battery

    monkeypatch.setattr(load_battery, "DB_URL", None)
    monkeypatch.setattr(load_battery, "_OWNED_CONTAINER_ID", None)
    monkeypatch.setattr(load_battery.time, "sleep", lambda _: None)
    # _ensure_postgres writes these; register restoration before it runs.
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("STATE_BACKEND", "sqlite")
    return load_battery


def test_caller_database_never_creates_or_stops_a_container(battery, monkeypatch):
    url = "postgresql+asyncpg://synthetic.invalid/disposable"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(battery, "DB_URL", url)

    def unexpected_command(*args, **kwargs):
        pytest.fail("caller-owned database reached a Docker command")

    monkeypatch.setattr(battery.subprocess, "run", unexpected_command)
    assert battery._ensure_postgres() == url
    battery._stop_postgres()


@pytest.mark.parametrize("mode", ["reuse", "created", "create-failed", "not-ready"])
def test_cleanup_only_stops_this_process_successfully_created_id(
    battery, monkeypatch, mode
):
    calls = []

    def command(argv, **kwargs):
        calls.append(argv)
        operation = argv[1]
        if operation == "ps":
            return subprocess.CompletedProcess(
                argv, 0, "borrowed-id" if mode == "reuse" else ""
            )
        if operation == "run":
            if mode == "create-failed":
                raise subprocess.CalledProcessError(1, argv)
            return subprocess.CompletedProcess(argv, 0, "created-id\n")
        if operation == "exec":
            assert argv[2] == "created-id"
            return subprocess.CompletedProcess(argv, 1 if mode == "not-ready" else 0)
        assert operation == "stop"
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(battery.subprocess, "run", command)
    try:
        if mode == "create-failed":
            with pytest.raises(subprocess.CalledProcessError):
                battery._ensure_postgres()
        elif mode == "not-ready":
            with pytest.raises(RuntimeError, match="failed to start"):
                battery._ensure_postgres()
        else:
            battery._ensure_postgres()
    finally:
        battery._stop_postgres()
        battery._stop_postgres()
    stops = [argv for argv in calls if argv[1] == "stop"]
    assert stops == (
        [["docker", "stop", "-t", "5", "created-id"]]
        if mode in {"created", "not-ready"}
        else []
    )
