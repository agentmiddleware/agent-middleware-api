# Validation record — economics reconsidered

Finalized September 8, 2026. Provider and public-source observations were collected September 5 Pacific time / September 6 UTC; their timestamps are retained. Source HEAD was rechecked at finalization and remains 795cd9b3c691a2c697bfef364546940dd5780e93.

This validates the research artifact and its arithmetic. It does not qualify an application deployment or establish actual customer unit economics.

## Completed checks

- **33 Python checks passed.** Both billing-period project totals reconcile to their services; each service reconciles to CPU, memory, volume, egress, and backup components. Independent base arithmetic, exception-hour units, support sensitivity, zero revenue, zero volume, usage-credit minimums, incremental commitment behavior, invalid inputs, and the target-price equation passed.
- **Five Python/JavaScript scenario comparisons passed.** Displayed contribution and cost match model results to currency rounding; margins match to one decimal percentage point.
- **Browser checks passed.** Negative contribution, zero revenue, zero attempts, empty and negative inputs, percentages above 100, reset, and navigation anchors were checked. No JavaScript errors or whole-page mobile overflow at 390px.
- **PDF exported: 22 pages.** All 26 section headings are present; no empty pages. Visual inspection of pages 1, 9, and 22 found readable text and tables without clipping. Mobile preview was also inspected.
- **All 20 local file links resolve.** Linked source lines, where specified, are within their files. There are 18 Markdown tables.
- **Standalone model lint and compilation passed.** Ruff formatting/check and Python byte compilation completed. Node syntax checks covered the builder, calculator, and export checker.
- **Application changes: none.** Git status contains the research directories only. No runtime, public API, authentication, billing, migration, or deployment configuration was edited.

## Reproduce the scenario outputs

From the repository root:

    .venv/bin/python docs/research/unit-economics-reconsidered-2026-09-05/model.py

The model reads the saved, sanitized provider usage observation and writes assumptions.json, model-results.json, scenarios.csv, and calculated-tables.md. It neither queries customer data nor imports the application.

The generated HTML/PDF presentation files are intentionally excluded from this
curated source set. Rebuild them with the retained scripts by passing installed
`marked` and `playwright` module paths:

    node docs/research/unit-economics-reconsidered-2026-09-05/build-report.mjs /absolute/path/to/marked/lib/marked.esm.js

    node docs/research/unit-economics-reconsidered-2026-09-05/check-export.mjs /absolute/path/to/playwright/index.js

The builder refreshes marked tables in `REPORT.md` and writes HTML. The checker
writes the PDF and browser-validation snapshot. The Python model, inputs, saved
outputs, and report remain the canonical economics record.

Lint and compile commands used:

    ruff format --check docs/research/unit-economics-reconsidered-2026-09-05/model.py
    ruff check docs/research/unit-economics-reconsidered-2026-09-05/model.py
    python3 -m py_compile docs/research/unit-economics-reconsidered-2026-09-05/model.py

## Observation provenance and limits

Provider evidence came from authenticated, read-only Railway project usage queries for the previous and current billing periods. Workspace/service identifiers were removed from the saved financial observation. Project totals are resource usage, not full paid invoices. The previous period includes varying service lifetimes; the current period is partial.

The public health response was retrieved with GET from https://api.thisisatest.tech/health/dependencies. It reports a different deployed commit and explicitly distinguishes process-local counters from durable dispatch history. No tool invocation was made to create additional economic activity.

A seven-day HTTP metrics query failed the provider data-point limit. The shorter one-day query returned no request measurements. No throughput denominator was inferred from those queries. The separate resource metrics summary contained current readings, not measured historical averages.

An initial HTML check detected horizontal overflow caused by long commit hashes. Adding text wrapping resolved it; the full browser checks then passed. The final PDF and HTML contain the fix.

## Not tested or established

Application tests, type checks for app, production load, crash behavior, live customer integrations, competitor implementations, competitor customers, full account payment/settlement, contract terms, sales conversion, churn, renewal, and buyer willingness to pay were not tested or established here. The application suite was not run because this revision adds report artifacts only.

Published offers were inspected as primary-source statements, not mystery-shopped or purchased. Public issues were checked for content and attribution, not independently reproduced. The source audit lowered the confidence assigned to several demand claims.

The report makes a decision under uncertainty. Passing its arithmetic and export checks does not validate its hypothetical operating inputs.
