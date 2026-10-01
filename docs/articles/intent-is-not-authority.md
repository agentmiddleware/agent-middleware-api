> Status: draft for review. Industry sources are cited as characterized by the editorial review of 2026-10-01; they were not re-fetched from this environment.

# Intent is not authority: what an agent gateway cannot promise, and what it can

If your product has an agent that can issue a refund, release a payout, write a booking, trigger a deploy or change an entitlement, you will be offered a gateway that promises to make those calls safe. Agent Middleware API (AMW) is one. This article starts with the three strongest claims you might hear about it and why each is wrong, then what the repository's own tests support, then what you still have to build. Three evidence classes are kept apart and labelled: industry evidence, AMW's measured results (with the file that proves each), and hypotheses not yet measured.

## Three claims that do not hold

**"Exactly-once downstream."** No. The gateway guarantees at most one dispatch and at most one wallet debit per accepted idempotency key. The dispatch claim is committed before the network send, so it records the authority to send, not that a send happened and never that the tool acted. The remote effect is once only if the upstream tool also honours the forwarded key (README.md:157-162; WEDGE.md:16-23).

**"Any retry is safe from duplicating a refund or payout."** No. Same-key retries are deduplicated; that is tested. A fresh-key retry with identical arguments, in the shipped default configuration, is dispatched again, debited again and receipted again as a success (tests/test_upstream_retry_cap_enforcement.py:527-528). The failure lab's agent-restart case pays twice in every configuration it runs, and both payouts are correctly receipted (tests/test_failure_lab.py:183-199). A signed receipt records what the gateway observed; it does not independently prove downstream payment completion.

**"0% attack success."** Not a claim this repository can make. Its permit-validation battery shows ten attack types denied with no debit (docs/PROOF_MATRIX.md:72-79; tests/test_adversarial_five_claims.py). That is a validation battery, not an attack-success rate. The Open Agent Passport paper, sometimes cited for a zero result, reports it under a restrictive policy that allowed zero capabilities and a $0 limit (Table 6). That demonstrates blocking, not equally useful operation with perfect security.

## Thesis

AMW provides an operator-controlled boundary for consequential tool calls. Scoped permits constrain gateway-authorized actions; idempotency controls deduplicate tested same-key requests; signed receipts provide verifiable records of gateway decisions and observed outcomes. These controls do not guarantee exactly-once downstream effects. Their effectiveness depends on deployment configuration, protected signing keys, closed bypass routes, durable state and upstream reconciliation.

The organizing idea is that intent is not authority. An agent can decide to refund a customer; that decision is not permission. Permission is a permit the operator issued with a tool scope, budget and expiry, checked at the boundary before the tool runs. The agent cannot mint that permit; it can request one through `POST /v1/permit-requests`, and a human decides (README.md:240-241; WEDGE.md:174-177).

## What the industry evidence shows

*Evidence class: industry. Surveys, disclosed vulnerabilities and regulation. None of it measures AMW.*

The Cloud Security Alliance press release of 21 April 2026 reports a 65% figure. It is a result from 418 surveyed professionals, not a measured rate across all organizations. IBM's July 2025 report says 13% of respondents reported breaches of AI models or applications, and 97% of that subset lacked proper AI access controls. It concerns AI models and applications, not agents specifically.

Reported incidents do not establish accidental duplicate execution. They chiefly concern compromised credentials, malicious instructions, supply-chain exposure and exfiltration. EchoLeak was a disclosed vulnerability with no known affected customers, not a confirmed theft incident. The Step Finance theft is explained by the company as compromised executive devices; nobody has established that autonomous agents executed those transfers, so it is not used here as agent evidence.

Those classes map poorly onto what AMW does. By the repository's own OWASP self-assessment, credential misuse of wallet-scoped keys is enforced, prompt injection is contained rather than prevented (the gateway cannot see prompts), supply chain is partially addressed only because there is no registry to poison, and exfiltration is not addressed (docs/owasp-agentic-top10-mapping.md). AMW's idempotency argument has to stand on its own evidence. The repository's own problem evidence is three GitHub issue reports and one community thread, labelled as reproductions or duplicated-compute incidents, with no confirmed production incident of a duplicated payment charge (docs/market-research-2026-08.md:60-73).

