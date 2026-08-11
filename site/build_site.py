#!/usr/bin/env python3
"""Render the static marketing site only when launch contacts are real.

The source HTML deliberately contains non-deployable tokens. Vercel runs this
script and serves only ``dist/``; a missing or obviously provisional contact
therefore fails the build instead of leaking a fake funnel into production.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse


SITE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SITE_ROOT.parent
DEFAULT_OUTPUT = SITE_ROOT / "dist"
CONTACT_FIELDS = {
    "@@PUBLIC_DISPLAY_NAME@@": "PUBLIC_DISPLAY_NAME",
    "@@PUBLIC_CONTACT_EMAIL@@": "PUBLIC_CONTACT_EMAIL",
    "@@PUBLIC_BOOKING_URL@@": "PUBLIC_BOOKING_URL",
}
TEXT_ASSETS = (
    "index.html",
    "proof/index.html",
)
COPY_ASSETS = (
    ".well-known",
    "analytics.js",
    "favicon.svg",
    "llm.txt",
    "llms.txt",
    "social-card.png",
    "proof",
    "robots.txt",
    "sitemap.xml",
    "styles.css",
)
REQUIRED_PUBLIC_ASSETS = (
    *TEXT_ASSETS,
    *COPY_ASSETS,
    "proof/receipt.json",
    "proof/trust-keys.json",
)
PROVISIONAL_TERMS = (
    "change me",
    "changeme",
    "example.com",
    "example.org",
    "example.net",
    "fake",
    "placeholder",
    "provisional",
    "test@",
    "your email",
    "your name",
)
RESERVED_HOSTS = {"example", "invalid", "localhost", "test"}
RESERVED_HOST_SUFFIXES = tuple(f".{host}" for host in RESERVED_HOSTS)


class LaunchConfigurationError(ValueError):
    """Raised when a build would publish an unusable human funnel."""


def _reject_provisional(field: str, value: str) -> None:
    lowered = value.casefold()
    if any(term in lowered for term in PROVISIONAL_TERMS):
        raise LaunchConfigurationError(f"{field} contains a provisional value")
    if "@@" in value:
        raise LaunchConfigurationError(f"{field} contains an unresolved token")


def _is_reserved_hostname(hostname: str) -> bool:
    normalized = hostname.casefold().rstrip(".")
    return normalized in RESERVED_HOSTS or normalized.endswith(RESERVED_HOST_SUFFIXES)


def validated_contacts(environment: dict[str, str]) -> dict[str, str]:
    """Return escaped contact values or refuse to build the public site."""

    missing = [
        name
        for name in CONTACT_FIELDS.values()
        if not environment.get(name, "").strip()
    ]
    if missing:
        raise LaunchConfigurationError(
            "missing required launch contact values: " + ", ".join(sorted(missing))
        )

    display_name = environment["PUBLIC_DISPLAY_NAME"].strip()
    email = environment["PUBLIC_CONTACT_EMAIL"].strip()
    booking_url = environment["PUBLIC_BOOKING_URL"].strip()

    for field, value in (
        ("PUBLIC_DISPLAY_NAME", display_name),
        ("PUBLIC_CONTACT_EMAIL", email),
        ("PUBLIC_BOOKING_URL", booking_url),
    ):
        _reject_provisional(field, value)

    if (
        display_name.casefold() == "agent middleware api"
        or len(display_name) < 3
        or re.search(
            r"\b(?:example|fake|placeholder|provisional|test)\b",
            display_name,
            flags=re.IGNORECASE,
        )
    ):
        raise LaunchConfigurationError(
            "PUBLIC_DISPLAY_NAME must identify an accountable person or entity"
        )
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) is None:
        raise LaunchConfigurationError(
            "PUBLIC_CONTACT_EMAIL is not a valid email address"
        )
    if _is_reserved_hostname(email.rsplit("@", 1)[1]):
        raise LaunchConfigurationError(
            "PUBLIC_CONTACT_EMAIL must use a routable public domain"
        )

    booking = urlparse(booking_url)
    if booking.scheme != "https" or not booking.hostname:
        raise LaunchConfigurationError(
            "PUBLIC_BOOKING_URL must be an absolute HTTPS URL"
        )
    if booking.username or booking.password:
        raise LaunchConfigurationError(
            "PUBLIC_BOOKING_URL must not contain credentials"
        )
    if _is_reserved_hostname(booking.hostname):
        raise LaunchConfigurationError(
            "PUBLIC_BOOKING_URL must use a routable public domain"
        )
    blocked_booking_hosts = {
        "api.thisisatest.tech",
        "thisisatest.tech",
        "www.thisisatest.tech",
    }
    if booking.hostname.casefold() in blocked_booking_hosts:
        raise LaunchConfigurationError(
            "PUBLIC_BOOKING_URL must point to a booking service"
        )

    return {
        "@@PUBLIC_DISPLAY_NAME@@": html.escape(display_name),
        "@@PUBLIC_CONTACT_EMAIL@@": html.escape(email, quote=True),
        "@@PUBLIC_BOOKING_URL@@": html.escape(booking_url, quote=True),
    }


def _copy_asset(relative_path: str, output: Path) -> None:
    source = SITE_ROOT / relative_path
    destination = output / relative_path
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _validated_output_path(output: Path) -> Path:
    """Resolve a build target without authorizing deletion of existing data."""

    resolved = output.resolve()
    default_output = DEFAULT_OUTPUT.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()

    # Never allow the source tree, repository, temp root, or one of their
    # ancestors to become the recursive-delete target.
    if resolved == SITE_ROOT or resolved in SITE_ROOT.parents:
        raise LaunchConfigurationError("output must not contain the source tree")
    if resolved == default_output:
        return resolved
    if REPO_ROOT in resolved.parents:
        raise LaunchConfigurationError(
            "output must not be another path inside the repository"
        )

    # Tests and one-off previews may use a fresh temp path. Existing arbitrary
    # temp directories are refused because this function clears the target.
    if temp_root in resolved.parents and not resolved.exists():
        return resolved
    raise LaunchConfigurationError(
        "output must be site/dist or a new path under the system temp directory"
    )


def render_site(output: Path, environment: dict[str, str]) -> None:
    replacements = validated_contacts(environment)
    missing_assets = [
        relative_path
        for relative_path in REQUIRED_PUBLIC_ASSETS
        if not (SITE_ROOT / relative_path).exists()
    ]
    if missing_assets:
        raise LaunchConfigurationError(
            "missing required public assets: " + ", ".join(sorted(missing_assets))
        )
    output = _validated_output_path(output)

    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True)
    for relative_path in COPY_ASSETS:
        _copy_asset(relative_path, output)

    for relative_path in TEXT_ASSETS:
        source = SITE_ROOT / relative_path
        rendered = source.read_text(encoding="utf-8")
        for token, replacement in replacements.items():
            rendered = rendered.replace(token, replacement)
        unresolved = sorted(set(re.findall(r"@@[A-Z0-9_]+@@", rendered)))
        if unresolved:
            raise LaunchConfigurationError(
                f"{relative_path} contains unresolved tokens: {', '.join(unresolved)}"
            )
        destination = output / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        render_site(args.output, dict(os.environ))
    except LaunchConfigurationError as exc:
        print(f"site build blocked: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
