# Pilot package validation

September 8, 2026. Source HEAD: 795cd9b3c691a2c697bfef364546940dd5780e93.

## Completed

- Nine-sheet workbook created with 126 formulas and no external workbook links.
- All formulas recalculated by LibreOffice; cached results inspected with openpyxl in data-only mode. No Excel formula errors found.
- Three prototype formulas were verified against independent arithmetic before the full workbook was built.
- Setup planning cost $1,697.80 and contribution $802.20 verified. Recurring planning cost $438.175 and contribution $1,061.825 verified before display rounding.
- Actuals defaults to Pending despite populated Plan and fictional Example sheets.
- A fixture with 100,000 accepted identities, 3.125 labor hours, $99.271 nonlabor cost, $999 earned fees and a $100 revenue credit produced $565.354 contribution.
- That fixture also included large out-of-period and wrong-phase entries, which were correctly excluded. An October collection for September earned revenue did not enter September cash collections.
- Technical and commercial acceptance remained Pending when rows were marked Pass without owner/date/evidence.
- Confirmed complete empty records produced actual zeros, with Undefined margin and unit cost instead of division errors.
- Complete partner evidence allowed a technical Pass and a separate commercial Committed status; a failed row produced Fail/Declined.
- Reversed period dates returned Pending. An impossible margin target returned Unreachable. Zero planned revenue returned Undefined margin.
- The final formatting-only rebuild retained 126 formulas, no formula errors, Pending actuals, and the independently checked recurring contribution.
- PDF: six pages, all seven section headings, all eleven acceptance IDs, eight valid local links, and no empty pages. Mobile HTML has no whole-page overflow.
- Visual review covered memo pages 1 and 3 and workbook readme/log previews. Case IDs were adjusted to stay on one line and input rows received visible separators.
- Ruff formatting/check and Python byte compilation passed for build_tracker.py. No application code was changed.

## Reproduce

Use a Python environment with `openpyxl` and `xlsxwriter` installed:

    python3 docs/research/paid-pilot-2026-09-08/build_tracker.py

This rebuilds a blank tracker, replacing any filled tracker at that output path. Preserve a filled operational copy separately.

Recalculate the generated XLSX into a separate output directory, then replace the generated copy with the recalculated result:

    soffice --headless --convert-to xlsx --outdir /tmp/amw-pilot-final-recalc docs/research/paid-pilot-2026-09-08/pilot-tracker.xlsx

The spreadsheet skill's macro-based recalc.py was attempted at 30 and 60 seconds on the prototype and timed out without recalculating. LibreOffice's XLSX conversion path successfully recalculated the workbook instead. Cached values and preserved formulas were independently checked; the delivered workbook contains the recalculated result, not the uncached generator output.

Render the memo with Node, passing installed `marked` and `playwright` module
paths:

    node docs/research/paid-pilot-2026-09-08/render_pack.mjs /absolute/path/to/marked/lib/marked.esm.js /absolute/path/to/playwright/index.js

No dependencies were installed. The fixture workbooks were kept under /tmp and are not included as customer records.

## Qualification evidence

An authenticated read-only search for the existing sender after September 5 returned no messages. The existing conversation was read directly and still ended with the September 5 five-question qualification message. The earlier inbound reply expressed interest but supplied none of the five required qualification answers.

This supports the documented Pending status as of this check. It does not establish that the candidate has no budget or cannot qualify later. Private names, email addresses, and correspondence were not copied into the repository artifacts.

No outreach was sent, calendar invitation created, monitoring process added, payment requested, infrastructure purchased, or deployment changed.

## Not tested

The partner acceptance cases have not been run. Customer workflow, deployment qualification, actual provider contract, payment, willingness to pay, performance capacity, and retention remain unverified. The application test suite was not run for this documentation/workbook task.

## Curated files

- `PILOT_PACKAGE.md`: scoped offer and acceptance workflow.
- `build_tracker.py` and `render_pack.mjs`: reproducible artifact generation.
- `VALIDATION.md`: historical validation record and reproduction notes.

The generated HTML, PDF, workbook, validation snapshots, and historical checksum
manifest are intentionally excluded. Regenerate them locally when needed and do
not commit a filled operational tracker.
