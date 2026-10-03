# Frontend and UX findings resolution — 2026-10-02

Scope: the five remaining frontend/UX findings in the
[QA evidence PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586),
covering [frontend charter #554](https://github.com/PetrefiedThunder/agent-middleware-api/issues/554)
and [UX charter #553](https://github.com/PetrefiedThunder/agent-middleware-api/issues/553).
All five were reproduced against `f82700f750862b6e51566a46dfc559e5b81e0a95`
before treating them as unresolved. Historical QA files were read from
`origin/qa/2026-10-02-sweep`; this change does not modify that evidence PR.

The worktree was verified as
`/Users/sellers/.openclaw/worktrees/amw-issues-20261002-frontend`, branch
`openclaw/amw-issues-20261002-frontend`, with origin
`https://github.com/PetrefiedThunder/agent-middleware-api.git` and initially clean status.

## Findings and fixes

| Finding | Root cause | Minimal change | Before and after evidence |
| --- | --- | --- | --- |
| FE-001 | `npm run build` invokes `tsc` with no project configuration, source input, output directory, or declaration settings. | Add `awi_sdk/typescript/tsconfig.json` with `index.ts`, CommonJS/ES2020 output, strict checks, declarations, and `dist`. Set `private: true` to keep the unshipped SDK unpublished. | Original declared build exits 1 with compiler help. Fixed declared build exits 0. `npm pack --dry-run --json --ignore-scripts` contains advertised `dist/index.js` and `dist/index.d.ts`. |
| FE-002 | `options?.maxSteps || 100` turns explicit zero into 100. | Use `?? 100`, preserving explicit values for the API's existing minimum/maximum checks. Add an Axios-adapter contract test that captures the actual serialized request and propagates a synthetic 422. | Original test fails `100 !== 0`. Fixed test passes; omitted limit remains 100, limits 1/1000 and invalid -1/1001 remain unchanged, and explicit `allowHumanPause: false` remains false. No network request is made. |
| UX-001 | `.fit-list li` uses dark-surface text on the paper card. | Scope `--paper-dim` to `.proof-col:not(.replay) .fit-list li`; leave the dark card's colors intact. | Computed paper contrast increases from 2.1308:1 to 6.9376:1. Four failing list nodes become zero axe contrast violations in Chromium, Firefox, and WebKit. Dark-card text still passes. |
| UX-002 | The horizontally scrolling command `<pre>` has no explicit focusability or accessible name. | Add `tabindex="0"`, `role="region"`, and `aria-labelledby="inspection-heading"`; retain the existing visible focus style. | All three engines reach the fixed region using Tab, expose its heading, show a 2px solid focus outline, and scroll with ArrowRight. WebKit could not reach the original region. Axe's original `scrollable-region-focusable` violation clears in all engines. |
| UX-003 | Runtime/discovery links and authenticated examples embed the production API origin. | Make runtime, key, manifest, and llms links root-relative. Use an explicit local `API_URL` with instructions to select this page's origin. Label the separate public proof as hosted. | Browser-read destinations resolve to the loopback origin; every authenticated example uses `${API_URL}`. Hosted proof remains a separately labeled external link. Links and commands were inspected, not followed or executed. |

## Files changed

- `awi_sdk/typescript/index.ts`: preserve explicit session limits.
- `awi_sdk/typescript/package.json`: private SDK guard and reproducible test command.
- `awi_sdk/typescript/tsconfig.json`: declared build configuration.
- `awi_sdk/typescript/tests/session.test.cjs`: two transport-level regressions.
- `site/styles.css`: paper-card list contrast.
- `static/dashboard.html`: keyboard-accessible command region and origin-correct guidance.
- This report.

No dependency was added or upgraded in the repository. The isolated build
installed the already-declared ranges: TypeScript 5.9.3, Axios 1.20.0, and
`@types/node` 20.19.43. It used Node 26.7.0 and npm 11.19.0. The SDK remains
private/unshipped; packaging was a local dry run, not publication.

## Verification

Raw safe logs, the browser probe, JSON results, and screenshots are retained at
`/tmp/amw-all-issues-20261002/frontend/`. Commands ran from this worktree unless
an isolated package directory is specified.

| Check | Result | Raw evidence |
| --- | --- | --- |
| Baseline isolated `npm run build` | Exit 1: no tsconfig/source input | `sdk-build-red.log` |
| Baseline explicitly compiled SDK + `node --test tests/session.test.cjs` | 1 pass, 1 expected failure: `100 !== 0` | `sdk-contract-red.log` |
| Fixed isolated `npm test` | Declared build succeeds; 2 tests pass, 0 skipped/TODO | `sdk-contract-green.log` |
| Fixed `npm pack --dry-run --json --ignore-scripts` and entrypoint/private assertions | Both advertised entrypoints present; private guard true | `sdk-package-dry-run.json` |
| `PUBLIC_DISPLAY_NAME='Design Partner Labs LLC' PUBLIC_CONTACT_EMAIL='operator@design-partner-labs.org' npm run build --prefix site` | Exit 0 using the repository's synthetic contact fixture; no contact or publication | `site-build-green.log` |
| `/Users/sellers/Projects/agent-middleware-api/.venv/bin/python -m pytest tests/test_dashboard_design.py tests/test_wedge_honesty.py tests/test_site_agent_interface.py --no-cov` | **85 passed in 7.70s** | `pytest.log` |
| `node --test tests/test_arcade_regressions.mjs` | **6 passed** | `arcade-regressions.log` |
| `node tests/test_site_design.mjs http://127.0.0.1:18866 /private/tmp/openclaw-qa-browser-20261002/node_modules/playwright/index.mjs /tmp/amw-all-issues-20261002/frontend/design-screenshots` | **78 design scenarios passed**: shell, responsive layout, keyboard, accessibility preferences, no-JavaScript rendering | `site-design.log` |
| Targeted Playwright 1.63.0 / axe 4.13.0 baseline and fixed probes at 390x844 in Chromium, Firefox, WebKit | **All assertions passed**; both reported axe violations clear; keyboard/origin checks pass | `browser-probe.cjs`, `browser-probe.log`, `browser-results.json`, engine-specific before/after screenshots |
| `git diff --check` | Pass | Local diff check |

The baseline build failed before explicit-source compilation; explicit-source
compilation was used only to execute the FE-002 regression against the original
implementation. The fixed run used the declared package build.

The browser probe allowed only its loopback preview origin; other browser
requests were aborted. It used original CSS/dashboard content from `git show
f82700f` for negative controls. The initial rapid-key WebKit probe sampled before
native scrolling completed. A held-key diagnostic verified 0 → 164px scrolling;
the final probe waits for native scrolling and passes in all three engines.
The initial probe and diagnostic logs remain alongside the final evidence.

An initial local build using an `.invalid` contact was correctly refused by the
existing launch validator. The successful build uses the same synthetic fixture
as `tests/test_site_agent_interface.py`. A preview-port conflict was resolved by
using port 18866; no existing listener was stopped.

## Limits and next step

These are local source/build/browser results. There was no live authenticated
API call, production call, provider change, publish, push, deployment, or remote
CI run. The SDK rejection test stubs the API's 422; it does not claim a deployed
API exercise. Native Safari, mobile hardware, and screen readers were not
tested; automated WebKit was tested. No new runtime JavaScript was added.

The next step is independent gate review of the frozen commit followed by the
coordinator's local integration and focused verification. Remote release actions
remain outside this lane's authorization.
