"""Contracts for the webfont vendoring tool.

``site/vendor_fonts.py`` generates deployed assets and deletes files from the
working tree, which AGENTS.md classifies as deployment/CI-adjacent and therefore
requires negative-path coverage. Every test here stubs the network, so the suite
never depends on Google being reachable.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

# A minimal css2 response: one static family (a file per weight) and one
# variable family (one file shared by both weights), which is the distinction
# the tool exists to handle.
STATIC_CSS = """
/* latin-ext */
@font-face {{
  font-family: 'IBM Plex Mono';
  font-style: normal;
  font-weight: {weight};
  src: url(https://fonts.gstatic.com/s/static-{weight}-ext.woff2) format('woff2');
  unicode-range: U+0100-02BA;
}}
/* latin */
@font-face {{
  font-family: 'IBM Plex Mono';
  font-style: normal;
  font-weight: {weight};
  src: url(https://fonts.gstatic.com/s/static-{weight}.woff2) format('woff2');
  unicode-range: U+0000-00FF;
}}
"""
VARIABLE_CSS = """
/* latin-ext */
@font-face {{
  font-family: '{family}';
  font-style: normal;
  font-weight: {weight};
  src: url(https://fonts.gstatic.com/s/variable-ext.woff2) format('woff2');
  unicode-range: U+0100-02BA;
}}
/* latin */
@font-face {{
  font-family: '{family}';
  font-style: normal;
  font-weight: {weight};
  src: url(https://fonts.gstatic.com/s/variable.woff2) format('woff2');
  unicode-range: U+0000-00FF;
}}
"""


def _woff2(marker: bytes) -> bytes:
    return b"wOF2" + marker


def _load_module():
    """Import vendor_fonts.py as a real module.

    ``runpy.run_path`` returns a *copy* of the namespace, so stubs written into
    it would never be seen by the module's own functions.
    """

    spec = importlib.util.spec_from_file_location(
        "vendor_fonts_under_test", SITE / "vendor_fonts.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def vendor(tmp_path, monkeypatch):
    """Load the module with its output paths redirected into tmp_path."""

    module = _load_module()
    monkeypatch.setattr(module, "FONT_DIR", tmp_path / "fonts")
    monkeypatch.setattr(module, "STYLESHEET", tmp_path / "fonts.css")
    monkeypatch.setattr(module, "MANIFEST", tmp_path / "fonts.manifest.json")
    monkeypatch.setattr(
        module, "FAMILIES", {"IBM Plex Mono": (400, 500), "Public Sans": (400, 600)}
    )
    monkeypatch.setattr(
        module,
        "PRELOAD",
        (("Public Sans", 400, "latin"), ("IBM Plex Mono", 400, "latin")),
    )

    def fake_get(url: str) -> bytes:
        if "css2" in url:
            if "IBM" in url:
                return "".join(STATIC_CSS.format(weight=w) for w in (400, 500)).encode()
            return "".join(
                VARIABLE_CSS.format(family="Public Sans", weight=w) for w in (400, 600)
            ).encode()
        # Distinct bytes per URL, except the variable family which shares one.
        return _woff2(url.rsplit("/", 1)[1].encode())

    monkeypatch.setattr(module, "_get", fake_get)
    module._fake_get = fake_get
    return module


def _vendor_all(v):
    faces = v.discover_faces()
    files = v.download(faces)
    return files, v.render_stylesheet(faces), v.render_manifest(faces)


def test_variable_family_is_stored_once_and_named_without_a_weight(vendor) -> None:
    """The whole point of the sha grouping: one file, several weights."""
    files, stylesheet, _ = _vendor_all(vendor)

    variable = [name for name in files if name.startswith("public-sans-latin.")]
    assert len(variable) == 1, files
    # No weight in the name, because the file serves more than one.
    assert "public-sans-400" not in " ".join(files)
    # Both weights still get their own @font-face pointing at that one file.
    for weight in (400, 600):
        assert f"font-weight: {weight};" in stylesheet
    assert stylesheet.count(f'url("/fonts/{variable[0]}")') == 2

    # The static family keeps a file per weight.
    assert any(name.startswith("ibm-plex-mono-400-latin.") for name in files)
    assert any(name.startswith("ibm-plex-mono-500-latin.") for name in files)


def test_each_distinct_url_is_fetched_exactly_once(vendor) -> None:
    """A shared variable file must not be pulled once per weight."""
    calls: list[str] = []
    original = vendor._fake_get

    def counting(url: str) -> bytes:
        calls.append(url)
        return original(url)

    vendor._get = counting
    faces = vendor.discover_faces()
    vendor.download(faces)

    font_calls = [url for url in calls if url.endswith(".woff2")]
    assert len(font_calls) == len(set(font_calls)), f"re-fetched: {font_calls}"


def test_filenames_carry_a_content_hash(vendor) -> None:
    files, stylesheet, _ = _vendor_all(vendor)
    for name, blob in files.items():
        digest = hashlib.sha256(blob).hexdigest()[: vendor.HASH_LENGTH]
        assert name.endswith(f".{digest}.woff2"), name
        assert f'url("/fonts/{name}")' in stylesheet


def test_a_missing_subset_is_refused_rather_than_silently_dropped(vendor) -> None:
    """Without a subset-aware check, write() would delete the committed
    latin-ext files and the offline tests would still pass."""

    def latin_only(url: str) -> bytes:
        if "css2" not in url:
            return vendor._fake_get(url)
        # Remove the latin-ext faces outright, marker and block, so the guard
        # fires because the face is absent rather than because a comment is.
        body = vendor._fake_get(url).decode()
        return re.sub(
            r"/\*\s*latin-ext\s*\*/\s*@font-face\s*\{.*?\}", "", body, flags=re.S
        ).encode()

    vendor._get = latin_only
    with pytest.raises(vendor.VendorError, match="no face for"):
        vendor.discover_faces()


def test_an_unparsable_upstream_block_raises_vendor_error(vendor) -> None:
    """Not AttributeError: main only maps VendorError to a distinct exit code."""

    def ttf_instead(url: str) -> bytes:
        if "css2" not in url:
            return vendor._fake_get(url)
        return vendor._fake_get(url).decode().replace(".woff2", ".ttf").encode()

    vendor._get = ttf_instead
    with pytest.raises(vendor.VendorError, match="woff2 src"):
        vendor.discover_faces()


def test_non_woff2_payload_is_refused(vendor) -> None:
    vendor._get = lambda url: vendor._fake_get(url) if "css2" in url else b"OTTO junk"
    faces = vendor.discover_faces()
    with pytest.raises(vendor.VendorError, match="not woff2"):
        vendor.download(faces)


def test_preloading_an_unknown_face_is_refused(vendor) -> None:
    vendor.PRELOAD = (("Nonexistent Family", 400, "latin"),)
    faces = vendor.discover_faces()
    vendor.download(faces)
    with pytest.raises(vendor.VendorError, match="does not exist"):
        vendor.render_manifest(faces)


def test_write_replaces_stale_files_and_check_detects_drift(vendor) -> None:
    files, stylesheet, manifest = _vendor_all(vendor)
    vendor.FONT_DIR.mkdir(parents=True)
    orphan = vendor.FONT_DIR / "left-over-from-a-previous-run.woff2"
    orphan.write_bytes(b"wOF2 stale")

    vendor.write(files, stylesheet, manifest)

    assert not orphan.exists(), "write() must clear files no longer referenced"
    assert vendor.check(files, stylesheet, manifest) == []
    assert json.loads(vendor.MANIFEST.read_text())["preload"]

    # Any one of the three outputs drifting must be reported.
    next(vendor.FONT_DIR.glob("*.woff2")).write_bytes(b"wOF2 tampered")
    assert any(
        "differs from upstream" in p for p in vendor.check(files, stylesheet, manifest)
    )

    vendor.write(files, stylesheet, manifest)
    vendor.STYLESHEET.write_text("/* hand-edited */")
    assert any(
        "fonts.css is stale" in p for p in vendor.check(files, stylesheet, manifest)
    )

    vendor.write(files, stylesheet, manifest)
    vendor.MANIFEST.unlink()
    assert any(
        "fonts.manifest.json is missing" in p
        for p in vendor.check(files, stylesheet, manifest)
    )


def test_ssl_context_keeps_the_system_trust_store(vendor) -> None:
    """Passing cafile= to create_default_context would replace the system roots
    with a single corporate cert and break every fetch to a public host."""
    import ssl

    baseline = len(ssl.create_default_context().get_ca_certs())
    assert len(vendor._ssl_context().get_ca_certs()) >= baseline


def test_slug_is_derived_not_hand_maintained(vendor) -> None:
    """The README tells operators to edit FAMILIES and nothing else."""
    module = runpy.run_path(str(SITE / "vendor_fonts.py"))
    assert "SLUGS" not in module, "a parallel slug table will drift from FAMILIES"
    assert module["_slug"]("Some New Family") == "some-new-family"


def test_main_maps_upstream_failure_to_exit_2(vendor, monkeypatch) -> None:
    """--check has to distinguish "output is stale" from "the tool broke"."""

    def explode():
        raise vendor.VendorError("upstream unreachable")

    monkeypatch.setattr(vendor, "vendor", explode)
    assert vendor.main([]) == 2
    assert vendor.main(["--check"]) == 2


def test_main_maps_drift_to_exit_1_and_clean_to_0(vendor, monkeypatch) -> None:
    files, stylesheet, manifest = _vendor_all(vendor)
    monkeypatch.setattr(vendor, "vendor", lambda: (files, stylesheet, manifest))

    # Nothing written yet: everything is missing, which is drift.
    vendor.FONT_DIR.mkdir(parents=True, exist_ok=True)
    assert vendor.main(["--check"]) == 1

    assert vendor.main([]) == 0
    assert vendor.main(["--check"]) == 0


def test_ssl_context_ignores_a_ca_bundle_path_that_does_not_exist(
    vendor, monkeypatch, tmp_path
) -> None:
    """A stale REQUESTS_CA_BUNDLE must not make every fetch fail."""

    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path / "nope.pem"))
    context = vendor._ssl_context()
    assert context.get_ca_certs(), "system roots were dropped"


def test_ssl_context_layers_a_real_ca_bundle_on_top_of_the_system_store(
    vendor, monkeypatch, tmp_path
) -> None:
    import ssl

    default_paths = ssl.get_default_verify_paths()
    real_bundle = default_paths.cafile or default_paths.openssl_cafile
    if not real_bundle or not Path(real_bundle).is_file():
        pytest.skip("no system CA bundle to layer in this environment")

    baseline = len(ssl.create_default_context().get_ca_certs())
    monkeypatch.setenv("CURL_CA_BUNDLE", real_bundle)
    # The point is that the system roots survive the layering, not that the
    # count grows: re-adding the same bundle is a no-op.
    assert len(vendor._ssl_context().get_ca_certs()) >= baseline


def test_vendoring_refuses_a_font_url_from_an_unexpected_host(vendor) -> None:
    """The URL comes from a fetched CSS response and its bytes get committed."""

    def elsewhere(url: str) -> bytes:
        if "css2" not in url:
            return vendor._fake_get(url)
        return (
            vendor._fake_get(url)
            .decode()
            .replace("fonts.gstatic.com", "cdn.example.invalid")
            .encode()
        )

    vendor._get = elsewhere
    faces = vendor.discover_faces()
    with pytest.raises(vendor.VendorError, match="unexpected host"):
        vendor.download(faces)