On regulation, current Commission guidance under the AI Omnibus places the principal high-risk deadlines in December 2027 and August 2028. The EUR 35m / 7% of turnover penalty tier concerns prohibited practices, not ordinary high-risk compliance failures generally. AMW claims no compliance mapping to the EU AI Act or any other framework; receipts may be one input an auditor accepts, and that determination is the operator's (WEDGE.md:292-295). AEGIS is a research system described in a paper, not an established standard.

## What AMW's measured results show

*Evidence class: measured. In-repo tests against in-process fake executors, two failure labs on throwaway SQLite (PostgreSQL where noted), invariant attacks, and probes of the operator's own live deployment. None is a production or customer measurement.*

**Same key, same payload.** One dispatch, one debit, the same receipt id; on a local tool the tool body ran once. Proof: tests/test_adversarial_five_claims.py:345-353; tests/test_upstream_retry_cap_enforcement.py:656-657.

**Same key, changed payload.** Refused with `idempotency_key_reused`, no dispatch, no debit. Proof: app/services/idempotency.py:215-216; tests/test_adversarial_five_claims.py:824-833.

**Fresh key, identical arguments, default LOG mode.** `MCP_UPSTREAM_DUPLICATE_GUARD` defaults to `log`, which detects and allows. The second call dispatches and receives a success receipt; `dispatch_count == 2`. Proof: app/core/config.py:144-148; tests/test_upstream_retry_cap_enforcement.py:467-528.

**Fresh key, identical arguments, ENFORCE mode.** Refused before dispatch with `duplicate_request_new_key`; `dispatch_count == 1`. On PostgreSQL, five concurrent identical new-key calls yield one dispatch, one debit, one success receipt, four denials. The guard is opt-in, upstream tools only, and bypassed by `allow_identical_repeats`, by the 24-hour window expiring, and by OFF mode. Proof: tests/test_upstream_retry_cap_enforcement.py:460-461, 843-847; tests/test_duplicate_guard_postgres_concurrency.py:210-279.

**Agent restart with a new key: nothing the lab runs recovers it.** An agent that loses its key store and mints a new key for the same invoice pays twice in every configuration the single-run lab exercises; behind the gateway that is two dispatches, two debits, two valid receipts. The lab runs the default LOG mode with identical arguments and never ran under enforce, so it shows neither that enforce would catch this case nor that it is uncatchable. In the scenario suite, the only layer measured to catch the restart duplicate was a downstream keyed on the business operation id, not the gateway. Proof: tests/test_failure_lab.py:183-199; docs/failure-lab.md:110-111, 128-133; docs/failure-lab-suite.md:330-344.

**Against a correct native baseline, the gateway prevented no additional duplicate.** Where the downstream already honours a durable operation id, the verdict is that it did not observe an additional duplicate effect prevented by the gateway; it fails if the gateway ever beats a correct baseline on effect count. What the gateway added: one payout instead of two where the downstream had no idempotency control, the lost receipt recovered under the same key, and a receipted `delivery_uncertain` state in place of silence. What it cost: one retained charge against an unknown outcome. Proof: tests/test_failure_lab.py:98-99; docs/failure-lab-suite.md:131-146.

**Ambiguity after the send claim.** A death after the dispatch checkpoint is receipted `delivery_uncertain`, stays charged, and a same-key replay returns the identical receipt with no redispatch. A death before it refunds to net zero. Proof: tests/test_adversarial_five_claims.py:698-715, 758-774; tests/test_mcp_postgres_multiprocess.py (two-process SIGKILL on PostgreSQL).

**Budget and caps.** Concurrent calls cannot overspend `max_credits`. The invariant campaign originally found a roughly 3x overspend on SQLite from a silently dropped `FOR UPDATE`; after a guarded UPDATE, a 7-credit cap under 10 racers yields 3 successes on both engines. A cap-of-one permit refuses the second key with `permit_max_calls_exceeded`, holding its slot after an uncertain delivery; caps count calls, they do not deduplicate. Proof: docs/invariant-attack-report.md:171-268; tests/test_permit_budget_integrity.py; tests/test_upstream_retry_cap_enforcement.py:253-255, 312-313.

