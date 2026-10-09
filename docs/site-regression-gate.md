# Site regression gate (required release step for site changes)

The three regression scripts in `tests/` run outside the Python suite and
outside CI's browser-less jobs. Run them through the gate before any site
release. The gate runs every script to completion, reports each one
separately, and exits nonzero unless all pass.

```bash
make site-regression-gate
```

With no arguments the gate builds the site into a fresh temporary directory
using placeholder launch contacts, serves that preview on loopback, runs the
three scripts, then tears the server down. To target a preview you already
serve, or to use an installed Playwright module and keep screenshots:

```bash
SITE_PREVIEW_URL=http://127.0.0.1:8765 PLAYWRIGHT_PATH=/absolute/path/to/playwright/index.mjs \
  SCREENSHOT_DIR=/tmp/site-shots make site-regression-gate
```

Only loopback preview URLs are accepted. A missing browser driver fails the
gate; it never silently skips the browser checks.

## What runs

| Script | Needs | Reporting |
|---|---|---|
| `tests/test_arcade_regressions.mjs` | node only, no server, no browser | per-scenario results from `node --test`; also runs in CI |
| `tests/test_site_design.mjs` | local preview plus a browser driver | prints how many design scenarios passed |
| `tests/test_site_pilot_fit.mjs` | local preview plus a browser driver | prints a JSON summary with the calculator scenario count |

The two browser scripts stop at their first failing assertion, so a failure
names one scenario, not the whole run. The gate still runs the remaining
scripts and its closing summary names every script that passed or failed, so
one red scenario cannot hide the state of the rest.
