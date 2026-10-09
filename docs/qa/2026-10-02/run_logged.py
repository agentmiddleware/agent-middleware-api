"""Run a QA command with UTC timestamps and scrubbed output; no shell expansion."""

import argparse
import datetime as dt
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def scrub(text):
    text = re.sub(
        r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z]+ )?PRIVATE KEY-----",
        "[REDACTED]",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[REDACTED]", text
    )
    text = re.sub(r"(?<=://)[^/@\s]+:[^/@\s]+@", "[REDACTED]@", text)
    text = re.sub(r"(?i)(bearer\s+)[\w.\-]+", r"\1[REDACTED]", text)
    text = re.sub(
        r"\b(?:amw_(?:dev_|live_)?|sk-(?:proj-)?)[A-Za-z0-9_-]{12,}\b",
        "[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)((?:api[_-]?key|token|secret|password|private_key)\s*[=:]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        text,
    )
    # Generated local fixture signing seeds must not enter shared QA logs.
    text = re.sub(
        r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{43}=(?![A-Za-z0-9+/=])", "[REDACTED]", text
    )
    text = re.sub(
        r"(?<![A-Fa-f0-9])[A-Fa-f0-9]{64,}(?![A-Fa-f0-9])", "[REDACTED]", text
    )
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--cwd", default=str(ROOT))
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument(
        "--aggregate-session",
        action="store_true",
        help="Refresh SESSION-LOG.md after this command outcome is written",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log = HERE / f"{args.group.upper()}-SESSION.md"
    artifacts = HERE / "artifacts"
    artifacts.mkdir(exist_ok=True)
    output_path = artifacts / f"{args.group.lower()}-{args.label}.txt"
    env = {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT"}
    }
    env.update(
        {
            "UV_CACHE_DIR": "/private/tmp/amw-qa-uv-cache",
            "PIP_CACHE_DIR": "/private/tmp/amw-qa-pip-cache",
            "PYTHONDONTWRITEBYTECODE": "1",
            "NO_COLOR": "1",
            "CI": "true",
        }
    )
    with log.open("a") as handle:
        handle.write(
            f"\n### {now} — {args.label}\n\nCWD: `{args.cwd}`\n\nCommand (argv): `{scrub(repr(command))}`\n\n"
        )
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=args.cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=args.timeout,
        )
        output, code = result.stdout, result.returncode
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or b""
        output = (
            output.decode(errors="replace") if isinstance(output, bytes) else output
        )
        output += "\nQA timeout reached.\n"
        code = 124
    except OSError as exc:
        output, code = str(exc), 127
    output = scrub(output)
    output_path.write_text(output)
    end = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log.open("a") as handle:
        handle.write(
            f"Outcome for `{args.group.lower()}-{args.label}`: exit {code}; {time.monotonic() - started:.1f}s; ended {end}. [Output](artifacts/{output_path.name}).\n"
        )
    if args.aggregate_session:
        from assemble_session_log import assemble

        assemble()
    print(output[-16000:])
    print(f"\nQA exit={code}; artifact={output_path.relative_to(ROOT)}")
    return code


if __name__ == "__main__":
    sys.exit(main())