**Receipt tampering.** All ten edits inside `signing_input` broke the signature. Four envelope fields (`issuer`, `canonicalization`, `schema_version`, `keys_url`) are unsigned and were edited with the signature still valid. The gateway's own `POST /v1/receipts/verify` re-checks its stored row and answered `valid: true` for a tampered bundle; only the independent offline verifier catches it. Proof: failure_lab/scenarios/t10_receipt_tampering.py; docs/failure-lab-suite.md:299-328.

**Live deployment.** An unauthenticated external probe of 200 requests found no bypass of the auth boundary; three requests returned 503 and one timed out under load. It tested the unauthenticated layer only; the committed output is a 2026-09-14 regeneration. The production dispatch history is operator-issued traffic against the operator's own `partner.echo` echo server; no external caller exists. This is self-issued live gateway proof, not customer traction. Proof: docs/research/external-adversarial-2026-09-11/README.md; docs/reality-check-2026-09-01.md.

## What remains a hypothesis

*Evidence class: hypothesis. Believed from code reading or documented expectation, not measured.*

- A fresh key with different arguments defeats every guard mode. The guard matches on a hash of tool name, arguments, wallet and permit (app/routers/mcp.py:1063-1072; app/services/mcp_dispatch_attempts.py:671-672), so any argument change is a new request. No test exercises it.
- Enforce mode would stop the agent-restart case. The unit tests refuse identical-argument new keys within the window; the lab never ran with enforce.
- A real upstream completed its side effect. Tests count calls into fake executors and a simulated rail; a `success` receipt records that a valid response reached the gateway, not that money moved.
- The gateway is "a boundary the agent cannot route around". No test or control makes the upstream tool unreachable except through the gateway.
- Scenarios T11 (database restart), T13 (retention expiry) and T14 (standard MCP client) pass. They are documented expectations enforced by CI; the repository holds no recorded figures for them.
- The 2026-08-12 findings of 404s on the published proof and `/.well-known/jwks.json` have been fixed; no later document re-checks them (docs/hard-run-report-2026-08-12.md).

## The architectural risks

These are architectural: properties of how the system is built, not deployment footnotes.

**Bypass paths.** The gateway is the only path to its one configured upstream tool only once the operator closes the tool's other routes. The repository does not enforce that; the failure lab's baseline rows call the rail directly (SECURITY_LIMITATIONS.md:96-98).

**Key custody.** The Ed25519 signing key is loaded from an environment variable into process memory. No HSM, no KMS, rotation by redeploy. If it is compromised, every receipt and permit becomes forgeable from that moment (docs/key-management.md:7-11, 45-53). Key distribution is first-party: a compromised issuing origin can serve keys that validate forged receipts, and the independent verifier reports issuer trust as not established.

**Fresh-key semantics.** Identity is the caller's key. Two keys are two operations by design, the default guard only observes, and an argument change defeats every mode. The mitigation is in the agent: derive the key from the business operation, not the attempt.

**Downstream ambiguity.** `delivery_uncertain` is a truthful statement that the outcome is unknowable to the gateway, not a resolution. Closing it is manual and outside the boundary.

**Receipt completeness.** There is no transparency log; receipts prove what happened, never what did not. Pre-permit denials leave no receipt. A local tool that crashes after its side effect leaves a debit with no receipt, in permanent manual review. Revoking a compromised key makes every receipt it signed unverifiable (docs/agent-accountability.md:132-165).

**Durable state.** Audit chains are tamper-evident, not immutable; a database administrator can delete rows. The replay guarantee lasts exactly as long as the idempotency record row; no retention policy exists, and a future purge would silently make purged keys replayable (failure_lab/scenarios/t13_retention_expiration.py).

**Upstream reconciliation.** A stale dispatch claim waits an 11,430-second idle threshold plus a five-minute sweep, and reconciliation never redispatches or refunds on its own (docs/failure-semantics.md:311-315). Revocation landing after the `prepare` transaction does not stop a call already holding its reservation (docs/failure-lab-suite.md:243-262).

