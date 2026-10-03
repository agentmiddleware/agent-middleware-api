# Proposed draft PR

**Suggested title:** Resolve AMW QA findings and document single-action integration acceptance

This file is a reviewable publication draft. No PR has been created for the repair branch.

## Problem and resulting behavior

The unpublished AMW audit identified 82 findings in authorization, money precision/accounting, durable action ownership, integrations, release tooling and clients. The candidate preserves 79 local fixes and three explicit retirements, then corrects eight remaining findings from the separate [QA evidence PR586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586).

Bearer/API-key alternatives are discoverable through OpenAPI without changing Authorization precedence. Multicast destinations fail before outbound dispatch. The checked-in private TypeScript SDK builds its promised entrypoints and preserves explicit zero step limits for rejection. Operator UI commands are keyboard-accessible, runtime links follow the served origin and comparison text has readable contrast. Integration documentation states the actual at-most-one and missing-receipt/manual-review limits.

## Inherited scope

This is a substantial integration built on previously unpublished single-action work (`62066eed`, then `dc3da89f`), including schema042 and the 82 audit remedies (`f82700f`). It is broader than the eight follow-up changes. Preserve upstream041 as migration042's parent. [Schema042 rollout prerequisites](../schema-042-rollout.md) require separate operational evidence before release. No migration or deployment against an operational system was performed.

## Issue and PR traceability

Parent: https://github.com/PetrefiedThunder/agent-middleware-api/issues/499

Existing PR586 contains a separate QA report and tests; it does not contain these fixes. The full finding-to-code/evidence mapping is in [issue-index.md](issue-index.md) and [issue-ledger.json](issue-ledger.json). All findings remain open for acceptance/release tracking; this draft uses references rather than auto-closing statements.

- accounting_data: #500, #501, #502, #520, #521, #522, #523, #539, #541, #542, #543, #557, #558, #559, #584, #585.
- action_execution: #512, #519, #524, #540.
- awi_ordering: #526.
- clients_docs: #509, #510, #511, #529, #530, #531, #532, #538, #560, #561, #562, #563, #564, #565, #566, #567, #568, #569, #570, #571, #572.
- infrastructure_proofs: #533, #534, #535, #536, #537, #547, #548, #549, #550, #551, #552, #573, #574, #575, #576, #577, #578, #579, #580.
- integrations_product: #513, #514, #515, #516, #517, #518, #527, #528, #544, #545, #546, #581, #582, #583.
- security_runtime: #503, #504, #505, #506, #507, #508, #525.

Broad QA charters: #553, #554, #555, #556. Their 36 acceptance checks are mapped in [charter-coverage.md](charter-coverage.md); this PR would not establish full charter completion.

## Validation

Final combined suite at `4ac5a56`: **4,866 passed, 85 skipped, 6 warnings, zero failures**, including proof surfaces. Exact command, source identity and skip reasons are recorded in [README](README.md) and retained evidence. Per-domain counts overlap and are not summed. Independent gate review found no blocking finding across reviewed repairs and follow-up commits. Fresh PostgreSQL checks passed 12 accounting, 10 process/crash-recovery and 1 migration, in addition to targeted migration038 and approval-expiry proofs. All-files Ruff, format, mypy, generated OpenAPI and documentation/inventory checks passed. Frontend negative controls and fixed checks passed in Chromium, Firefox and WebKit.

The original interrupted audit run, a temporary-directory mismatch in the first resumed suite, and the corrected runner result remain documented. No test expectation, security boundary or scanner suppression was weakened to obtain a pass.

## Release limits

No production/provider/payment/customer execution is established. Existing scanner baseline candidates remain qualified; no full-history zero-secret assertion. Docker base-digest/development-dependency requirements and broader charter coverage remain open. PR586 CI applies to its evidence-only source, not this unpublished candidate. Hosted CI on this PR, release authorization and migration/deployment readiness must be assessed separately.
