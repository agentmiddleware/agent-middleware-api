#!/usr/bin/env python3
"""Render the static marketing site only when launch contacts are real.

The source HTML deliberately contains non-deployable tokens. Vercel runs this
script and serves only ``dist/``; a missing or obviously provisional contact
therefore fails the build instead of leaking a fake funnel into production.

The Vercel Web Analytics loader is emitted only when
``PUBLIC_ENABLE_VERCEL_ANALYTICS=true``. Deploying the ``/_vercel/insights``
script tag against a project whose Web Analytics is not enabled makes every
page load log a 404 plus a MIME-type refusal in the browser console, so the
default build omits the tag entirely.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
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
ANALYTICS_FLAG = "PUBLIC_ENABLE_VERCEL_ANALYTICS"
ANALYTICS_TOKEN = "@@VERCEL_ANALYTICS_SCRIPTS@@"
ANALYTICS_FLAG_ENABLED = frozenset({"true"})
ANALYTICS_FLAG_DISABLED = frozenset({"", "false"})
# The queue shim lives in /va-init.js rather than an inline <script> so the
# deployed Content-Security-Policy can stay script-src 'self' with no
# 'unsafe-inline'. It must load before the insights script reads window.vaq.
ANALYTICS_SCRIPTS = """<script src="/va-init.js?v=gateway-2"></script>
    <script defer src="/_vercel/insights/script.js"></script>"""
BUILD_DATE_TOKEN = "@@BUILD_DATE@@"
SECURITY_TXT_EXPIRES_TOKEN = "@@SECURITY_TXT_EXPIRES@@"
# security.txt must carry a future Expires (RFC 9116 §2.5.5). Regenerating it
# one year out on every build means a deployed site never serves a lapsed file.
SECURITY_TXT_LIFETIME_DAYS = 365
TEXT_ASSETS = (
    "index.html",
    "proof/index.html",
    "404.html",
    "sitemap.xml",
    ".well-known/security.txt",
)
COPY_ASSETS = (
    ".well-known",
    "a11y.js",
    "a11y-preload.js",
    "analytics.js",
    "favicon.svg",
    "llm.txt",
    "llms.txt",
    "social-card.png",
    "proof",
    "robots.txt",
    "sitemap.xml",
    "styles.css",
    "va-init.js",
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


def validated_contacts(
    environment: dict[str, str], *, escape_markup: bool = True
) -> dict[str, str]:
    """Return contact values or refuse to build the public site.

    ``escape_markup`` is on for HTML and XML targets. Plain-text targets such as
    ``.well-known/security.txt`` take the raw value, because an entity-escaped
    address there would be served verbatim to whoever reads the file.
    """

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

    if not escape_markup:
        return {
            "@@PUBLIC_DISPLAY_NAME@@": display_name,
            "@@PUBLIC_CONTACT_EMAIL@@": email,
            "@@PUBLIC_BOOKING_URL@@": booking_url,
        }
    return {
        "@@PUBLIC_DISPLAY_NAME@@": html.escape(display_name),
        "@@PUBLIC_CONTACT_EMAIL@@": html.escape(email, quote=True),
        "@@PUBLIC_BOOKING_URL@@": html.escape(booking_url, quote=True),
    }


def vercel_analytics_enabled(environment: dict[str, str]) -> bool:
    """Return whether the build should emit the Vercel Web Analytics loader.

    A misspelled value fails the build instead of silently disabling analytics
    the operator meant to turn on.
    """

    raw = environment.get(ANALYTICS_FLAG, "").strip().casefold()
    if raw in ANALYTICS_FLAG_ENABLED:
        return True
    if raw in ANALYTICS_FLAG_DISABLED:
        return False
    raise LaunchConfigurationError(
        f'{ANALYTICS_FLAG} must be "true", "false", or unset'
    )


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


def _build_timestamps() -> dict[str, str]:
    """Return the date tokens shared by the sitemap and security.txt."""

    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=SECURITY_TXT_LIFETIME_DAYS)
    return {
        BUILD_DATE_TOKEN: now.date().isoformat(),
        SECURITY_TXT_EXPIRES_TOKEN: expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def render_site(output: Path, environment: dict[str, str]) -> None:
    markup_replacements = validated_contacts(environment)
    text_replacements = validated_contacts(environment, escape_markup=False)
    timestamps = _build_timestamps()
    markup_replacements.update(timestamps)
    text_replacements.update(timestamps)
    analytics_enabled = vercel_analytics_enabled(environment)
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
        if analytics_enabled:
            rendered = rendered.replace(ANALYTICS_TOKEN, ANALYTICS_SCRIPTS)
        else:
            # Drop the token's whole line regardless of indentation so no
            # blank line or stray whitespace is left behind; the
            # unresolved-token check below still fails loudly if the token
            # ever stops sitting on its own line.
            rendered = re.sub(
                rf"^[ \t]*{re.escape(ANALYTICS_TOKEN)}[ \t]*\n",
                "",
                rendered,
                flags=re.MULTILINE,
            )
        replacements = (
            markup_replacements
            if relative_path.endswith((".html", ".xml"))
            else text_replacements
        )
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
