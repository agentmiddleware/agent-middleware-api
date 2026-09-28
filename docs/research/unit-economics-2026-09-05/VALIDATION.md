# Unit-economics report verification

Verified September 5, 2026 against repository HEAD `ebe36d7baaf0978b2c8160bd46d5b3ff8556f91f`.

## Completed checks

- Python model: 26 arithmetic, range, and reconciliation assertions passed. Revenue equals delivery cost plus contribution; per-unit totals reconcile; Enterprise cost reduces contribution dollar for dollar; included-volume revenue equals the base fee; labor calculations reconcile.
- Dated base-case cross-check: $2,400 revenue, $662.65 delivery cost, $1,737.35 contribution, 72.3896% margin before Enterprise allocation. A $1,000 allocation gives $737.35 contribution and 30.7229% margin.
- `ruff check docs/research/unit-economics-2026-09-05/model.py`: passed using the available global Ruff binary. This checkout does not have `.venv/bin/ruff`.
- `.venv/bin/python -m py_compile docs/research/unit-economics-2026-09-05/model.py`: passed.
- Headless Chromium: all four calculator scenarios matched the Python result snapshot for cost and contribution; the $1,000 and $2,000 Enterprise cases matched; zero attempts were rejected; zero revenue showed an undefined margin; reset restored the base scenario.
- Browser: no JavaScript errors; no document-level horizontal overflow at a 390-pixel mobile viewport. Desktop and mobile screenshots inspected.
- PDF: 26 pages, all 28 report sections present, no blank pages; extracted text reviewed for completeness. Rendered PDF pages 9 and 13 inspected for table readability, repeated headers, and page layout.
- Report: 38 local source/artifact links checked; every target exists and cited source lines are in range. All 11 generated-table placeholders resolved.
- Scope: only the new report folder was added; tracked application files and deployment configuration were unchanged.

## Reproduction

From the repository root:

```bash
.venv/bin/python docs/research/unit-economics-2026-09-05/model.py
ruff check docs/research/unit-economics-2026-09-05/model.py
.venv/bin/python -m py_compile docs/research/unit-economics-2026-09-05/model.py
```

The render/export scripts use already-installed `marked` and `playwright` libraries. The optional argument is the absolute module path when those modules are outside the normal Node resolution path:

```text
node build-report.mjs /absolute/path/to/marked/lib/marked.esm.js
node check-export.mjs /absolute/path/to/playwright/index.js
```

`build-report.mjs` refreshes marked table regions in the Markdown and writes HTML. It does not rewrite explanatory prose. `check-export.mjs` verifies the original dated baseline as well as the scenario snapshot, then writes the PDF. If assumptions change, update the prose and dated baseline checks before treating a new export as reviewed. These scripts install no dependencies and never access production.

## Not verified

No application tests, hosted CI, production benchmark, production database query, real customer pilot, invoice reconciliation, Enterprise quote, measured labor, conversion cohort, or paid renewal was executed or established by this report. Public prices and source code support the analysis; scenario outputs do not establish operating results or a deployable service quote.

## Recommended next step

Resolve the required Enterprise contract allocation, then replace assumed usage, support, onboarding, and exception inputs with one bounded paid partner pilot's measurements.
