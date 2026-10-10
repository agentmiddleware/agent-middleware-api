import subprocess
import sys
import tomllib
from pathlib import Path


def test_rewrite_paths_follows_export_layout(tmp_path):
    source = Path(__file__).resolve().parents[2]
    gateway = tmp_path / "gateway"
    files = (
        ("app/routers/mcp_public.py", gateway),
        ("pyproject.toml", gateway),
        ("examples/dry_run_example.py", tmp_path),
        ("examples/mcp_tool_example.py", tmp_path),
        ("examples/README.md", tmp_path),
        ("framework_integrations/tools.py", tmp_path / "integrations"),
    )
    for name, destination in files:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source / name).read_bytes())

    wrapper_config = tmp_path / "integrations/openai-agent-middleware/pyproject.toml"
    wrapper_config.parent.mkdir(parents=True, exist_ok=True)
    wrapper_config.write_bytes(
        (source / "wrappers/openai-agent-middleware/pyproject.toml").read_bytes()
    )

    (gateway / "Makefile").write_text("")
    (tmp_path / "sdk/python/src/b2a_sdk").mkdir(parents=True)
    (tmp_path / "integrations/openai-agent-middleware/src").mkdir(parents=True)
    (tmp_path / "sdk/python/src/b2a_sdk/receipt_verifier.py").write_text("")

    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("rewrite_paths.py")),
            str(gateway),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    verifier = (gateway / "app/routers/mcp_public.py").read_text()
    compile(verifier, "mcp_public.py", "exec")
    assert 'Path(__file__).resolve().parents[2].parent / "sdk" / "python"' in verifier
    assert (
        (gateway / "app/routers/mcp_public.py")
        .resolve()
        .parents[2]
        .parent.joinpath("sdk", "python", "src", "b2a_sdk", "receipt_verifier.py")
        .is_file()
    )

    config = tomllib.loads((gateway / "pyproject.toml").read_text())
    assert config["tool"]["pytest"]["ini_options"]["pythonpath"] == [
        ".",
        "../sdk/python/src",
        "../integrations/openai-agent-middleware/src",
        "../integrations",
    ]
    wrapper_settings = tomllib.loads(wrapper_config.read_text())
    assert wrapper_settings["tool"]["pytest"]["ini_options"]["pythonpath"] == [
        "src",
        "../../sdk/python/src",
    ]

    for name in ("dry_run_example.py", "mcp_tool_example.py"):
        example = (tmp_path / "examples" / name).read_text()
        compile(example, name, "exec")
        assert '"sdk", "python", "src"' in example
        assert '"b2a_sdk", "src"' not in example
    assert "./sdk/python[dev]" in (tmp_path / "examples/README.md").read_text()
    framework_tools = (
        tmp_path / "integrations/framework_integrations/tools.py"
    ).read_text()
    assert "integrations/crewai-agent-middleware" in framework_tools
    assert "wrappers/crewai-agent-middleware" not in framework_tools
