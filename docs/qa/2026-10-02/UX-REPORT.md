# UX QA report — 2026-10-02

Resumed an interrupted sweep; existing logs/artifacts retained. Local-only browser pass, no credentials or authenticated production calls.

## Written exploratory charters

1. **Accessibility and keyboard (15 minutes):** Public overview/proof/compare/404 and operator index; axe WCAG 2.2 A/AA; landmark/headings/accessible names; skip link, tab order, accessibility options, calculator labels and status announcements. Goal: a keyboard or screen-reader user can discover the pilot and interpret evidence without hidden information.
2. **Responsive and state behavior (10 minutes):** 1440px desktop, 390px mobile, 320px reflow; calculator empty/invalid/valid states; reduced motion; default and enlarged text; screenshot important states. Goal: no clipped controls, trapped focus, or ambiguous recovery.
3. **Nielsen/developer experience (10 minutes):** Review ten heuristics against public pages and README/quickstart using code-backed evidence; inspect error recovery, user control, consistency, documentation accuracy, and stated limits. Goal: a new integrator can identify a safe local path and understand operational boundaries.

Axe is a sampled automated check, not WCAG certification. Screen-reader semantics are inspected from the accessibility tree; no physical assistive-technology speech session. Browser outbound requests are blocked except loopback, and public API calls are mocked or blocked.

## Results

Counts: Critical=0 High=0 Medium=2 Low=1

The UX pass is complete with the limits below. Product files were not changed. Three finding-linked Playwright regressions use `test.fail(true, "UX-...")`; syntax and discovery passed, but their Playwright runtime execution is blocked by this machine's browser-launch sandbox.

### Findings

