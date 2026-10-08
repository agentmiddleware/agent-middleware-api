import re, pathlib, sys
root = pathlib.Path(sys.argv[1])
subs = [
    # pathlib joins
    (r'(\b(?:REPO_ROOT|ROOT|_REPO_ROOT|PROJECT_ROOT|repo_root|root))\s*/\s*"b2a_sdk"\s*/\s*"src"', r'\1.parent / "sdk" / "python" / "src"'),
    (r'(\b(?:REPO_ROOT|ROOT|_REPO_ROOT|PROJECT_ROOT|repo_root|root))\s*/\s*"b2a_sdk"', r'\1.parent / "sdk" / "python"'),
    (r'(\b(?:REPO_ROOT|ROOT|_REPO_ROOT|PROJECT_ROOT|repo_root|root))\s*/\s*"examples"', r'\1.parent / "examples"'),
    (r'(\b(?:REPO_ROOT|ROOT|_REPO_ROOT|PROJECT_ROOT|repo_root|root))\s*/\s*"wrappers"', r'\1.parent / "integrations"'),
    (r'(\b(?:REPO_ROOT|ROOT|_REPO_ROOT|PROJECT_ROOT|repo_root|root))\s*/\s*"framework_integrations"', r'\1.parent / "integrations" / "framework_integrations"'),
    (r'(\b(?:REPO_ROOT|ROOT|_REPO_ROOT|PROJECT_ROOT|repo_root|root))\s*/\s*f"wrappers/', r'\1.parent / f"integrations/'),
    (r'os\.path\.join\(ROOT, "b2a_sdk", "src"\)', r'os.path.join(ROOT, "..", "sdk", "python", "src")'),
    (r'Path\.cwd\(\) / "b2a_sdk/src"', r'Path.cwd().parent / "sdk/python/src"'),
    (r'Path\(__file__\)\.resolve\(\)\.parent\.parent / "b2a_sdk"', r'Path(__file__).resolve().parents[2] / "sdk" / "python"'),
    # display strings
    (r'wrappers/([a-z]+-agent-middleware)', r'integrations/\1'),
    (r'"b2a_sdk/src/b2a_sdk/', r'"../sdk/python/src/b2a_sdk/'),
]
for p in list(root.rglob("*.py")) + list(root.rglob("*.sh")) + [root/"Makefile"]:
    s = p.read_text()
    n = s
    for a, b in subs:
        n = re.sub(a, b, n)
    if n != s:
        p.write_text(n); print("rewrote", p.relative_to(root))
