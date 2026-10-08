#!/usr/bin/env python3
"""Fail when pytest coverage silently shrinks.

CI runs each pytest step with ``--junitxml`` and then calls this script on
the report. It enforces two things:

1. Skip ceiling: the total number of skipped tests must stay at or below
   ``--max-skipped``. A jump means a suite started skipping (new skipif,
   missing dependency, lost service) instead of running. When the suite
   legitimately gains skips, bump the number pinned in the CI workflow and say
   why in the comment next to it.
2. Must-run suites: every ``--expect-run`` prefix must match at least one
   collected test that was NOT skipped (catches an opt-in suite that a job
   is supposed to run reporting only skips). Every ``--expect-collected``
   prefix must match at least one collected test, skipped or not (catches
   a deleted or renamed file so a suite reports zero tests).

Skip reasons are printed grouped so a growing category is easy to spot.
Plain English, no network, reads only the XML files given on the command
line.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import Counter


def parse_reports(paths: list[str]) -> tuple[list[dict], Counter[str]]:
    cases: list[dict] = []
    reasons: Counter[str] = Counter()
    for path in paths:
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        for suite in suites:
            for case in suite.findall("testcase"):
                skipped = case.find("skipped")
                nodeid = f"{case.get('classname', '')}::{case.get('name', '')}"
                is_skipped = skipped is not None
                reason = ""
                if is_skipped:
                    reason = (skipped.get("message") or "").strip() or "(no reason)"
                    reasons[reason] += 1
                cases.append(
                    {"nodeid": nodeid, "skipped": is_skipped, "reason": reason}
                )
    return cases, reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--junitxml",
        action="append",
        default=[],
        help="pytest JUnit XML report (repeatable)",
    )
    parser.add_argument(
        "--max-skipped",
        type=int,
        required=True,
        help="fail if more tests than this were skipped",
    )
    parser.add_argument(
        "--expect-run",
        action="append",
        default=[],
        help="nodeid prefix with at least one non-skipped test",
    )
    parser.add_argument(
        "--expect-collected",
        action="append",
        default=[],
        help="nodeid prefix with at least one collected test",
    )
    args = parser.parse_args(argv)

    if not args.junitxml:
        print("check_suite_skips: no --junitxml given, nothing to check")
        return 2

    cases, reasons = parse_reports(args.junitxml)
    total = len(cases)
    skipped = sum(1 for c in cases if c["skipped"])
    print(f"collected={total} skipped={skipped} passed_or_other={total - skipped}")
    print("skip reasons (grouped):")
    for reason, count in reasons.most_common():
        print(f"  {count}x {reason}")

    failures: list[str] = []
    if skipped > args.max_skipped:
        failures.append(
            f"skipped count {skipped} exceeds ceiling {args.max_skipped}: "
            "a suite started skipping instead of running. Inspect the "
            "grouped reasons above; if the new skips are legitimate, bump "
            "--max-skipped in ci.yml with a comment saying why."
        )
    for prefix in args.expect_run:
        ran = [c for c in cases if c["nodeid"].startswith(prefix) and not c["skipped"]]
        collected = [c for c in cases if c["nodeid"].startswith(prefix)]
        if not collected:
            failures.append(
                f"suite '{prefix}' collected zero tests: the file may have "
                "been deleted or renamed."
            )
        elif not ran:
            failures.append(
                f"suite '{prefix}' collected {len(collected)} tests but all "
                f"skipped (e.g. '{collected[0]['reason']}'): a job that "
                "should run it is skipping it instead."
            )
    for prefix in args.expect_collected:
        if not any(c["nodeid"].startswith(prefix) for c in cases):
            failures.append(
                f"suite '{prefix}' collected zero tests: the file may have "
                "been deleted or renamed."
            )

    if failures:
        print("COVERAGE GUARD FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("coverage guard passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