| ID | Severity | Group | Title | Exact reproduction | Expected vs actual | Evidence | Suggested fix |
|---|---|---|---|---|---|---|---|
| UX-001 | Medium | UX | Comparison fit text fails WCAG AA contrast | Build the site as recorded by Frontend QA; serve locally; open `/compare/#who-title` at 390×844 with default colors. Run axe WCAG A/AA or inspect the four “A good fit” list items. | Expected normal text contrast ≥4.5:1. Actual four items use `#9ca8cb` on `#f6f3e9`, measured 2.13:1. | [`site/styles.css:1802`](../../../site/styles.css#L1802), paper background at line779; [`site/compare/index.html:365`](../../../site/compare/index.html#L365); [axe report](artifacts/ux-axe-compare-mobile.json); [screenshot](artifacts/ux-cua-compare-low-contrast.jpg); `UX-001: comparison fit text meets minimum contrast`. | Give `.proof-col:not(.replay) .fit-list li` a paper-surface text color such as the existing `--paper-dim`; retain the current light text on dark cards. Re-run axe at desktop/mobile and high contrast. |
| UX-002 | Medium | UX | Dashboard scrolling commands lack explicit keyboard access | Serve `static/dashboard.html` locally (the runtime `/dashboard` route returns this file); open at 390×844; inspect “Authenticated inspection”; run axe. | Expected a keyboard user can enter and scroll the command region on supported browsers. Actual `<pre>` is 348px wide with 512px scroll content, `tabIndex=-1`, and no focusable descendants. Axe flags `scrollable-region-focusable`, specifically for Safari keyboard accessibility. Physical Safari interaction is **not verified** because WebKit could not launch. | [`static/dashboard.html:373`](../../../static/dashboard.html#L373), overflow rule at215; [axe report](artifacts/ux-axe-dashboard-mobile.json); [screenshot](artifacts/ux-cua-dashboard-scroll-region.jpg); `UX-002: dashboard scrollable commands have explicit keyboard access`. | Add `tabindex="0"` and a concise accessible name/region association to the scrolling code block; verify arrow-key access and a visible focus indicator in Safari as well as Chromium/Firefox. |
| UX-003 | Low | UX | A locally served operator dashboard points runtime inspection at production | Open the local dashboard and inspect the `Runtime truth`, trust-key, agent-manifest links and the three authenticated curl examples. Do **not** follow links or run examples. | Expected an operator viewing a local/staging runtime can inspect that runtime, or clearly see that a link targets a separately hosted public sample. Actual links and terminal examples always target `https://api.thisisatest.tech`, even when the page is served on loopback. | [`app/routers/static.py:159`](../../../app/routers/static.py#L159) serves the unmodified file; [`static/dashboard.html:342`](../../../static/dashboard.html#L342),346,356,377–385; [dashboard screenshot](artifacts/ux-cua-dashboard-scroll-region.jpg); `UX-003: operator runtime links remain on the served origin`. | Use same-origin relative links for runtime inspection and an explicit `API_URL` in terminal examples; label hosted public proof separately. This sweep did not contact the production destination. |

### Automated accessibility and responsive evidence

Axe-core **4.13.0**, tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`, ran in the available Chrome extension browser against QA loopback servers. Six 390×844 page samples produced two rule violations across five nodes, 138 passing rule-page outcomes, and five incomplete rule-page outcomes requiring further manual review. This is not WCAG certification.

| Page | Violations | Passing rules | Incomplete | Document/viewport width | Report |
|---|---:|---:|---:|---|---|
| Overview | 0 | 32 | 2 | 390/390 | [JSON](artifacts/ux-axe-home-mobile.json) |
| Proof | 0 | 22 | 1 | 390/390 | [JSON](artifacts/ux-axe-proof-mobile.json) |
| Compare | 1 (4 nodes) | 29 | 1 | 390/390 | [JSON](artifacts/ux-axe-compare-mobile.json) |
| 404 | 0 | 18 | 0 | 390/390 | [JSON](artifacts/ux-axe-404-mobile.json) |
| Concept | 0 | 19 | 1 | 390/390 | [JSON](artifacts/ux-axe-concept-mobile.json) |
| Dashboard | 1 (1 node) | 18 | 0 | 390/390 | [JSON](artifacts/ux-axe-dashboard-mobile.json) |

The initial desktop overview was captured at the browser's actual 1728px width; document width matched it. At 320px, overview text enlarged to 140% through the product's accessibility panel still had document width320px. [Desktop](artifacts/ux-cua-home-desktop.jpg), [mobile](artifacts/ux-cua-home-mobile.jpg), [140% text at320px](artifacts/ux-cua-home-enlarged-320.jpg). These are sampled reflow observations, not a complete 200%/400% zoom assessment.

The first calculator captures suffered a CUA screenshot scaling issue (tiny column plus excess black space); they are retained as dead-end evidence. Use the readable [invalid-state retake](artifacts/ux-cua-calculator-invalid-retake.jpg), captured with `innerWidth=390`, `innerHeight=844`, and root font size16px. The invalid status text is separately recorded in [DOM semantics](artifacts/ux-cua-calculator-invalid-semantics.txt); that retake shows the invalid input, while its guidance is below the viewport.

### Keyboard, semantics, and state checks

- **Verified:** first Tab from page start selected “Skip to content”; Enter changed the fragment to `#main`. Chrome reported BODY as the active element after anchor navigation. A subsequent-navigation focus-sequence check was attempted but did not complete; no full skip-link focus claim is made.
- **Verified:** keyboard activation of “Accessibility options” focused its named `role=dialog`. Escape closed it and returned focus to the trigger. The text controls expose accessible names; switches expose pressed state in the recorded DOM tree. The control's non-modal semantics match its ability to leave focus outside the panel.
- **Verified:** a single H1 and main landmark appear on the overview; site navigation, headings, field labels, dialog names, and live-result semantics are exposed in the retained DOM snapshots. Proof, comparison, 404, concept, and dashboard snapshots are saved as `ux-cua-*-semantics.txt`.
- **Verified:** calculator empty text asks for four assumptions; entering `-1` actions sets `aria-invalid=true` and displays correction guidance. Inputs `100000`, `0.1`, `50`, `80`, `2800` yield $4,000 estimated avoided loss, $1,200 excess, $35 break-even, and a warning that assumptions do not prove savings.
- **Verified:** 404 gives a plain explanation and recovery links; the UI labels receipt proof as historical and self-issued. The page read did not make a new cryptographic-verification claim.
- **Not verified:** physical screen-reader speech, complete keyboard tab order, reduced-motion animation behavior, 200%/400% zoom, touch-device interaction, native Firefox/WebKit rendering, and actual email/book-a-call handoff. Two late CUA input dispatch deadlines prevented the extra reduced-motion and skip-next-focus check; these failures are logged.
- **Partially verified:** empty/error UX is exercised for the calculator and 404; proof loading/failure states are source-reviewed here and covered by the Frontend pass's isolated DOM checks. A real-browser forced-network-error screenshot was not obtained.

### Nielsen ten-heuristic review (source and sampled UI)

| Heuristic | Observation |
|---|---|
| Visibility of system status | Calculator result is a polite live region and updates synchronously; published proof distinguishes loaded historical artifacts. Loading/failure browser coverage remains limited as above. |
| Match with the real world | Refund/retry examples and credit-cost explanation connect terminology to a consequential action; credit units are expressly separate from payment rails. |
| User control and freedom | Accessibility reset and Escape/focus return work. Contact actions disclose opening the mail app; no contact or booking action was submitted. |
| Consistency and standards | Shared navigation/footer and headings are consistent across sampled site pages. UX-003 breaks expected runtime-origin consistency. |
| Error prevention | Numeric minima, percentage maxima, required fields, and assumption language reduce invalid economic conclusions. Boundary arithmetic is covered by Frontend tests. |
| Recognition rather than recall | Form labels, rate example, optional-cost helper, and proof commands are visible. UX-002 makes long commands harder to access by keyboard in Safari. |
| Flexibility and efficiency | Accessibility text size and Escape controls help repeat use; proof artifacts offer a direct offline path. No physical assistive-technology session was performed. |
| Aesthetic/minimalist design | Main offer and evidence are explicit. The optional arcade is outside the transaction-control task and was not prioritized over the core onboarding/inspection path. UX-001 makes buyer-fit content hard to read. |
| Help recognize/diagnose/recover | Calculator invalid guidance and 404 recovery are present. The calculator uses a general live error rather than per-field prose, while `aria-invalid` identifies the bad field. |
| Help and documentation | README presents local demo and strict-trust quickstart paths; quickstart names prerequisites, a second terminal, synthetic credits, reset-before-repeat, and offline verification. Actual boot/API correctness is owned by Backend QA. |

### Reproduction, execution limits, and handoff

- `ux_browser_qa.cjs` retains the original local-only Playwright exploration/axe/screenshot harness. Its Chromium launch failed before navigation with macOS `MachPortRendezvousServer` permission denial/SIGTRAP. The Frontend pass separately recorded Firefox/WebKit launch failures. Do not count these as failing product assertions.
- `ux_csp_server.py` retains the successful fallback harness. It serves the existing temporary site build on127.0.0.1:8769 and dashboard on127.0.0.1:8770, injects only local axe/test scripts, and enforces `connect-src 'self'`, external-source restrictions, no frames/objects, and `form-action 'self'`. Headers and local instrumentation were checked before browser navigation. No production link was followed.
- CUA used a pre-existing Chrome profile with extension UI present. A 1Password live region caused an ambiguous unscoped `role=status` lookup; the test correctly scoped the product result and continued. This fallback is less isolated than the failed fresh Playwright contexts, and the report states that limit.
- `ux-regressions.spec.cjs` adds three expected-failure tests tied to UX-001/002/003. `node --check` passed; Playwright listed all9 project/test combinations. Their runtime assertions were **not run** after the independently proven browser-launch block. `playwright.config.cjs` changed only its discovery pattern to include this file.
- Original CSP server shutdown via SIGTERM was refused by the sandbox; the owned exec session was then interrupted safely. The final instrumented server shut down through its QA-only loopback endpoint. Ports8767–8770 were verified closed; browser viewport was reset and the QA tab closed.
- No product behavior, production setting, credentials, environment file, migration, deployment, billing, or remote Git state was modified. All changes remain uncommitted for the orchestrator.

Recommended fix order: UX-001 contrast, UX-002 keyboard-scrolling region, UX-003 origin-safe operator links. Then repeat the three expected failures in fresh Chromium/Firefox/WebKit contexts, review axe's incomplete checks, and complete physical screen-reader and zoom testing.