## What you still have to build

1. **Close the other routes.** Egress allowlist or proxy so the tool is reachable only through the gateway.
2. **Decide the guard mode.** Default `log` only observes. To refuse identical-argument fresh-key retries, set `MCP_UPSTREAM_DUPLICATE_GUARD=enforce`, run PostgreSQL, and know the 24-hour window.
3. **Key the agent on the business operation.** Persist the idempotency key with the invoice or order, not the attempt. Nothing at the boundary recovers a key the agent lost.
4. **Make the downstream idempotent too.** The remote-side guarantee holds only if the upstream honours the forwarded key. If you can change your downstream, do that first.
5. **Build the reconciliation loop.** Every `delivery_uncertain` receipt needs a person or job that queries the upstream with the forwarded key and closes it.
6. **Protect and pin the signing key.** Hardware custody is not shipped. Pin the public key set out of band so verification does not trust the origin it audits.
7. **Run production posture.** `TRUST_MODE_ENABLED=true`, legacy unpermitted MCP off, proof surfaces off, durable PostgreSQL with migrations. Boot refuses the permissive combination; it does not audit a running deployment.
8. **Treat receipts as gateway evidence.** Verify the signed fields offline. `issuer` and `keys_url` are unauthenticated; a receipt is not proof the payment completed.

## Closing

Intent is not authority. The agent's wish to refund, pay or deploy is a request; the permit is the authority; the receipt is the record of what the gateway decided and observed. AMW holds that line on one tested path, one adapter in front of one configured upstream tool, under conditions the operator must keep true. It does not make a retry safe when the agent forgets its own key, does not know what the downstream did, and cannot prove an action it did not record. The proof is self-issued, not customer traction. Judge it on those terms.

## Sources

External (characterizations as verified by the reviewer; not fetched from this environment):

- Step Finance company statement: https://www.bleepingcomputer.com/news/security/step-finance-says-compromised-execs-devices-led-to-40m-crypto-theft/
- EchoLeak discoverer's account: https://www.catonetworks.com/blog/breaking-down-echoleak/
- CSA survey methodology: https://cloudsecurityalliance.org/press-releases/2026/04/21/new-cloud-security-alliance-survey-reveals-82-of-enterprises-have-unknown-ai-agents-in-their-environments
- IBM report: https://newsroom.ibm.com/2025-07-30-ibm-report-13-of-organizations-reported-breaches-of-ai-models-or-applications,-97-of-which-reported-lacking-proper-ai-access-controls
- Open Agent Passport, Table 6: https://arxiv.org/html/2603.20953v1
- AI Omnibus: https://digital-strategy.ec.europa.eu/en/news/ai-omnibus-enters-force
- AI Act penalty tiers: https://digital-strategy.ec.europa.eu/en/policies/enforcement-ai-act
- AEGIS paper: https://arxiv.org/abs/2603.12621

Repository (all paths relative to the Agent Middleware API repository root):

- README.md; WEDGE.md; TRUST_MODEL.md; SECURITY_LIMITATIONS.md
- app/core/config.py; app/services/idempotency.py; app/services/mcp_dispatch_attempts.py; app/routers/mcp.py
- tests/test_adversarial_five_claims.py; tests/test_upstream_retry_cap_enforcement.py; tests/test_duplicate_guard_postgres_concurrency.py; tests/test_permit_budget_integrity.py; tests/test_mcp_postgres_multiprocess.py; tests/test_failure_lab.py; tests/test_failure_lab_scenarios.py
- docs/PROOF_MATRIX.md; docs/failure-lab.md; docs/failure-lab-suite.md; failure_lab/scenarios/t10_receipt_tampering.py; failure_lab/scenarios/t13_retention_expiration.py
- docs/invariant-attack-report.md; docs/research/external-adversarial-2026-09-11/README.md; docs/reality-check-2026-09-01.md; docs/hard-run-report-2026-08-12.md
- docs/key-management.md; docs/agent-accountability.md; docs/failure-semantics.md; docs/owasp-agentic-top10-mapping.md; docs/market-research-2026-08.md; docs/tool-interface-authority.md; docs/x-announcement-thread.md
