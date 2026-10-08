"""The hashed lock (requirements.lock) must pin what requirements.txt asks for.

requirements.txt keeps lower bounds as the human-edited input. The lock
records exact pinned versions with hashes so installs are reproducible.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT = REPO_ROOT / "requirements.txt"
LOCK = REPO_ROOT / "requirements.lock"

PIN_RE = re.compile(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)")
HASH_RE = re.compile(r"^\s+--hash=sha\d+:[0-9a-f]+")


def _input_names() -> set[str]:
    names: set[str] = set()
    for line in INPUT.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)", line)
        assert m, f"unparseable requirements.txt line: {line!r}"
        names.add(m.group(1).lower().replace("_", "-"))
    return names


def _lock_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in LOCK.read_text().splitlines():
        m = PIN_RE.match(line.strip())
        if m:
            pins[m.group(1).lower().replace("_", "-")] = m.group(2)
    return pins


def test_lock_file_exists():
    assert LOCK.exists(), (
        "requirements.lock is missing; run scripts/compile_requirements_lock.sh"
    )


def test_lock_pins_every_input():
    pins = _lock_pins()
    missing = sorted(n for n in _input_names() if n not in pins)
    assert not missing, f"lock is missing pins for: {missing}"


def test_lock_entries_carry_hashes():
    # Every pinned distribution must be followed by at least one --hash line.
    lines = LOCK.read_text().splitlines()
    current_pin: str | None = None
    hash_seen: dict[str, bool] = {}
    for line in lines:
        m = PIN_RE.match(line.strip())
        if m:
            if current_pin is not None:
                assert hash_seen.get(current_pin), f"no hashes for {current_pin}"
            current_pin = m.group(1)
            hash_seen[current_pin] = False
        elif HASH_RE.match(line) and current_pin is not None:
            hash_seen[current_pin] = True
    if current_pin is not None:
        assert hash_seen.get(current_pin), f"no hashes for {current_pin}"
    assert hash_seen, "lock contains no pinned packages"


def test_lock_header_names_input():
    head = LOCK.read_text().splitlines()[:15]
    assert any("requirements.txt" in line for line in head), (
        "lock header should record requirements.txt as its source"
    )
