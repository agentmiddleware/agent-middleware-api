"""The `perf` marker contract: the checkout latency budget stays enforced.

`make test` skips `perf` tests because a wall-clock budget times the runner as
much as the code, so a busy dev machine fails it with nothing wrong. That is
only safe while CI still runs them under the real budget: the 45ms bound in
`tests/test_acp_bridge.py` is enforced by the CI step that runs the whole
`tests/` directory. Two edits would silently stop enforcing it while the docs
kept saying it is enforced, and this pins against both: a marker filter that
drops `perf` from that step, and widening `ACP_CHECKOUT_MEDIAN_BUDGET_S` in CI.
It also pins the local half (`make test` skips perf, `make test-perf` runs it).

Deliberately not covered: quarantining the one test by node id (`--deselect`,
`-k`), which this repo does not use. A deliberate restructure — say, moving
perf into its own CI step — fails here on purpose, so the contract is updated
alongside it.
"""

import re
import shlex

import yaml

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"

# `pytest tests/` running the whole directory — not `pytest tests/test_x.py`.
WHOLE_SUITE = re.compile(r"(?<![\w/.-])pytest\s+tests/(?=\s|$)")


def _marker_exprs(command):
    """Every -m expression passed to the whole-suite `pytest tests/` call.

    Parsing starts at `pytest`, so the `-m` in `python -m pytest` is not
    mistaken for a marker expression.
    """
    match = WHOLE_SUITE.search(command)
    assert match, f"no whole-suite `pytest tests/` call in {command!r}"
    invocation = command[match.start() :].replace("\\\n", " ").split("\n", 1)[0]
    tokens = shlex.split(invocation)
    exprs = []
    for index, token in enumerate(tokens):
        if token == "-m" and index + 1 < len(tokens):
            exprs.append(tokens[index + 1])
        elif token.startswith("-m") and len(token) > 2:
            exprs.append(token[2:])
    return exprs


def _make_recipe(target):
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*(?:\n|$))+)", makefile, re.M
    )
    assert match, f"Makefile has no `{target}` target with a recipe"
    return match.group(1)


def _ci_whole_suite_commands():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    return [
        step["run"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if WHOLE_SUITE.search(step.get("run", ""))
    ]


def test_ci_whole_suite_run_does_not_filter_perf():
    """CI is the only place the latency budget is enforced; it must select perf."""
    commands = _ci_whole_suite_commands()
    assert commands, "no CI step runs the whole tests/ directory"
    for command in commands:
        for expr in _marker_exprs(command):
            assert "perf" not in expr, (
                f"CI deselects perf tests ({expr!r}), so the 45ms checkout "
                "budget would no longer be enforced anywhere. Keep perf in CI; "
                "it is skipped only by the local `make test` loop."
            )


def test_ci_does_not_widen_the_latency_budget():
    """Overriding the budget in CI un-enforces it as surely as deselecting it."""
    assert "ACP_CHECKOUT_MEDIAN_BUDGET_S" not in CI_WORKFLOW.read_text(
        encoding="utf-8"
    ), "CI must enforce the default 45ms budget, not override it"


def test_make_test_skips_perf_and_make_test_perf_runs_it():
    """The local fast loop skips perf; `make test-perf` runs exactly perf."""
    assert any("not perf" in e for e in _marker_exprs(_make_recipe("test")))
    assert _marker_exprs(_make_recipe("test-perf")) == ["perf"]
