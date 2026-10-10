import re, pathlib, sys

root = pathlib.Path(sys.argv[1])
subs = [
    # pathlib joins
    (
        r'(\b(?:REPO_ROOT|ROOT|_REPO_ROOT|PROJECT_ROOT|repo_root|root))\s*/\s*"b2a_sdk"\s*/\s*"src"',
        r'\1.parent / "sdk" / "python" / "src"',
    ),
    (
        r'(\b(?:REPO_ROOT|ROOT|_REPO_ROOT|PROJECT_ROOT|repo_root|root))\s*/\s*"b2a_sdk"',
        r'\1.parent / "sdk" / "python"',
    ),
    (
        r'(\b(?:REPO_ROOT|ROOT|_REPO_ROOT|PROJECT_ROOT|repo_root|root))\s*/\s*"examples"',
        r'\1.parent / "examples"',
    ),
    (
        r'(\b(?:REPO_ROOT|ROOT|_REPO_ROOT|PROJECT_ROOT|repo_root|root))\s*/\s*"wrappers"',
        r'\1.parent / "integrations"',
    ),
    (
        r'(\b(?:REPO_ROOT|ROOT|_REPO_ROOT|PROJECT_ROOT|repo_root|root))\s*/\s*"framework_integrations"',
        r'\1.parent / "integrations" / "framework_integrations"',
    ),
    (
        r'(\b(?:REPO_ROOT|ROOT|_REPO_ROOT|PROJECT_ROOT|repo_root|root))\s*/\s*f"wrappers/',
        r'\1.parent / f"integrations/',
    ),
    (
        r'os\.path\.join\(ROOT, "b2a_sdk", "src"\)',
        r'os.path.join(ROOT, "..", "sdk", "python", "src")',
    ),
    (r'Path\.cwd\(\) / "b2a_sdk/src"', r'Path.cwd().parent / "sdk/python/src"'),
    (
        r'(Path\(__file__\)\.resolve\(\)\.parents\[2\])\s*/\s*"b2a_sdk"',
        r'\1.parent / "sdk" / "python"',
    ),
    (
        r'Path\(__file__\)\.resolve\(\)\.parent\.parent / "b2a_sdk"',
        r'Path(__file__).resolve().parents[2] / "sdk" / "python"',
    ),
    # display strings
    (r"wrappers/([a-z]+-agent-middleware)", r"integrations/\1"),
    (r'"b2a_sdk/src/b2a_sdk/', r'"../sdk/python/src/b2a_sdk/'),
]
examples = root.parent / "examples"
integrations = root.parent / "integrations"
paths = (
    list(root.rglob("*.py"))
    + list(root.rglob("*.sh"))
    + list(examples.rglob("*.py"))
    + list(integrations.rglob("*.py"))
    + list(integrations.rglob("pyproject.toml"))
    + [root / "Makefile", root / "pyproject.toml", examples / "README.md"]
)
for p in paths:
    if not p.is_file():
        continue
    s = p.read_text()
    n = s
    if p == root / "pyproject.toml":
        n = n.replace('"b2a_sdk/src"', '"../sdk/python/src"')
        n = n.replace(
            '"wrappers/openai-agent-middleware/src"',
            '"../integrations/openai-agent-middleware/src", "../integrations"',
        )
    if p.is_relative_to(integrations) and p.name == "pyproject.toml":
        n = n.replace("../../b2a_sdk/src", "../../sdk/python/src")
    for a, b in subs:
        n = re.sub(a, b, n)
    if p.is_relative_to(examples):
        n = n.replace('"b2a_sdk", "src"', '"sdk", "python", "src"')
        n = n.replace("b2a_sdk/src", "sdk/python/src")
        n = n.replace("./b2a_sdk[dev]", "./sdk/python[dev]")
    if n != s:
        p.write_text(n)
        print("rewrote", p.relative_to(root.parent))

# These published instructions describe the source checkout layout. The
# exported checkout places the SDK at the public repository root in sdk/python.
export_guidance = {
    root / "app/routers/well_known.py": [
        ('"path": "b2a_sdk/"', '"path": "sdk/python/"'),
        (
            '"install": "pip install -e ./b2a_sdk"',
            '"install": "pip install -e ./sdk/python"',
        ),
        ("source in b2a_sdk/ is", "source in sdk/python/ is"),
    ],
    root / "static/llm.txt": [
        ("from `b2a_sdk/`.", "from `sdk/python/`."),
        ("pip install -e ./b2a_sdk", "pip install -e ./sdk/python"),
    ],
    root / "docs/partner-first-tool-runbook.md": [
        (
            "or run it from a copy of b2a_sdk/:",
            "or install it from the public repository root:",
        ),
        ('pip install "./b2a_sdk[verify]"', 'pip install "./sdk/python[verify]"'),
    ],
    root / "tests/test_wedge_honesty.py": [
        (
            'assert python_sdk["path"] == "b2a_sdk/"',
            'assert python_sdk["path"] == "sdk/python/"',
        ),
        (
            'assert python_sdk["install"] == "pip install -e ./b2a_sdk"',
            'assert python_sdk["install"] == "pip install -e ./sdk/python"',
        ),
        (
            'assert "pip install -e ./b2a_sdk" in text',
            'assert "pip install -e ./sdk/python" in text',
        ),
    ],
    root / "tests/test_onboarding_doc_contracts.py": [
        (
            "assert 'pip install \"./b2a_sdk[verify]\"' in doc",
            "assert 'pip install \"./sdk/python[verify]\"' in doc",
        ),
    ],
}
for p, replacements in export_guidance.items():
    if not p.is_file():
        continue
    s = p.read_text()
    n = s
    for old, new in replacements:
        if n.count(old) == 1:
            n = n.replace(old, new)
        elif not (old not in n and n.count(new) == 1):
            raise SystemExit(f"expected one {old!r} or {new!r} in {p}")
    if n != s:
        p.write_text(n)
        print("rewrote", p.relative_to(root.parent))
