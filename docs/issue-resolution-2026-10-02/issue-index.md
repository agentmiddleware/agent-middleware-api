# Complete issue register — October 2, 2026

GitHub inventory: **87 open issues**, consisting of [parent #499](https://github.com/PetrefiedThunder/agent-middleware-api/issues/499), **82 findings**, and four QA charters. All issues remain open. This file records local remedy provenance; it does not certify release or deployment.

**Existing PR:** [#586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) contains a separate QA report and test evidence. It is not the fixing PR for the 82 findings. No fixing PR exists for these local commits.

**Recovered source:** `f82700f750862b6e51566a46dfc559e5b81e0a95`; 63 distinct fix/follow-up commits verified as ancestors; every cited original red, green and independent-review artifact exists. Historical evidence is preserved at /Users/sellers/Documents/Codex/2026-10-01/task-4. Fresh validation and additional repairs are summarized in [README](README.md).

[Machine-readable ledger](issue-ledger.json) retains detailed correction, commit and evidence mappings.

| Finding | GitHub issue | Severity | Local disposition | Domain handoff |
| --- | --- | --- | --- | --- |
| ACCT-001 | [#502 — Accepted sub-credit tool prices produce unverifiable quotes and receipts](https://github.com/PetrefiedThunder/agent-middleware-api/issues/502) | P2 | local_fixed | [Review](accounting.md) |
| ACCT-002 | [#500 — New client request keys can reuse one human approval to mint additional permits](https://github.com/PetrefiedThunder/agent-middleware-api/issues/500) | P1 | local_fixed | [Review](accounting.md) |
| ACCT-003 | [#501 — Permit-request approval can cross its local deadline while polling and still mint](https://github.com/PetrefiedThunder/agent-middleware-api/issues/501) | P2 | local_fixed | [Review](accounting.md) |
| ACCT-004 | [#520 — Startup schema verification misses every required single-action column](https://github.com/PetrefiedThunder/agent-middleware-api/issues/520) | P2 | local_fixed | [Review](accounting.md) |
| ACCT-005 | [#521 — Concurrent Stripe top-ups lose settled credits on SQLite](https://github.com/PetrefiedThunder/agent-middleware-api/issues/521) | P2 | local_fixed | [Review](accounting.md) |
| ACCT-006 | [#522 — Concurrent Stripe cumulative refunds double-claw back on SQLite](https://github.com/PetrefiedThunder/agent-middleware-api/issues/522) | P2 | local_fixed | [Review](accounting.md) |
| ACCT-007 | [#523 — PostgreSQL migration 038 cannot recover after concurrent-index interruption](https://github.com/PetrefiedThunder/agent-middleware-api/issues/523) | P2 | local_fixed | [Review](accounting.md) |
| ACCT-008 | [#539 — Zero-price tools receive signed quotes but cannot execute](https://github.com/PetrefiedThunder/agent-middleware-api/issues/539) | P2 | local_fixed | [Review](accounting.md) |
| ACCT-009 | [#541 — Terminal billing-policy denial leaves its idempotency key in progress](https://github.com/PetrefiedThunder/agent-middleware-api/issues/541) | P2 | local_fixed | [Review](accounting.md) |
| ACCT-010 | [#542 — Keyed billing charge for unknown wallet returns500 instead of404](https://github.com/PetrefiedThunder/agent-middleware-api/issues/542) | P2 | local_fixed | [Review](accounting.md) |
| ACCT-011 | [#543 — Ledger period exact totals are calculated from binary floats](https://github.com/PetrefiedThunder/agent-middleware-api/issues/543) | P3 | local_fixed | [Review](accounting.md) |
| ACCT-012 | [#557 — Wallet-scoped credentials can read global profitability and other tenants' ledger details](https://github.com/PetrefiedThunder/agent-middleware-api/issues/557) | P2 | local_fixed | [Review](accounting.md) |
| ACCT-013 | [#558 — Profitability report labels all-history totals as a one-day period](https://github.com/PetrefiedThunder/agent-middleware-api/issues/558) | P3 | local_fixed | [Review](accounting.md) |
| ACCT-014 | [#559 — Receiptless x402 crash recovery consumes permit budget twice](https://github.com/PetrefiedThunder/agent-middleware-api/issues/559) | P2 | local_fixed | [Review](accounting.md) |
| ACCT-015 | [#585 — Failed x402 compensation releases the accepted request owner](https://github.com/PetrefiedThunder/agent-middleware-api/issues/585) | P2 | local_fixed | [Review](accounting.md) |
| AE-001 | [#512 — Release exact issuance ownership after a proven pre-persistence rejection](https://github.com/PetrefiedThunder/agent-middleware-api/issues/512) | P3 | local_fixed | [Review](security-actions-integrations.md) |
| AE-002 | [#519 — Reuse the preparation transaction for action signature verification](https://github.com/PetrefiedThunder/agent-middleware-api/issues/519) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| AE-003 | [#540 — Retry local call-counter contention instead of caching false budget denial](https://github.com/PetrefiedThunder/agent-middleware-api/issues/540) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| INFRA-001 | [#533 — Failure Lab negative-control CI promotes judge crashes to success](https://github.com/PetrefiedThunder/agent-middleware-api/issues/533) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-002 | [#534 — Downloaded Failure Lab ZIP omits keys needed by its offline verifier](https://github.com/PetrefiedThunder/agent-middleware-api/issues/534) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-003 | [#535 — Live release preflight certifies missing posture fields as safe](https://github.com/PetrefiedThunder/agent-middleware-api/issues/535) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-004 | [#536 — Database-only preflight silently drops explicit release identity expectations](https://github.com/PetrefiedThunder/agent-middleware-api/issues/536) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-005 | [#537 — Development Compose hot reload command is ignored by the entrypoint](https://github.com/PetrefiedThunder/agent-middleware-api/issues/537) | P3 | local_fixed | [Review](infrastructure.md) |
| INFRA-006 | [#547 — Make crash-proof wrapper migrates before isolation checks](https://github.com/PetrefiedThunder/agent-middleware-api/issues/547) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-007 | [#548 — Rotation verification transmits bootstrap keys over remote HTTP](https://github.com/PetrefiedThunder/agent-middleware-api/issues/548) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-008 | [#549 — Partner bootstrap ignores successful --key-only output mode](https://github.com/PetrefiedThunder/agent-middleware-api/issues/549) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-009 | [#550 — Load battery stops a container it did not create](https://github.com/PetrefiedThunder/agent-middleware-api/issues/550) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-010 | [#551 — Load battery labels an all-error run PASS and exits zero](https://github.com/PetrefiedThunder/agent-middleware-api/issues/551) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-011 | [#552 — Loaded claim manifest promotes a PASS summary over FAIL/ERROR rows](https://github.com/PetrefiedThunder/agent-middleware-api/issues/552) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-012 | [#573 — Repo guardian caches failed full lint as a successful sweep](https://github.com/PetrefiedThunder/agent-middleware-api/issues/573) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-013 | [#574 — Live stress checks accept HTTP failures and absent receipt IDs](https://github.com/PetrefiedThunder/agent-middleware-api/issues/574) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-014 | [#575 — Adversarial battery forwards API keys across redirect origins](https://github.com/PetrefiedThunder/agent-middleware-api/issues/575) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-015 | [#576 — Comparison report interprets configuration errors as successful measurements](https://github.com/PetrefiedThunder/agent-middleware-api/issues/576) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-016 | [#577 — Diagnostic request size limit applies only after full buffering](https://github.com/PetrefiedThunder/agent-middleware-api/issues/577) | P2 | local_fixed | [Review](infrastructure.md) |
| INFRA-017 | [#578 — Agent-facing documentation advertises a nonexistent rate-limit burst](https://github.com/PetrefiedThunder/agent-middleware-api/issues/578) | P3 | local_fixed | [Review](infrastructure.md) |
| INFRA-018 | [#579 — Agent endpoint table labels production discovery authentication optional](https://github.com/PetrefiedThunder/agent-middleware-api/issues/579) | P3 | local_fixed | [Review](infrastructure.md) |
| INFRA-019 | [#580 — Troubleshooting treats an uncertain-delivery receipt as proof of acceptance](https://github.com/PetrefiedThunder/agent-middleware-api/issues/580) | P3 | local_fixed | [Review](infrastructure.md) |
| IP-001 | [#513 — Rehydrate durable AI decisions and heals before exposing them through typed routes](https://github.com/PetrefiedThunder/agent-middleware-api/issues/513) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| IP-002 | [#514 — Use the configured API root once when building OpenAI chat URLs](https://github.com/PetrefiedThunder/agent-middleware-api/issues/514) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| IP-003 | [#515 — Propagate structured DOM execution failure to AWI top-level status before accounting](https://github.com/PetrefiedThunder/agent-middleware-api/issues/515) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| IP-004 | [#516 — Prevent browser dispatch when AWI callers explicitly request a dry run](https://github.com/PetrefiedThunder/agent-middleware-api/issues/516) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| IP-005 | [#517 — Bind all effect-bearing AWI arguments into the idempotency identity](https://github.com/PetrefiedThunder/agent-middleware-api/issues/517) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| IP-006 | [#518 — Enforce signed AWI argument prohibitions and atomic per-tool call limits before execution](https://github.com/PetrefiedThunder/agent-middleware-api/issues/518) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| IP-007 | [#527 — Honor write-only and explicit-deny IoT topic ACLs](https://github.com/PetrefiedThunder/agent-middleware-api/issues/527) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| IP-008 | [#528 — Persist completed content campaigns and their pipeline links](https://github.com/PetrefiedThunder/agent-middleware-api/issues/528) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| IP-009 | [#544 — Generate valid Python literals in the behavioral sandbox wrapper](https://github.com/PetrefiedThunder/agent-middleware-api/issues/544) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| IP-010 | [#545 — Validate RTaaS attack categories at the request boundary](https://github.com/PetrefiedThunder/agent-middleware-api/issues/545) | P3 | local_fixed | [Review](security-actions-integrations.md) |
| IP-011 | [#546 — Remove live security-testing and CI-gate claims from simulated scan route metadata](https://github.com/PetrefiedThunder/agent-middleware-api/issues/546) | P3 | local_fixed | [Review](security-actions-integrations.md) |
| IP-012 | [#581 — Delete every memory before removing the AWI session index](https://github.com/PetrefiedThunder/agent-middleware-api/issues/581) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| IP-013 | [#582 — Reject or safely handle empty AWI RAG queries](https://github.com/PetrefiedThunder/agent-middleware-api/issues/582) | P3 | local_fixed | [Review](security-actions-integrations.md) |
| IP-014 | [#583 — Do not report malformed or failed Python runner output as success](https://github.com/PetrefiedThunder/agent-middleware-api/issues/583) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| QA-ACTION-TRANSPORT-001 | [#529 — Standalone MCP generator emits Python that cannot start](https://github.com/PetrefiedThunder/agent-middleware-api/issues/529) | P3 | retired_with_explicit_refusal | [Review](clients-and-docs.md) |
| QA-ACTION-TRANSPORT-002 | [#524 — A valid no-argument local tool breaks standard MCP discovery](https://github.com/PetrefiedThunder/agent-middleware-api/issues/524) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| QA-CLIENT-001 | [#509 — SDK local permit verification rejects valid action-bound permits](https://github.com/PetrefiedThunder/agent-middleware-api/issues/509) | P2 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-002 | [#510 — Framework wrapper retry changes permit body after a lost creation response](https://github.com/PetrefiedThunder/agent-middleware-api/issues/510) | P2 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-003 | [#511 — Legacy SDK standalone MCP command and generated scripts are unusable](https://github.com/PetrefiedThunder/agent-middleware-api/issues/511) | P2 | retired_with_explicit_refusal | [Review](clients-and-docs.md) |
| QA-CLIENT-004 | [#530 — Legacy framework client omits current discovery authentication and AWI governance inputs](https://github.com/PetrefiedThunder/agent-middleware-api/issues/530) | P2 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-005 | [#531 — AWI discovery still denies permit enforcement on governed HTTP routes](https://github.com/PetrefiedThunder/agent-middleware-api/issues/531) | P3 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-006 | [#532 — Public site and bootstrap manifests claim private source repository is public](https://github.com/PetrefiedThunder/agent-middleware-api/issues/532) | P3 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-007 | [#538 — Agent self-credentialing guide writes unevaluated shell substitution into dotenv signing key](https://github.com/PetrefiedThunder/agent-middleware-api/issues/538) | P3 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-008 | [#560 — Key Rotation can consume multiple lives in one update despite granting invulnerability](https://github.com/PetrefiedThunder/agent-middleware-api/issues/560) | P3 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-009 | [#561 — Happy Path draws the player twelve pixels above its collision position](https://github.com/PetrefiedThunder/agent-middleware-api/issues/561) | P3 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-010 | [#562 — Tap Forge discards passive quota earnings on every animation frame](https://github.com/PetrefiedThunder/agent-middleware-api/issues/562) | P3 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-011 | [#563 — Security reviewer claim omits local invocations that cannot produce a receipt](https://github.com/PetrefiedThunder/agent-middleware-api/issues/563) | P3 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-012 | [#564 — Golden-path dogfood substitution leaves incompatible message arguments](https://github.com/PetrefiedThunder/agent-middleware-api/issues/564) | P2 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-013 | [#565 — Partner offline-verification install command omits required verify extra](https://github.com/PetrefiedThunder/agent-middleware-api/issues/565) | P2 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-014 | [#566 — CI bootstrap recipe combines credentials from three separate provisioning runs](https://github.com/PetrefiedThunder/agent-middleware-api/issues/566) | P2 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-015 | [#567 — Legacy database guidance recommends stamping current head without schema equivalence](https://github.com/PetrefiedThunder/agent-middleware-api/issues/567) | P2 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-016 | [#568 — Lockdown and key-rotation runbooks retain deployment paths contradicted by current immutable release SOP](https://github.com/PetrefiedThunder/agent-middleware-api/issues/568) | P3 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-017 | [#569 — Local demo Compose recipe omits DATABASE_URL required for its key and trust workflow](https://github.com/PetrefiedThunder/agent-middleware-api/issues/569) | P2 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-018 | [#570 — Historical external diagnostic harness reports zero findings for unauthenticated200 responses](https://github.com/PetrefiedThunder/agent-middleware-api/issues/570) | P3 | retired_with_explicit_refusal | [Review](clients-and-docs.md) |
| QA-CLIENT-019 | [#571 — Partner checklist uses GET for the POST-only receipt verification operation](https://github.com/PetrefiedThunder/agent-middleware-api/issues/571) | P3 | local_fixed | [Review](clients-and-docs.md) |
| QA-CLIENT-020 | [#572 — Failure-lab suite quick commands select the older lab instead of the advertised fast tier](https://github.com/PetrefiedThunder/agent-middleware-api/issues/572) | P3 | local_fixed | [Review](clients-and-docs.md) |
| SEC-001 | [#503 — Refresh widens an attenuated JWT scope set](https://github.com/PetrefiedThunder/agent-middleware-api/issues/503) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| SEC-002 | [#504 — Scoped access tokens can mint unrestricted wallet API keys](https://github.com/PetrefiedThunder/agent-middleware-api/issues/504) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| SEC-003 | [#505 — Derived JWT authentication bypasses the originating key use budget](https://github.com/PetrefiedThunder/agent-middleware-api/issues/505) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| SEC-004 | [#506 — Bearer callers choose fresh rate buckets with ignored API-key headers](https://github.com/PetrefiedThunder/agent-middleware-api/issues/506) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| SEC-005 | [#507 — Readiness probe returns healthy HTTP status during dependency failure](https://github.com/PetrefiedThunder/agent-middleware-api/issues/507) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| SEC-006 | [#508 — Late IGA compensation erases a different invocation velocity reservation](https://github.com/PetrefiedThunder/agent-middleware-api/issues/508) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| SEC-007 | [#525 — Concurrent valid append makes audit verification falsely report truncation](https://github.com/PetrefiedThunder/agent-middleware-api/issues/525) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| SEC-008 | [#526 — AWI performs effects before budget/debit and repeats them after reservation contention](https://github.com/PetrefiedThunder/agent-middleware-api/issues/526) | P2 | local_fixed | [Review](security-actions-integrations.md) |
| SEC-009 | [#584 — SQLite permit issuance signs values that change during persistence](https://github.com/PetrefiedThunder/agent-middleware-api/issues/584) | P2 | local_fixed | [Review](accounting.md) |

## Per-finding provenance

Original negative controls, passing regressions and review artifacts below are preserved local evidence from the earlier audit. A listed review covers only its recorded subset and commit. Fresh results appear in the linked domain handoffs; historical counts must not be summed as independent coverage.

### ACCT-001 — Accepted sub-credit tool prices produce unverifiable quotes and receipts

Issue: [#502](https://github.com/PetrefiedThunder/agent-middleware-api/issues/502) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Reject unsupported precision before signing/pricing and preserve exact stored credit amounts.

**Exact local fix/follow-up commits:** `d978982c615d84a5c597c350c47f3d823eadeef0`, `0620f6f45ea5c272f6c5819d4d86527c16e1ee0d`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [ACCT-001.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/ACCT-001.md)
- [test_precision_review.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/test_precision_review.py)
- [precision-red-v2.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/precision-red-v2.log)

**Passing historical regressions:**

- [accounting-fast-suite-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/accounting-fast-suite-final.log)

**Prior independent review:**

- [independent-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-fix-review.md)
- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### ACCT-002 — New client request keys can reuse one human approval to mint additional permits

Issue: [#500](https://github.com/PetrefiedThunder/agent-middleware-api/issues/500) · Severity: P1 · Local state: **local_fixed**.

**Correction:** Bind the provider approval identity to the logical local request; a new client key cannot reuse one approval to mint another permit.

**Exact local fix/follow-up commits:** `ee54ae16e635e6a4c66dc73f57db1a5539514619`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [ACCT-002.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/ACCT-002.md)
- [test_permit_request_review.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/test_permit_request_review.py)
- [permit-request-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/permit-request-red.log)

**Passing historical regressions:**

- [accounting-fast-suite-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/accounting-fast-suite-final.log)

**Prior independent review:**

- [independent-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-fix-review.md)
- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### ACCT-003 — Permit-request approval can cross its local deadline while polling and still mint

Issue: [#501](https://github.com/PetrefiedThunder/agent-middleware-api/issues/501) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Recheck approval expiry through polling and transaction contention; roll back mint claims crossing the deadline.

**Exact local fix/follow-up commits:** `ee54ae16e635e6a4c66dc73f57db1a5539514619`, `0e2d2f1c92909fb3db9eee6e8f275d960ed6936d`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [ACCT-003.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/ACCT-003.md)
- [test_permit_request_review.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/test_permit_request_review.py)
- [permit-request-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/permit-request-red.log)

**Passing historical regressions:**

- [accounting-fast-suite-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/accounting-fast-suite-final.log)

**Prior independent review:**

- [independent-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-fix-review.md)
- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### ACCT-004 — Startup schema verification misses every required single-action column

Issue: [#520](https://github.com/PetrefiedThunder/agent-middleware-api/issues/520) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Startup validates all required action-binding columns rather than only table presence.

**Exact local fix/follow-up commits:** `ea73b3c76491aa6e64dc3aaa9e29f0fe770fb792`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [ACCT-004.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/ACCT-004.md)
- [test_schema_guard_review.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/test_schema_guard_review.py)
- [schema-guard-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/schema-guard-red.log)

**Passing historical regressions:**

- [accounting-fast-suite-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/accounting-fast-suite-final.log)

**Prior independent review:**

- [independent-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-fix-review.md)
- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### ACCT-005 — Concurrent Stripe top-ups lose settled credits on SQLite

Issue: [#521](https://github.com/PetrefiedThunder/agent-middleware-api/issues/521) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Apply settled Stripe top-up credits atomically so concurrent SQLite updates do not lose credits.

**Exact local fix/follow-up commits:** `1cd4d0c31ed2873f370b65f20d6a52fc3af30e6d`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [ACCT-005.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/ACCT-005.md)
- [test_stripe_race_review.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/test_stripe_race_review.py)
- [stripe-races-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/stripe-races-red.log)

**Passing historical regressions:**

- [accounting-fast-suite-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/accounting-fast-suite-final.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### ACCT-006 — Concurrent Stripe cumulative refunds double-claw back on SQLite

Issue: [#522](https://github.com/PetrefiedThunder/agent-middleware-api/issues/522) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Serialize cumulative Stripe refund deltas and apply each newly observed amount once.

**Exact local fix/follow-up commits:** `1cd4d0c31ed2873f370b65f20d6a52fc3af30e6d`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [ACCT-006.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/ACCT-006.md)
- [test_stripe_race_review.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/test_stripe_race_review.py)
- [stripe-races-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/stripe-races-red.log)

**Passing historical regressions:**

- [accounting-fast-suite-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/accounting-fast-suite-final.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### ACCT-007 — PostgreSQL migration 038 cannot recover after concurrent-index interruption

Issue: [#523](https://github.com/PetrefiedThunder/agent-middleware-api/issues/523) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Recover interrupted PostgreSQL concurrent-index construction safely on migration 038 retry.

**Exact local fix/follow-up commits:** `6387945279ac7254c672ff7010975f0de57f5cbd`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [ACCT-007.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/ACCT-007.md)
- [prove_migration038_retry.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/prove_migration038_retry.py)
- [migration038-retry-red-escalated.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/migration038-retry-red-escalated.log)

**Passing historical regressions:**

- [accounting-fast-suite-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/accounting-fast-suite-final.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### ACCT-008 — Zero-price tools receive signed quotes but cannot execute

Issue: [#539](https://github.com/PetrefiedThunder/agent-middleware-api/issues/539) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Refuse unsupported zero-price governed quotes before issuing an unusable signed quote.

**Exact local fix/follow-up commits:** `ef64d0291cbf50c8f00fbf5d2e4be22d2c781916`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [ACCT-008.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/ACCT-008.md)
- [test_zero_price_review.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/test_zero_price_review.py)
- [zero-price-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/zero-price-red.log)

**Passing historical regressions:**

- [accounting-fast-suite-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/accounting-fast-suite-final.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### ACCT-009 — Terminal billing-policy denial leaves its idempotency key in progress

Issue: [#541](https://github.com/PetrefiedThunder/agent-middleware-api/issues/541) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Complete/release keyed terminal billing denial correctly instead of leaving the key in progress.

**Exact local fix/follow-up commits:** `edfd71a8088cc1aabaa42ba88a1fba94e46a3eec`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [ACCT-009.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/ACCT-009.md)
- [test_billing_boundary_review.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/test_billing_boundary_review.py)
- [billing-boundaries-red-v2.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/billing-boundaries-red-v2.log)

**Passing historical regressions:**

- [accounting-fast-suite-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/accounting-fast-suite-final.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### ACCT-010 — Keyed billing charge for unknown wallet returns500 instead of404

Issue: [#542](https://github.com/PetrefiedThunder/agent-middleware-api/issues/542) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Preserve the unknown-wallet 404 at the keyed billing boundary instead of converting it to 500.

**Exact local fix/follow-up commits:** `edfd71a8088cc1aabaa42ba88a1fba94e46a3eec`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [ACCT-010.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/ACCT-010.md)
- [test_billing_boundary_review.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/test_billing_boundary_review.py)
- [billing-boundaries-red-v2.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/billing-boundaries-red-v2.log)

**Passing historical regressions:**

- [accounting-fast-suite-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/accounting-fast-suite-final.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### ACCT-011 — Ledger period exact totals are calculated from binary floats

Issue: [#543](https://github.com/PetrefiedThunder/agent-middleware-api/issues/543) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Calculate exact ledger period totals with decimal arithmetic rather than binary floats.

**Exact local fix/follow-up commits:** `edfd71a8088cc1aabaa42ba88a1fba94e46a3eec`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [ACCT-011.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/ACCT-011.md)
- [test_billing_boundary_review.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/test_billing_boundary_review.py)
- [billing-boundaries-red-v2.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/billing-boundaries-red-v2.log)

**Passing historical regressions:**

- [accounting-fast-suite-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/accounting-fast-suite-final.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### ACCT-012 — Wallet-scoped credentials can read global profitability and other tenants' ledger details

Issue: [#557](https://github.com/PetrefiedThunder/agent-middleware-api/issues/557) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Require administrator authority for global profitability and cross-tenant ledger detail.

**Exact local fix/follow-up commits:** `d446f0b554307040654526f318699873d1b2e305`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [ACCT-012.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/ACCT-012.md)
- [test_arbitrage_review.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/test_arbitrage_review.py)
- [arbitrage-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/arbitrage-red.log)

**Passing historical regressions:**

- [resume-arbitrage-green-v2.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/resume-arbitrage-green-v2.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### ACCT-013 — Profitability report labels all-history totals as a one-day period

Issue: [#558](https://github.com/PetrefiedThunder/agent-middleware-api/issues/558) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Restrict profitability rows and totals to the stated report interval.

**Exact local fix/follow-up commits:** `d446f0b554307040654526f318699873d1b2e305`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [ACCT-013.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/ACCT-013.md)
- [test_arbitrage_review.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/test_arbitrage_review.py)
- [arbitrage-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/arbitrage-red.log)

**Passing historical regressions:**

- [resume-arbitrage-green-v2.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/resume-arbitrage-green-v2.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### ACCT-014 — Receiptless x402 crash recovery consumes permit budget twice

Issue: [#559](https://github.com/PetrefiedThunder/agent-middleware-api/issues/559) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Retain ambiguous receiptless x402 owners and reservations for review; recovery cannot consume authority twice.

**Exact local fix/follow-up commits:** `2cc557d69172df14d369167899fb81e50adcdda7`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [ACCT-014.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/ACCT-014.md)
- [test_x402_crash_review.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/test_x402_crash_review.py)
- [x402-crash-red-v4.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/x402-crash-red-v4.log)

**Passing historical regressions:**

- [resume-x402-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/resume-x402-green.log)

**Prior independent review:**

- [final-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/final-review.md)
- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### ACCT-015 — Failed x402 compensation releases the accepted request owner

Issue: [#585](https://github.com/PetrefiedThunder/agent-middleware-api/issues/585) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Retain x402 request ownership when settlement compensation is uncertain or incomplete; do not release authority for another retry.

**Exact local fix/follow-up commits:** `d9275789138a1f22e3adb9c62a1e6868f3dce650`, `9d8c962301a35705c184534979ec7f8c06da9af0`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [findings.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/findings.json)
- [x402-compensation-red-targeted.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/x402-compensation-red-targeted.log)

**Passing historical regressions:**

- [resume-compensation-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/resume-compensation-stable.log)
- [x402-compensation-green-34040b3-targeted.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/x402-compensation-green-34040b3-targeted.log)
- [x402-independent-controls-34040b3-targeted.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/x402-independent-controls-34040b3-targeted.log)

**Prior independent review:**

- [final-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/final-review.md)
- [x402-compensation-green-34040b3-targeted.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/x402-compensation-green-34040b3-targeted.json)

### AE-001 — Release exact issuance ownership after a proven pre-persistence rejection

Issue: [#512](https://github.com/PetrefiedThunder/agent-middleware-api/issues/512) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Release only the exact issuance owner after an explicit proven pre-signing/pre-persistence rejection; retain ambiguous post-mint ownership.

**Exact local fix/follow-up commits:** `0e4b1411d494722fb4f592d13eb3764503c7fbce`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_issuance_retry.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/probes/test_issuance_retry.py)
- [run_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/run_probe.py)
- [issuance-retry-red-run.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/issuance-retry-red-run.log)
- [issuance-retry-red-run-result.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/issuance-retry-red-run-result.json)

**Passing historical regressions:**

- [ae001-focused-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/ae001-focused-green.log)

**Prior independent review:**

- [final-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/final-review.md)
- [independent-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-fix-review.md)

### AE-002 — Reuse the preparation transaction for action signature verification

Issue: [#519](https://github.com/PetrefiedThunder/agent-middleware-api/issues/519) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Reuse the action preparation transaction for signature verification rather than acquiring a second pooled connection.

**Exact local fix/follow-up commits:** `59d24e24df94bd0a59ea641c8164e59308343e3e`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_action_pool.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/probes/test_action_pool.py)
- [action-pool-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/action-pool-red.log)
- [action-pool-red-result.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/action-pool-red-result.json)

**Passing historical regressions:**

- [ae002-focused.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/ae002-focused.log)
- [ae002-postgres-test.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/ae002-postgres-test.log)

**Prior independent review:**

- [independent-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-fix-review.md)

### AE-003 — Retry local call-counter contention instead of caching false budget denial

Issue: [#540](https://github.com/PetrefiedThunder/agent-middleware-api/issues/540) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Distinguish optimistic local permit counter contention from genuine authority/budget denial and retry before debit/effect.

**Exact local fix/follow-up commits:** `61cb0ca630993f11bb0818a87bad07a8020ab21c`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_local_call_counter_race.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/probes/test_local_call_counter_race.py)
- [local-counter-race.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/local-counter-race.log)
- [local-counter-race-result.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/local-counter-race-result.json)
- [local-counter-http-race.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/local-counter-http-race.log)
- [local-counter-http-race-result.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/local-counter-http-race-result.json)

**Passing historical regressions:**

- [ae003-focused-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/ae003-focused-green.log)

**Prior independent review:**

- [independent-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-fix-review.md)

### INFRA-001 — Failure Lab negative-control CI promotes judge crashes to success

Issue: [#533](https://github.com/PetrefiedThunder/agent-middleware-api/issues/533) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Require valid completed observed-duplicate evidence for the CI negative control; a judge crash cannot count as success.

**Exact local fix/follow-up commits:** `043705c822b22afa685fdde713e48d9d09a94816`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-001.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-001.md)
- [test_proof_boundaries.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_proof_boundaries.py)
- [proof-boundaries-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/proof-boundaries-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [independent-infrastructure-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-infrastructure-fix-review.md)

### INFRA-002 — Downloaded Failure Lab ZIP omits keys needed by its offline verifier

Issue: [#534](https://github.com/PetrefiedThunder/agent-middleware-api/issues/534) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Include receipt public keys in integrity-covered offline archives so extracted bundles can be signature-checked.

**Exact local fix/follow-up commits:** `dd25465b2c19342c2ba983b576cdb9e1303ce181`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-002.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-002.md)
- [test_proof_boundaries.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_proof_boundaries.py)
- [proof-boundaries-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/proof-boundaries-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [independent-infrastructure-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-infrastructure-fix-review.md)

### INFRA-003 — Live release preflight certifies missing posture fields as safe

Issue: [#535](https://github.com/PetrefiedThunder/agent-middleware-api/issues/535) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Require explicit safe public posture fields; missing/malformed nested evidence fails live preflight.

**Exact local fix/follow-up commits:** `24b955dfb20f343f3d67c6de056aae6fc3a740d3`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-003.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-003.md)
- [test_preflight_boundaries.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_preflight_boundaries.py)
- [preflight-boundaries-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/preflight-boundaries-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [independent-infrastructure-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-infrastructure-fix-review.md)

### INFRA-004 — Database-only preflight silently drops explicit release identity expectations

Issue: [#536](https://github.com/PetrefiedThunder/agent-middleware-api/issues/536) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Refuse DB-only selections that would silently discard requested live release-identity expectations.

**Exact local fix/follow-up commits:** `93b3ee722f7c6025accf7ab76bd9e8b98d07ad9f`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-004.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-004.md)
- [test_preflight_boundaries.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_preflight_boundaries.py)
- [preflight-boundaries-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/preflight-boundaries-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [independent-infrastructure-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-infrastructure-fix-review.md)

### INFRA-005 — Development Compose hot reload command is ignored by the entrypoint

Issue: [#537](https://github.com/PetrefiedThunder/agent-middleware-api/issues/537) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Honor explicit container command overrides after the migration gate.

**Exact local fix/follow-up commits:** `56e6cecf1ef6c5c0ef58924b16dfcf31dcf9258a`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-005.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-005.md)
- [test_compose_entrypoint.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_compose_entrypoint.py)
- [compose-entrypoint-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/compose-entrypoint-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [independent-infrastructure-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-infrastructure-fix-review.md)

### INFRA-006 — Make crash-proof wrapper migrates before isolation checks

Issue: [#547](https://github.com/PetrefiedThunder/agent-middleware-api/issues/547) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Run crash-proof isolation guards before any database operation; Make no longer migrates first.

**Exact local fix/follow-up commits:** `aa96e51596490bb0f960cd94bcc88fef28488d8c`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-006.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-006.md)
- [test_operator_boundaries.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_operator_boundaries.py)
- [operator-boundaries-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/operator-boundaries-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [independent-infrastructure-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-infrastructure-fix-review.md)

### INFRA-007 — Rotation verification transmits bootstrap keys over remote HTTP

Issue: [#548](https://github.com/PetrefiedThunder/agent-middleware-api/issues/548) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Validate rotation-verifier origins before sending keys and refuse redirects/remote plaintext HTTP.

**Exact local fix/follow-up commits:** `037e590086c2b1807979dba759a89991f786d20b`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-007.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-007.md)
- [test_operator_boundaries.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_operator_boundaries.py)
- [operator-boundaries-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/operator-boundaries-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [independent-infrastructure-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-infrastructure-fix-review.md)

### INFRA-008 — Partner bootstrap ignores successful --key-only output mode

Issue: [#549](https://github.com/PetrefiedThunder/agent-middleware-api/issues/549) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Emit only the minted key plus newline for successful --key-only bootstrap output.

**Exact local fix/follow-up commits:** `2efbc36cd12b57cd17a2035c60af37897e02b023`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-008.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-008.md)
- [test_bootstrap_load_boundaries.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_bootstrap_load_boundaries.py)
- [bootstrap-load-boundaries-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/bootstrap-load-boundaries-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [independent-infrastructure-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-infrastructure-fix-review.md)

### INFRA-009 — Load battery stops a container it did not create

Issue: [#550](https://github.com/PetrefiedThunder/agent-middleware-api/issues/550) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Stop only containers created by the load script itself, including failed-readiness cleanup.

**Exact local fix/follow-up commits:** `902893fdf20d08797b9876c549e38aa404bb1839`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-009.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-009.md)
- [test_bootstrap_load_boundaries.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_bootstrap_load_boundaries.py)
- [bootstrap-load-boundaries-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/bootstrap-load-boundaries-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [independent-infrastructure-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-infrastructure-fix-review.md)

### INFRA-010 — Load battery labels an all-error run PASS and exits zero

Issue: [#551](https://github.com/PetrefiedThunder/agent-middleware-api/issues/551) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Require complete successful workload and no error/denial/accounting anomaly for load PASS and zero exit.

**Exact local fix/follow-up commits:** `ad6330cb1d3869bb12a073a9019b37e2b7c527c4`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-010.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-010.md)
- [test_bootstrap_load_boundaries.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_bootstrap_load_boundaries.py)
- [bootstrap-load-boundaries-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/bootstrap-load-boundaries-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [independent-infrastructure-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-infrastructure-fix-review.md)

### INFRA-011 — Loaded claim manifest promotes a PASS summary over FAIL/ERROR rows

Issue: [#552](https://github.com/PetrefiedThunder/agent-middleware-api/issues/552) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Preserve negative FAIL/ERROR observations when loading manifests rather than trusting a contradictory PASS summary.

**Exact local fix/follow-up commits:** `da8ffd3a684c5ec320cca917ace355267efb2f08`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-011.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-011.md)
- [test_claim_manifest_boundary.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_claim_manifest_boundary.py)
- [claims-boundary-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/claims-boundary-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [independent-infrastructure-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-infrastructure-fix-review.md)

### INFRA-012 — Repo guardian caches failed full lint as a successful sweep

Issue: [#573](https://github.com/PetrefiedThunder/agent-middleware-api/issues/573) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Cache guardian full sweeps only when both tests and lint succeed; invalidate older cached success after a forced failure.

**Exact local fix/follow-up commits:** `4aa33e9b461dc5fa90c065be6c0bf5617e4111cd`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-012.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-012.md)
- [test_guardian_boundary.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_guardian_boundary.py)
- [guardian-boundary-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/guardian-boundary-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [coordinator-rag-infra-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/coordinator-rag-infra-review.md)

### INFRA-013 — Live stress checks accept HTTP failures and absent receipt IDs

Issue: [#574](https://github.com/PetrefiedThunder/agent-middleware-api/issues/574) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Require successful HTTP/JSON-RPC responses and nonblank receipt IDs from every stress result; use identical same-key payloads and checks that survive -O.

**Exact local fix/follow-up commits:** `2009fdf1c2b7369e57f3df0284d878dddb8bf2db`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-013.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-013.md)
- [test_stress_response_boundaries.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_stress_response_boundaries.py)
- [stress-redirect-boundaries-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/stress-redirect-boundaries-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [coordinator-rag-infra-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/coordinator-rag-infra-review.md)

### INFRA-014 — Adversarial battery forwards API keys across redirect origins

Issue: [#575](https://github.com/PetrefiedThunder/agent-middleware-api/issues/575) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Refuse redirects for authenticated adversarial requests so credentials and mutations stay at the chosen destination.

**Exact local fix/follow-up commits:** `03372935385202c277d31956c618eb7d753e719d`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-014.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-014.md)
- [test_adversarial_redirect_boundary.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_adversarial_redirect_boundary.py)
- [stress-redirect-boundaries-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/stress-redirect-boundaries-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [coordinator-rag-infra-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/coordinator-rag-infra-review.md)

### INFRA-015 — Comparison report interprets configuration errors as successful measurements

Issue: [#576](https://github.com/PetrefiedThunder/agent-middleware-api/issues/576) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Exclude ERROR configuration counters from prevention/latency arithmetic while rendering errors and retaining valid partial baseline comparisons.

**Exact local fix/follow-up commits:** `98cd3eed11908a44cce77b3c6c4c481a23e20811`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-015.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-015.md)
- [test_report_error_boundary.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_report_error_boundary.py)
- [report-error-boundary-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/report-error-boundary-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [coordinator-rag-infra-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/coordinator-rag-infra-review.md)

### INFRA-016 — Diagnostic request size limit applies only after full buffering

Issue: [#577](https://github.com/PetrefiedThunder/agent-middleware-api/issues/577) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Enforce the diagnostic body limit while consuming ASGI chunks, including absent/false Content-Length.

**Exact local fix/follow-up commits:** `322be7f522dca93c4cddba00b6427abf36ba2765`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-016.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-016.md)
- [test_diagnostic_body_boundary.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/test_diagnostic_body_boundary.py)
- [diagnostic-body-boundary-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/diagnostic-body-boundary-red.log)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [coordinator-rag-infra-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/coordinator-rag-infra-review.md)

### INFRA-017 — Agent-facing documentation advertises a nonexistent rate-limit burst

Issue: [#578](https://github.com/PetrefiedThunder/agent-middleware-api/issues/578) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Document the configurable default 120/min, zero extra burst and fixed Redis versus rolling local windows.

**Exact local fix/follow-up commits:** `ad108fb0b88fc9e2627ce1089224741d209f6461`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-017.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-017.md)
- [probe_documentation_contracts.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/probe_documentation_contracts.py)
- [documentation-contract-evidence.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/documentation-contract-evidence.json)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [coordinator-rag-infra-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/coordinator-rag-infra-review.md)

### INFRA-018 — Agent endpoint table labels production discovery authentication optional

Issue: [#579](https://github.com/PetrefiedThunder/agent-middleware-api/issues/579) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Document production-like discovery authentication and anonymous local-compatible quickstart accurately.

**Exact local fix/follow-up commits:** `ad108fb0b88fc9e2627ce1089224741d209f6461`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-018.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-018.md)
- [probe_documentation_contracts.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/probe_documentation_contracts.py)
- [documentation-contract-evidence.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/documentation-contract-evidence.json)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [coordinator-rag-infra-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/coordinator-rag-infra-review.md)

### INFRA-019 — Troubleshooting treats an uncertain-delivery receipt as proof of acceptance

Issue: [#580](https://github.com/PetrefiedThunder/agent-middleware-api/issues/580) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Explain that delivery_uncertain proves neither acceptance nor execution and requires authoritative downstream reconciliation.

**Exact local fix/follow-up commits:** `ad108fb0b88fc9e2627ce1089224741d209f6461`.

**Current domain review:** [handoff](infrastructure.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [INFRA-019.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/INFRA-019.md)
- [probe_documentation_contracts.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/probe_documentation_contracts.py)
- [documentation-contract-evidence.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/documentation-contract-evidence.json)

**Passing historical regressions:**

- [infra-third-slice-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/infrastructure_proofs/infra-third-slice-stable.log)

**Prior independent review:**

- [coordinator-rag-infra-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/coordinator-rag-infra-review.md)

### IP-001 — Rehydrate durable AI decisions and heals before exposing them through typed routes

Issue: [#513](https://github.com/PetrefiedThunder/agent-middleware-api/issues/513) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Rehydrate durable decision/heal records and timestamps and initialize read routes after restart.

**Exact local fix/follow-up commits:** `88828e8f4b963305a0233ab5f5aea237f5e6070c`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_ai_durable_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/test_ai_durable_probe.py)
- [ai-probe-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/ai-probe-red.log)

**Passing historical regressions:**

- [ai-fix-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/ai-fix-green.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### IP-002 — Use the configured API root once when building OpenAI chat URLs

Issue: [#514](https://github.com/PetrefiedThunder/agent-middleware-api/issues/514) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Treat the configured OpenAI URL as the API root and append the chat path only once.

**Exact local fix/follow-up commits:** `f20abec84ee618b55af15506a486144f2d017a2d`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_ai_durable_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/test_ai_durable_probe.py)
- [ai-probe-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/ai-probe-red.log)

**Passing historical regressions:**

- [llm-fix-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/llm-fix-green.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### IP-003 — Propagate structured DOM execution failure to AWI top-level status before accounting

Issue: [#515](https://github.com/PetrefiedThunder/agent-middleware-api/issues/515) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Propagate structured browser failure as uncertain effect status and truthful governed accounting; preserve precharge/owner semantics from SEC-008.

**Exact local fix/follow-up commits:** `19fe8c2ff2d0ff2fa498556fb348ea9f4ac8cdfe`, `cb8d2f816badf7f504c6cb51153f91cf94ab15ed`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_awi_boundary_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/test_awi_boundary_probe.py)
- [awi-boundary-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/awi-boundary-red.log)

**Passing historical regressions:**

- [awi-stable-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/awi-stable-green.log)
- [final-sqlite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/awi_ordering/final-sqlite.log)
- [pg-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/awi_ordering/pg-final.log)

**Prior independent review:**

- [awi-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/awi-review.md)

### IP-004 — Prevent browser dispatch when AWI callers explicitly request a dry run

Issue: [#516](https://github.com/PetrefiedThunder/agent-middleware-api/issues/516) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Reject unsupported dry run without browser commands or step mutation; final AWI precharge is refunded only on trusted not-dispatched evidence.

**Exact local fix/follow-up commits:** `19fe8c2ff2d0ff2fa498556fb348ea9f4ac8cdfe`, `cb8d2f816badf7f504c6cb51153f91cf94ab15ed`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_awi_boundary_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/test_awi_boundary_probe.py)
- [awi-boundary-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/awi-boundary-red.log)

**Passing historical regressions:**

- [awi-stable-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/awi-stable-green.log)
- [final-sqlite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/awi_ordering/final-sqlite.log)
- [pg-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/awi_ordering/pg-final.log)

**Prior independent review:**

- [awi-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/awi-review.md)

### IP-005 — Bind all effect-bearing AWI arguments into the idempotency identity

Issue: [#517](https://github.com/PetrefiedThunder/agent-middleware-api/issues/517) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Bind all normalized effect-bearing arguments plus wallet/tool/permit to AWI request identity; changed same-key semantics conflict.

**Exact local fix/follow-up commits:** `19fe8c2ff2d0ff2fa498556fb348ea9f4ac8cdfe`, `cb8d2f816badf7f504c6cb51153f91cf94ab15ed`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_awi_governance_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/test_awi_governance_probe.py)
- [awi-governance-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/awi-governance-red.log)

**Passing historical regressions:**

- [awi-stable-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/awi-stable-green.log)
- [final-sqlite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/awi_ordering/final-sqlite.log)
- [pg-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/awi_ordering/pg-final.log)

**Prior independent review:**

- [awi-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/awi-review.md)

### IP-006 — Enforce signed AWI argument prohibitions and atomic per-tool call limits before execution

Issue: [#518](https://github.com/PetrefiedThunder/agent-middleware-api/issues/518) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Enforce signed forbidden-field constraints and refuse unsupported per-tool call-limit authority before callbacks.

**Exact local fix/follow-up commits:** `19fe8c2ff2d0ff2fa498556fb348ea9f4ac8cdfe`, `cb8d2f816badf7f504c6cb51153f91cf94ab15ed`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_awi_governance_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/test_awi_governance_probe.py)
- [awi-governance-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/awi-governance-red.log)

**Passing historical regressions:**

- [awi-stable-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/awi-stable-green.log)
- [final-sqlite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/awi_ordering/final-sqlite.log)
- [pg-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/awi_ordering/pg-final.log)

**Prior independent review:**

- [awi-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/awi-review.md)

### IP-007 — Honor write-only and explicit-deny IoT topic ACLs

Issue: [#527](https://github.com/PetrefiedThunder/agent-middleware-api/issues/527) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Enforce READ/WRITE direction and precedence of every matching IoT DENY rule.

**Exact local fix/follow-up commits:** `9b26b35b17aaa1196892dd31604cc14f500e0508`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_iot_acl_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/test_iot_acl_probe.py)
- [iot-acl-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/iot-acl-red.log)

**Passing historical regressions:**

- [iot-fix-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/iot-fix-green.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### IP-008 — Persist completed content campaigns and their pipeline links

Issue: [#528](https://github.com/PetrefiedThunder/agent-middleware-api/issues/528) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Persist campaign pipeline links and terminal status, including failed render state, across restart.

**Exact local fix/follow-up commits:** `527f3b7fc2e69042fa642266f871a28786efa65f`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_factory_durable_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/test_factory_durable_probe.py)
- [factory-durable-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/factory-durable-red.log)
- [factory-durable-initial-fixture-error.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/factory-durable-initial-fixture-error.log)
- [factory-durable-async-fixture-error.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/factory-durable-async-fixture-error.log)

**Passing historical regressions:**

- [factory-fix-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/factory-fix-green.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### IP-009 — Generate valid Python literals in the behavioral sandbox wrapper

Issue: [#544](https://github.com/PetrefiedThunder/agent-middleware-api/issues/544) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Generate valid Python values in behavioral runner wrappers while preserving captured output.

**Exact local fix/follow-up commits:** `8d3ed08b053ca9c9a9e09972f39db3f0f9d358b7`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_behavioral_wrapper_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/test_behavioral_wrapper_probe.py)
- [sandbox-validation-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/sandbox-validation-red.log)

**Passing historical regressions:**

- [behavioral-runner-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/behavioral-runner-green.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### IP-010 — Validate RTaaS attack categories at the request boundary

Issue: [#545](https://github.com/PetrefiedThunder/agent-middleware-api/issues/545) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Validate RTaaS attack category values at the request boundary and return 422 before engine execution.

**Exact local fix/follow-up commits:** `f6e9f51947ca18587ec399493f5569f2d48b1db1`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_rtaas_validation_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/test_rtaas_validation_probe.py)
- [sandbox-validation-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/sandbox-validation-red.log)

**Passing historical regressions:**

- [rtaas-fix-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/rtaas-fix-green.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### IP-011 — Remove live security-testing and CI-gate claims from simulated scan route metadata

Issue: [#546](https://github.com/PetrefiedThunder/agent-middleware-api/issues/546) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Describe simulated security-scan behavior accurately in route metadata while keeping execution gates.

**Exact local fix/follow-up commits:** `636f8cf3d37fef6a007f3d7c4e4bdefbfdeccc87`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [findings.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/findings.json)

**Passing historical regressions:**

- [simulation-metadata-check.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/simulation-metadata-check.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### IP-012 — Delete every memory before removing the AWI session index

Issue: [#581](https://github.com/PetrefiedThunder/agent-middleware-api/issues/581) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Iterate a snapshot of session memory IDs so deletion removes every owned record without skipping mutated-index entries.

**Exact local fix/follow-up commits:** `c3385e9c87bd65d841015ce6602eb382383877bd`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_rag_lifecycle_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/test_rag_lifecycle_probe.py)
- [rag-parser-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/rag-parser-red.log)

**Passing historical regressions:**

- [rag-stable-c3385e9.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/rag-stable-c3385e9.log)

**Prior independent review:**

- [coordinator-rag-infra-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/coordinator-rag-infra-review.md)

### IP-013 — Reject or safely handle empty AWI RAG queries

Issue: [#582](https://github.com/PetrefiedThunder/agent-middleware-api/issues/582) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Reject blank RAG queries at the HTTP schema boundary and safely return no results for direct empty search without embedding/access mutations.

**Exact local fix/follow-up commits:** `c3385e9c87bd65d841015ce6602eb382383877bd`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_rag_lifecycle_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/test_rag_lifecycle_probe.py)
- [rag-parser-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/rag-parser-red.log)

**Passing historical regressions:**

- [rag-stable-c3385e9.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/rag-stable-c3385e9.log)

**Prior independent review:**

- [coordinator-rag-infra-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/coordinator-rag-infra-review.md)

### IP-014 — Do not report malformed or failed Python runner output as success

Issue: [#583](https://github.com/PetrefiedThunder/agent-middleware-api/issues/583) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Reject malformed, nonobject or failed Python runner output and process errors instead of reporting success.

**Exact local fix/follow-up commits:** `8d3ed08b053ca9c9a9e09972f39db3f0f9d358b7`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_behavioral_parser_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/test_behavioral_parser_probe.py)
- [rag-parser-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/rag-parser-red.log)

**Passing historical regressions:**

- [behavioral-runner-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/integrations_product/behavioral-runner-green.log)

**Prior independent review:**

- [audit-report.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/audit-report.md)

### QA-ACTION-TRANSPORT-001 — Standalone MCP generator emits Python that cannot start

Issue: [#529](https://github.com/PetrefiedThunder/agent-middleware-api/issues/529) · Severity: P3 · Local state: **retired_with_explicit_refusal**.

**Correction:** Retire the server standalone generator with explicit refusal before registry traversal or output writes; retain callable argument compatibility and active metadata generation.

**Exact local fix/follow-up commits:** `e4a046bc65c833c9765315355be0c4c1fd99e08b`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_transports_generator_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/test_transports_generator_probe.py)
- [transports-generator-probe.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/transports-generator-probe.log)
- [transports-generator-probe-result.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/transports-generator-probe-result.json)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### QA-ACTION-TRANSPORT-002 — A valid no-argument local tool breaks standard MCP discovery

Issue: [#524](https://github.com/PetrefiedThunder/agent-middleware-api/issues/524) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Normalize absent/null no-argument tool schemas to an object schema for standard MCP discovery, preserving explicit schemas.

**Exact local fix/follow-up commits:** `1f47952b302eaa89256af41ff4f358b2b7eda87f`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_transports_discovery_probe.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/test_transports_discovery_probe.py)
- [transports-discovery-probe.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/transports-discovery-probe.log)
- [transports-discovery-repair-control.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/transports-discovery-repair-control.log)
- [transports-discovery-probe-result.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/transports-discovery-probe-result.json)
- [transports-discovery-repair-control-result.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/transports-discovery-repair-control-result.json)

**Passing historical regressions:**

- [transport002-focused.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/transport002-focused.log)

**Prior independent review:**

- [independent-fix-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-fix-review.md)

### QA-CLIENT-001 — SDK local permit verification rejects valid action-bound permits

Issue: [#509](https://github.com/PetrefiedThunder/agent-middleware-api/issues/509) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Include all six signed action-binding fields in SDK canonical permit verification; preserve legacy envelope bytes.

**Exact local fix/follow-up commits:** `02622db97980975d26377235c1ce4d606a0c0774`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [run_checks.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/run_checks.py)
- [test_sdk_action_signature.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_sdk_action_signature.py)
- [sdk-action-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/sdk-action-red.log)
- [sdk-action-red-result.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/sdk-action-red-result.json)

**Passing historical regressions:**

- [action-fix-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/action-fix-stable.log)

**Prior independent review:**

- [independent-security-client-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md)

### QA-CLIENT-002 — Framework wrapper retry changes permit body after a lost creation response

Issue: [#510](https://github.com/PetrefiedThunder/agent-middleware-api/issues/510) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Retain the original permit issuance body before the first await in framework wrappers, including expiry, across ambiguous same-key retries.

**Exact local fix/follow-up commits:** `0bf6151eb94bbb35562e3d2f856fa16bc259b153`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [run_checks.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/run_checks.py)
- [test_wrapper_retry_contract.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_wrapper_retry_contract.py)
- [wrapper-retry-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/wrapper-retry-red.log)
- [wrapper-retry-red-result.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/wrapper-retry-red-result.json)

**Passing historical regressions:**

- [wrapper-fix-tests.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/wrapper-fix-tests.log)

**Prior independent review:**

- [independent-security-client-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md)

### QA-CLIENT-003 — Legacy SDK standalone MCP command and generated scripts are unusable

Issue: [#511](https://github.com/PetrefiedThunder/agent-middleware-api/issues/511) · Severity: P2 · Local state: **retired_with_explicit_refusal**.

**Correction:** Retire standalone SDK generation with explicit refusal before tool discovery or output writes; accept existing CLI/callable arguments and return controlled CLI exit 2.

**Exact local fix/follow-up commits:** `e4a046bc65c833c9765315355be0c4c1fd99e08b`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [run_checks.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/run_checks.py)
- [test_sdk_mcp_cli_contract.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_sdk_mcp_cli_contract.py)
- [sdk-mcp-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/sdk-mcp-red.log)
- [sdk-mcp-red-result.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/sdk-mcp-red-result.json)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### QA-CLIENT-004 — Legacy framework client omits current discovery authentication and AWI governance inputs

Issue: [#530](https://github.com/PetrefiedThunder/agent-middleware-api/issues/530) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Forward credentials for discovery and require caller-owned AWI permit/idempotency arguments.

**Exact local fix/follow-up commits:** `8e5e684d3d2fcae9a53330b45be4e467e80fba64`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [run_checks.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/run_checks.py)
- [test_framework_discovery_contract.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_framework_discovery_contract.py)
- [framework-discovery-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/framework-discovery-red.log)
- [framework-discovery-red-result.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/framework-discovery-red-result.json)

**Passing historical regressions:**

- [legacy-client-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/legacy-client-stable.log)

**Prior independent review:**

- [independent-security-client-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md)

### QA-CLIENT-005 — AWI discovery still denies permit enforcement on governed HTTP routes

Issue: [#531](https://github.com/PetrefiedThunder/agent-middleware-api/issues/531) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Advertise the six actual governed AWI HTTP routes and their permit requirements accurately.

**Exact local fix/follow-up commits:** `740098d11c30e04f3f6fb534ed627e8865f6e44a`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [run_checks.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/run_checks.py)
- [test_framework_discovery_contract.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_framework_discovery_contract.py)
- [framework-discovery-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/framework-discovery-red.log)
- [framework-discovery-red-result.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/framework-discovery-red-result.json)

**Passing historical regressions:**

- [discovery-claims-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/discovery-claims-stable.log)

**Prior independent review:**

- [independent-security-client-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md)

### QA-CLIENT-006 — Public site and bootstrap manifests claim private source repository is public

Issue: [#532](https://github.com/PetrefiedThunder/agent-middleware-api/issues/532) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Describe private source access separately from publicly downloadable proof artifacts.

**Exact local fix/follow-up commits:** `817ccd52e3efde57b8be3ebdbf171e674663ec30`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_pages_name_no_second_bran0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_customer_facing_outputs_d0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_branded_404_offers_a_way_0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_robots_states_an_explicit0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_concept_page_is_an_unlist0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_live_verifier_output_matc0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_site_build_blocks_missing0/email-only/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_typography_is_self_hosted0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_vercel_insights_loader_re0/default/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_vercel_insights_loader_re0/enabled/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_rendered_landing_is_human0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_every_indexable_page_is_c0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_pages_carry_no_inline_scr0/analytics-on/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_pages_carry_no_inline_scr0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_rendered_site_has_truthfu0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_every_page_loads_the_acce0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_cta_aria_labels_preserve_0/email-only/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_cta_aria_labels_preserve_0/with-booking/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_booking_identity_names_on2/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_navigation_is_identical_a1/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_stylesheet_cache_key_trac0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_navigation_is_identical_a0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_html_pages_point_crawlers0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_pilot_draft_encodes_conta0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_all_pages_share_the_curre0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_booking_identity_names_on4/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_booking_identity_names_on3/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_landing_hero_wave_is_prog0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_pointer_files_render_the_0/pointers/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_footer_reaches_the_same_p0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_comparison_page_names_alt0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_landing_console_renders_t0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_external_links_carry_noop0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_pages_publish_valid_json_0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_preloaded_fonts_exist_and0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_faq_structured_data_is_ge0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_vendored_font_license_is_0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_search_social_and_analyti0/email-only/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_search_social_and_analyti0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_public_surfaces_separate_0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_arcade_ships_as_progressi0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_llms_full_extends_the_sho0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_security_txt_is_routable_0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_booking_identity_names_on1/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_booking_identity_names_on0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-12/test_sitemap_publishes_lastmod0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_pages_name_no_second_bran0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_customer_facing_outputs_d0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_branded_404_offers_a_way_0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_robots_states_an_explicit0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_concept_page_is_an_unlist0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_live_verifier_output_matc0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_site_build_blocks_missing0/email-only/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_typography_is_self_hosted0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_vercel_insights_loader_re0/default/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_vercel_insights_loader_re0/enabled/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_rendered_landing_is_human0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_every_indexable_page_is_c0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_pages_carry_no_inline_scr0/analytics-on/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_pages_carry_no_inline_scr0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_rendered_site_has_truthfu0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_every_page_loads_the_acce0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_cta_aria_labels_preserve_0/email-only/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_cta_aria_labels_preserve_0/with-booking/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_booking_identity_names_on2/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_navigation_is_identical_a1/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_stylesheet_cache_key_trac0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_navigation_is_identical_a0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_html_pages_point_crawlers0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_pilot_draft_encodes_conta0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_all_pages_share_the_curre0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_booking_identity_names_on4/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_booking_identity_names_on3/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_landing_hero_wave_is_prog0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_pointer_files_render_the_0/pointers/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_footer_reaches_the_same_p0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_comparison_page_names_alt0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_landing_console_renders_t0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_external_links_carry_noop0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_pages_publish_valid_json_0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_preloaded_fonts_exist_and0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_faq_structured_data_is_ge0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_vendored_font_license_is_0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_search_social_and_analyti0/email-only/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_search_social_and_analyti0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_public_surfaces_separate_0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_arcade_ships_as_progressi0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_llms_full_extends_the_sho0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_security_txt_is_routable_0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_booking_identity_names_on1/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_booking_identity_names_on0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/pytest-of-sellers/pytest-13/test_sitemap_publishes_lastmod0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_pages_name_no_second_bran0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_customer_facing_outputs_d0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_branded_404_offers_a_way_0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_robots_states_an_explicit0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_concept_page_is_an_unlist0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_live_verifier_output_matc0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_site_build_blocks_missing0/email-only/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_typography_is_self_hosted0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_vercel_insights_loader_re0/default/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_vercel_insights_loader_re0/enabled/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_rendered_landing_is_human0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_every_indexable_page_is_c0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_pages_carry_no_inline_scr0/analytics-on/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_pages_carry_no_inline_scr0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_rendered_site_has_truthfu0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_every_page_loads_the_acce0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_cta_aria_labels_preserve_0/email-only/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_cta_aria_labels_preserve_0/with-booking/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_booking_identity_names_on2/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_navigation_is_identical_a1/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_stylesheet_cache_key_trac0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_navigation_is_identical_a0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_html_pages_point_crawlers0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_pilot_draft_encodes_conta0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_all_pages_share_the_curre0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_booking_identity_names_on4/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_booking_identity_names_on3/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_landing_hero_wave_is_prog0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_pointer_files_render_the_0/pointers/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_footer_reaches_the_same_p0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_comparison_page_names_alt0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_landing_console_renders_t0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_external_links_carry_noop0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_pages_publish_valid_json_0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_preloaded_fonts_exist_and0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_faq_structured_data_is_ge0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_vendored_font_license_is_0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_search_social_and_analyti0/email-only/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_search_social_and_analyti0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_public_surfaces_link_to_p0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_arcade_ships_as_progressi0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_llms_full_extends_the_sho0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_security_txt_is_routable_0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_booking_identity_names_on1/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_booking_identity_names_on0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/state/tmp-client-site-existing-isolated/test_sitemap_publishes_lastmod0/site/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/ux-pilot/built-site-design-rerun/.well-known/agent.json)
- [agent.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/ux-pilot/built-site/.well-known/agent.json)

**Passing historical regressions:**

- [source-claims-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/source-claims-stable.log)

**Prior independent review:**

- [independent-security-client-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md)

### QA-CLIENT-007 — Agent self-credentialing guide writes unevaluated shell substitution into dotenv signing key

Issue: [#538](https://github.com/PetrefiedThunder/agent-middleware-api/issues/538) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Generate the local signing seed in the invoking shell rather than storing unevaluated shell substitution in dotenv.

**Exact local fix/follow-up commits:** `028e36e8cf66a0b80ce0d232b724e3df483db92e`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [run_checks.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/run_checks.py)
- [test_doc_credentialing_seed.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_doc_credentialing_seed.py)
- [credentialing-doc-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/credentialing-doc-red.log)
- [credentialing-doc-red-result.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/credentialing-doc-red-result.json)

**Passing historical regressions:**

- [credentialing-doc-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/credentialing-doc-stable.log)

**Prior independent review:**

- [independent-security-client-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md)

### QA-CLIENT-008 — Key Rotation can consume multiple lives in one update despite granting invulnerability

Issue: [#560](https://github.com/PetrefiedThunder/agent-middleware-api/issues/560) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Honor collision invulnerability inside each sweeper iteration; one update cannot deduct multiple lives after respawn. Bust cached script references so deployed clients receive the corrected arcade code.

**Exact local fix/follow-up commits:** `3e6d52e404f724d62a3b8d52e5a9ee3172afa2d0`, `dd834f0c80d8d77cf5ac62165801657fd3f1ae93`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [check_arcade_cabinets.cjs](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/check_arcade_cabinets.cjs)
- [arcade-cabinet-check.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/arcade-cabinet-check.json)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)
- [resumed-stable-arcade.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-arcade.log)
- [ux-cache-site-tests.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/ux-cache-site-tests.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### QA-CLIENT-009 — Happy Path draws the player twelve pixels above its collision position

Issue: [#561](https://github.com/PetrefiedThunder/agent-middleware-api/issues/561) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Align the rendered player body with its ground/platform collision origin. Bust cached script references so deployed clients receive the corrected arcade code.

**Exact local fix/follow-up commits:** `3e6d52e404f724d62a3b8d52e5a9ee3172afa2d0`, `dd834f0c80d8d77cf5ac62165801657fd3f1ae93`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [check_arcade_cabinets.cjs](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/check_arcade_cabinets.cjs)
- [arcade-cabinet-check.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/arcade-cabinet-check.json)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)
- [resumed-stable-arcade.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-arcade.log)
- [ux-cache-site-tests.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/ux-cache-site-tests.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### QA-CLIENT-010 — Tap Forge discards passive quota earnings on every animation frame

Issue: [#562](https://github.com/PetrefiedThunder/agent-middleware-api/issues/562) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Carry fractional passive quota earnings across animation frames and clear the carry on reset. Bust cached script references so deployed clients receive the corrected arcade code.

**Exact local fix/follow-up commits:** `3e6d52e404f724d62a3b8d52e5a9ee3172afa2d0`, `dd834f0c80d8d77cf5ac62165801657fd3f1ae93`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [check_arcade_progress.cjs](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/check_arcade_progress.cjs)
- [arcade-progress-check.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/arcade-progress-check.json)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)
- [resumed-stable-arcade.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-arcade.log)
- [ux-cache-site-tests.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/ux-cache-site-tests.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### QA-CLIENT-011 — Security reviewer claim omits local invocations that cannot produce a receipt

Issue: [#563](https://github.com/PetrefiedThunder/agent-middleware-api/issues/563) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Qualify receipt guarantees for terminalized/reconciled paths and identify local crashes requiring manual review without a receipt.

**Exact local fix/follow-up commits:** `ed6b396d0290de8904b9ac6db6e90626ad0ad1aa`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [run_checks.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/run_checks.py)
- [test_docs_contracts.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_docs_contracts.py)
- [docs-contract-controls.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/docs-contract-controls.log)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### QA-CLIENT-012 — Golden-path dogfood substitution leaves incompatible message arguments

Issue: [#564](https://github.com/PetrefiedThunder/agent-middleware-api/issues/564) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Use the dogfood tool text argument for both first invocation and replay.

**Exact local fix/follow-up commits:** `ed6b396d0290de8904b9ac6db6e90626ad0ad1aa`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [run_checks.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/run_checks.py)
- [test_docs_contracts.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_docs_contracts.py)
- [docs-contract-controls.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/docs-contract-controls.log)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### QA-CLIENT-013 — Partner offline-verification install command omits required verify extra

Issue: [#565](https://github.com/PetrefiedThunder/agent-middleware-api/issues/565) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Install the SDK verify extra for source and wheel offline-verifier recipes.

**Exact local fix/follow-up commits:** `ed6b396d0290de8904b9ac6db6e90626ad0ad1aa`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [run_checks.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/run_checks.py)
- [test_docs_contracts.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_docs_contracts.py)
- [docs-contract-controls.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/docs-contract-controls.log)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### QA-CLIENT-014 — CI bootstrap recipe combines credentials from three separate provisioning runs

Issue: [#566](https://github.com/PetrefiedThunder/agent-middleware-api/issues/566) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Extract API key, wallet and key ID from one provisioning response.

**Exact local fix/follow-up commits:** `ed6b396d0290de8904b9ac6db6e90626ad0ad1aa`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [run_checks.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/run_checks.py)
- [test_bootstrap_docs.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_bootstrap_docs.py)
- [bootstrap-doc-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/bootstrap-doc-red.log)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### QA-CLIENT-015 — Legacy database guidance recommends stamping current head without schema equivalence

Issue: [#567](https://github.com/PetrefiedThunder/agent-middleware-api/issues/567) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Require physical schema/data-history review for unstamped existing databases; stamp only a proven matching historical revision.

**Exact local fix/follow-up commits:** `7cb38a46581ae6f172f8e21e349c87b5afa83699`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [run_checks.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/run_checks.py)
- [test_operator_docs.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_operator_docs.py)
- [operator-doc-controls.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/operator-doc-controls.log)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### QA-CLIENT-016 — Lockdown and key-rotation runbooks retain deployment paths contradicted by current immutable release SOP

Issue: [#568](https://github.com/PetrefiedThunder/agent-middleware-api/issues/568) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Use qualified exact-SHA release contexts and schema-compatible recovery in lockdown/key-rotation runbooks.

**Exact local fix/follow-up commits:** `7cb38a46581ae6f172f8e21e349c87b5afa83699`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [findings.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/findings.json)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### QA-CLIENT-017 — Local demo Compose recipe omits DATABASE_URL required for its key and trust workflow

Issue: [#569](https://github.com/PetrefiedThunder/agent-middleware-api/issues/569) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Replace the broken local Compose example with the supported persistent SQLite/signing-seed quickstart.

**Exact local fix/follow-up commits:** `7cb38a46581ae6f172f8e21e349c87b5afa83699`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [run_checks.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/run_checks.py)
- [test_operator_docs.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_operator_docs.py)
- [operator-doc-controls.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/operator-doc-controls.log)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### QA-CLIENT-018 — Historical external diagnostic harness reports zero findings for unauthenticated200 responses

Issue: [#570](https://github.com/PetrefiedThunder/agent-middleware-api/issues/570) · Severity: P3 · Local state: **retired_with_explicit_refusal**.

**Correction:** Retire historical gauntlet CLI and raw transport with explicit refusal; preserve archived raw output and label counts non-gating.

**Exact local fix/follow-up commits:** `9edad00dfcde0a1daa79b2da47faadd9221f46f5`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [run_checks.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/run_checks.py)
- [test_historical_gauntlet.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/test_historical_gauntlet.py)
- [historical-gauntlet-red.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/historical-gauntlet-red.log)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### QA-CLIENT-019 — Partner checklist uses GET for the POST-only receipt verification operation

Issue: [#571](https://github.com/PetrefiedThunder/agent-middleware-api/issues/571) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Use authenticated POST with receipt_id for receipt verification.

**Exact local fix/follow-up commits:** `ed6b396d0290de8904b9ac6db6e90626ad0ad1aa`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [findings.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/findings.json)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### QA-CLIENT-020 — Failure-lab suite quick commands select the older lab instead of the advertised fast tier

Issue: [#572](https://github.com/PetrefiedThunder/agent-middleware-api/issues/572) · Severity: P3 · Local state: **local_fixed**.

**Correction:** Point the advertised fast-tier Failure Lab command to the actual suite target.

**Exact local fix/follow-up commits:** `ed6b396d0290de8904b9ac6db6e90626ad0ad1aa`.

**Current domain review:** [handoff](clients-and-docs.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [findings.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/findings.json)

**Passing historical regressions:**

- [resumed-stable-suite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/clients_docs/resumed-stable-suite.log)

**Prior independent review:**

- [clients-review-infra.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/clients-review-infra.md)

### SEC-001 — Refresh widens an attenuated JWT scope set

Issue: [#503](https://github.com/PetrefiedThunder/agent-middleware-api/issues/503) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Preserve attenuated or empty JWT scopes across refresh and reject unbound/malformed refresh authority.

**Exact local fix/follow-up commits:** `cd9440c62d8a2e7540e161e7522fcec6e72b8c43`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [jwt-authority.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/jwt-authority.log)

**Passing historical regressions:**

- [fix-regression-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/fix-regression-stable.log)

**Prior independent review:**

- [independent-security-client-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md)

### SEC-002 — Scoped access tokens can mint unrestricted wallet API keys

Issue: [#504](https://github.com/PetrefiedThunder/agent-middleware-api/issues/504) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Reject JWT callers that attempt to mint or replace unrestricted persistent API credentials.

**Exact local fix/follow-up commits:** `cd9440c62d8a2e7540e161e7522fcec6e72b8c43`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [jwt-authority.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/jwt-authority.log)

**Passing historical regressions:**

- [fix-regression-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/fix-regression-stable.log)

**Prior independent review:**

- [independent-security-client-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md)

### SEC-003 — Derived JWT authentication bypasses the originating key use budget

Issue: [#505](https://github.com/PetrefiedThunder/agent-middleware-api/issues/505) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Atomically consume the originating live key use budget when authenticating derived JWTs.

**Exact local fix/follow-up commits:** `cd9440c62d8a2e7540e161e7522fcec6e72b8c43`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [jwt-authority.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/jwt-authority.log)

**Passing historical regressions:**

- [fix-regression-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/fix-regression-stable.log)

**Prior independent review:**

- [independent-security-client-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md)

### SEC-004 — Bearer callers choose fresh rate buckets with ignored API-key headers

Issue: [#506](https://github.com/PetrefiedThunder/agent-middleware-api/issues/506) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Select rate buckets from the accepted authentication path, ignoring spoofed unused key headers and stabilizing JWT rotation identity.

**Exact local fix/follow-up commits:** `cd9440c62d8a2e7540e161e7522fcec6e72b8c43`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [authority-runtime-expanded2.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/authority-runtime-expanded2.log)

**Passing historical regressions:**

- [fix-regression-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/fix-regression-stable.log)

**Prior independent review:**

- [independent-security-client-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md)

### SEC-005 — Readiness probe returns healthy HTTP status during dependency failure

Issue: [#507](https://github.com/PetrefiedThunder/agent-middleware-api/issues/507) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Probe required ORM and durable-state dependencies with bounded waits; return HTTP 503 when unavailable.

**Exact local fix/follow-up commits:** `4a4fc75089e323d2d413874cce4108558d2a7ba2`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [authority-runtime-expanded2.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/authority-runtime-expanded2.log)

**Passing historical regressions:**

- [fix-regression-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/fix-regression-stable.log)

**Prior independent review:**

- [independent-security-client-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md)

### SEC-006 — Late IGA compensation erases a different invocation velocity reservation

Issue: [#508](https://github.com/PetrefiedThunder/agent-middleware-api/issues/508) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Compensate the exact identity-bearing IGA velocity reservation once; never remove a newer invocation reservation.

**Exact local fix/follow-up commits:** `13c709711f06ee28ca848c75212d2ff3503ab6ed`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [authority-runtime-expanded2.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/authority-runtime-expanded2.log)

**Passing historical regressions:**

- [fix-regression-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/fix-regression-stable.log)

**Prior independent review:**

- [independent-security-client-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md)

### SEC-007 — Concurrent valid append makes audit verification falsely report truncation

Issue: [#525](https://github.com/PetrefiedThunder/agent-middleware-api/issues/525) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Read audit head and bounded event stream from one SQL statement snapshot, retaining real truncation detection.

**Exact local fix/follow-up commits:** `ee32061580c6ac70b7a0e78cb9f8f95550b4925c`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [audit-snapshot.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/audit-snapshot.log)

**Passing historical regressions:**

- [fix-regression-stable.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/fix-regression-stable.log)

**Prior independent review:**

- [independent-security-client-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/action_execution/independent-security-client-review.md)

### SEC-008 — AWI performs effects before budget/debit and repeats them after reservation contention

Issue: [#526](https://github.com/PetrefiedThunder/agent-middleware-api/issues/526) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Reserve permit authority and checkpoint an operation-key debit before any of six AWI callbacks. Preserve owners across ambiguous errors/process death; refund only proven non-dispatch, and replay receipts without redispatch.

**Exact local fix/follow-up commits:** `cb8d2f816badf7f504c6cb51153f91cf94ab15ed`, `2c6f4291a042bbf88ffbe9cb891c61aa516ae68c`.

**Current domain review:** [handoff](security-actions-integrations.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [awi-ordering2.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/awi-ordering2.log)

**Passing historical regressions:**

- [original-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/awi_ordering/original-green.log)
- [final-sqlite.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/awi_ordering/final-sqlite.log)
- [pg-final.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/awi_ordering/pg-final.log)

**Prior independent review:**

- [final-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/final-review.md)
- [awi-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/awi-review.md)

### SEC-009 — SQLite permit issuance signs values that change during persistence

Issue: [#584](https://github.com/PetrefiedThunder/agent-middleware-api/issues/584) · Severity: P2 · Local state: **local_fixed**.

**Correction:** Reject permit max_credits/aggregate caps that cannot survive exact storage before signing; preserve the numeric bounds in generated schemas.

**Exact local fix/follow-up commits:** `f27c213cd2e48c2fd1c9927a8fea85d4af5479ee`, `34040b3ad1e574445ad1ead70622967b58e3240a`.

**Current domain review:** [handoff](accounting.md). **Fixing PR:** not created. [PR #586](https://github.com/PetrefiedThunder/agent-middleware-api/pull/586) is separate QA evidence only.

**Original failing evidence:**

- [test_permit_numeric_followup.py](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/test_permit_numeric_followup.py)
- [independent-permit-numeric-ef64d02.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-permit-numeric-ef64d02.log)
- [independent-permit-numeric-ef64d02-result.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/security_runtime/independent-permit-numeric-ef64d02-result.json)

**Passing historical regressions:**

- [resume-numeric-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/resume-numeric-green.log)
- [resume-numeric-postgres-v2.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/resume-numeric-postgres-v2.log)
- [resume-schema-green.log](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/accounting_data/resume-schema-green.log)

**Prior independent review:**

- [final-review.md](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/final-review.md)
- [accounting-2cc557d-followup-targeted.json](/Users/sellers/Documents/Codex/2026-10-01/task-4/evidence/qa-20261002/reviews/independent_review/accounting-2cc557d-followup-targeted.json)

