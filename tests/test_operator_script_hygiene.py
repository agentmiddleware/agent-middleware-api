"""Operator-script hygiene: private signing seed, no piped remote installer.

Covers two low-severity audit items in the files that own them:

- scripts/invariant_attacks/boot_controlled.sh must leave the test
  signing seed readable only by its owner, even under a permissive umask.
- .cursor/install.sh must fetch the uv installer to a file and run that
  file, instead of piping a live download straight into a shell.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BOOT_SCRIPT = REPO_ROOT / "scripts" / "invariant_attacks" / "boot_controlled.sh"
INSTALL_SCRIPT = REPO_ROOT / ".cursor" / "install.sh"

BASH = shutil.which("bash") or "/bin/bash"


def _make_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def test_boot_controlled_seed_is_owner_only(tmp_path: Path) -> None:
    """The seed must end up mode 0600 even when the caller umask is 022."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # The script ends with `exec python -m uvicorn ...`; stub `python` so the
    # script terminates instead of starting a server. `python3` stays real so
    # seed generation still runs.
    _make_executable(bindir / "python", "#!/bin/sh\nexit 0\n")
    stub_python3 = bindir / "python3"
    if not stub_python3.exists():
        stub_python3.symlink_to(Path(sys.executable))

    env = {
        "PATH": f"{bindir}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "TP_STATE_DIR": str(state_dir),
        "TP_PORT": "18099",
    }
    proc = subprocess.run(
        [BASH, str(BOOT_SCRIPT)],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        preexec_fn=lambda: os.umask(0o022),
    )
    assert proc.returncode == 0, proc.stdout.decode()[-2000:]

    seed = state_dir / "signing-seed.b64"
    assert seed.is_file()
    mode = stat.S_IMODE(seed.stat().st_mode)
    assert mode == 0o600, f"signing seed is mode {mode:o}, want 600"


def test_install_script_runs_installer_from_file(tmp_path: Path) -> None:
    """The uv installer must reach `sh` as a file argument, not a pipe."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    sh_log = tmp_path / "sh.log"

    _make_executable(
        bindir / "curl",
        "#!/bin/sh\n"
        'OUT=""\nWANT_OUT=0\nfor a in "$@"; do\n'
        '  if [ "$WANT_OUT" = "1" ]; then OUT="$a"; WANT_OUT=0; continue; fi\n'
        '  if [ "$a" = "-o" ]; then WANT_OUT=1; fi\ndone\n'
        'if [ -n "$OUT" ]; then\n'
        "  printf '#!/bin/sh\\necho installer-ran\\n' > \"$OUT\"\nelse\n"
        "  printf '#!/bin/sh\\necho installer-ran\\n'\nfi\n",
    )
    # Log how `sh` is invoked without executing the payload.
    _make_executable(
        bindir / "sh",
        "#!/bin/sh\n"
        f'echo "ARGS:$*" >> "{sh_log}"\n'
        f'echo "STDIN-START" >> "{sh_log}"\n'
        f'cat >> "{sh_log}"\n'
        f'echo "STDIN-END" >> "{sh_log}"\n',
    )

    # PATH has no `uv` (and HOME has no ~/.local/bin) so the installer branch
    # runs; the later `uv venv` step then fails, which is fine, only the
    # installer invocation is under test.
    env = {
        "PATH": f"{bindir}:/usr/bin:/bin",
        "HOME": str(home),
    }
    subprocess.run(
        [BASH, str(INSTALL_SCRIPT)],
        env=env,
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )

    assert sh_log.is_file(), "installer branch did not run (is uv on PATH?)"
    log = sh_log.read_text()
    args_line, _, rest = log.partition("\n")
    invoked = args_line.removeprefix("ARGS:").strip()
    assert invoked != "", f"installer piped to sh, not run from file: {log!r}"
    stdin_section = rest.split("STDIN-START", 1)[1].split("STDIN-END")[0]
    assert "installer-ran" not in stdin_section, (
        f"installer reached sh via pipe: {log!r}"
    )
