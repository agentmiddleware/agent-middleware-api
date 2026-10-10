# AMW Usage and Failure Insight runbook

**Status: synthetic acceptance only.** The insight reader, reports, and event
capture are local implementation work. This document does not authorize a
production migration, reporting exposure, capture activation, grant issuance,
business retry, refund, or customer contact. Keep
`OPERATION_INSIGHTS_REPORTING_ENABLED=false` and
`OPERATION_INSIGHTS_EVENTS_ENABLED=false` until their separate release gates are
approved. The event flag controls new capture; turning it off does not remove
retained events.

## Reproduce the local acceptance checks

Run from an isolated checkout, with no production connection or credentials:

```sh
uv run --with-requirements requirements.txt pytest tests/test_operation_insights_acceptance.py -q
uv run --with-requirements requirements.txt pytest tests/test_operation_insights_*.py -q
make test
make test-all
```

The ordinary test run skips PostgreSQL-only authority and snapshot proofs.
Run those proofs only against the designated disposable loopback databases
after checking that they contain no non-fixture rows. The tests reject any
other URL. `docs/schema-044-rollout.md` gives the authority migration and test
commands; the reader proof uses
`AMW_INSIGHTS_READER_TEST_DATABASE_URL=postgresql+asyncpg://sellers@127.0.0.1:55489/amw_insights_reader_test`.
Verify migrations 044 and 045 on a disposable database only, and reconcile the
current Alembic graph before any release: external PR #766 proposes a separate
043 migration. `docs/schema-045-rollout.md` covers event migration and retained
row behavior. Record pass, skip, and failure counts. Synthetic tests are not
evidence of production retention, traffic coverage, or deployed revision.

The acceptance record should cover the golden incident fixture matrix: lost
acknowledgment and crash boundaries; dispatch without effect proof; refund
without proof of no effect; same-key replay versus execution and fresh-key
races; missing, late, and conflicting records; retention gaps and UTC
boundaries; output caps and multi-page deduplication; wallet transfers,
unknown accounts and excluded classes; cross-wallet denial; secret/formula
redaction; and JSON/CSV counts and checksums. Assert that report and inspector
reads call no dispatch, refund, or business write path. Record the actual
expected unknowns and permitted `next_action` for each fixture.

The golden `lost_ack_after_effect` row supplies hypothetical independently
verified effect evidence to exercise conservative classification. The current
event emitter records downstream effect as unknown, and the scoped reader does
not establish external delivery from a dispatch claim. Passing that fixture
does not certify an end-to-end effect-proof capture path.

## Scoped read procedure, after separate approval

1. Verify `GET /health` reports the accepted `commit_sha` and
   `build_provenance=stamped`; verify the insight routes are mounted on that
   revision. A missing, mismatched, or unstamped build blocks production parity
   and deployment attribution claims. The process build stamp cannot fill a
   missing **per-operation** release field.
2. Use only a verified enterprise **access** token with the approved resource
   audience, plus an explicitly live reporting principal and wallet grants.
   Request a nonempty set of exact wallet IDs. The route accepts only the
   bearer header; API keys, bootstrap keys, wallet JWTs, and mixed credentials
   do not grant reporting access. A grant is tied to a certified ownership
   epoch and bounded evidence interval. Revocation is checked on the next
   request. The reader authorizes before querying evidence, joins, mapping, or
   exporting. Do not widen scope by wallet parentage, account mapping, or a
   linked evidence reference.
3. Request `/v1/operator/insights/report` with repeated `wallet_id` parameters,
   a UTC `as_of`, `days=7` or `days=30`, `time_basis=ingress` or
   `time_basis=first_observed_evidence`, and `format=json` or `format=csv`.
   The CSV response is a ZIP. The legacy export command remains a separate
   path. Insight CLI mode is `scripts/operator_analytics_export.py --insights`
   with `--insight-wallet-id`, `--as-of`, `--days`, `--time-basis`, `--format`,
   and `--out`. It reads the bearer from `AMW_INSIGHTS_BEARER_TOKEN`, requires a
   preexisting destination parent, creates the output with mode 0600, and
   rejects `--bootstrap-key`. Do not put tokens in arguments, reports, or logs.
4. To inspect one incident, use
   `/v1/operator/insights/operations/{operation_id}` with its exact authorized
   `wallet_id`, UTC `as_of`, `days`, and `time_basis`. An inaccessible ID must
   not reveal whether a foreign operation exists. If a bounded read is
   incomplete, treat absence as unknown, not as a clean 404.

The HTTP route currently supplies `mapping_version=unverified` because no
governed production account mapping is installed. Its customer account counts
cannot be certified until effective-dated wallet-to-account intervals and
internal, demo, CI, and monitoring exclusions are approved. A wallet with no
mapping remains visible as an unknown account inside its authorized scope.
Wallet-less raw rows never enter a report. The separate unknown-wallet count
requires a separate principal permission and request flag; it covers fixed
complete UTC days
and reports a null count when unauthorized, unavailable, or partial. Never
render any of those states as zero.

## Read a report before making a claim

- Confirm `window_start`, `window_end`, `as_of`, `time_basis`,
  `snapshot_cutoff`, `mapping_version`, `schema_version`, and
  `classification_version`. Windows are half-open and anchored to the original
  eligible ingress when that evidence exists. `first_observed_evidence` is a
  separate historical observed-activity cohort; never combine it with ingress
  or call it a full ingress rate. The immediately preceding equal-size window
  supplies the returning-account comparison.
- Check every source's availability, `earliest_retained_at`, enumeration and
  truncation status, event lag, consistency/skew flags, and gaps. Inspect each
  metric's `completeness`, grain, numerator, denominator, unknown and excluded
  counts before quoting its ratio. A zero denominator has a null ratio. An
  exact calculation over surviving rows is still partial when capture,
  retention, source access, mapping, or the prior period is unverified.
  A prior-window gap makes the **report** and returning-account comparison
  partial; it need not change a separately certified current-window request
  count. Never present a partial report as wholly complete because one metric
  is complete.
- Keep gateway outcome, downstream effect, refund, and budget release as four
  independent assessments. A dispatch claim is not delivery proof; a refund
  is not proof of no external effect. Missing receipt or terminal evidence
  cannot establish that nothing happened. Unknown and conflicting operations
  remain in the appropriate observed denominator and unresolved count.
- `server_release`, `deployment`, `client_version`, report `environment`, and
  `source_release` are unknown unless verified on the operation's evidence.
  The report envelope uses only consistent prospective event metadata; mixed
  or absent values stay unknown. An association with a deployment is not a
  causal diagnosis. Do not retrospectively fill missing metadata from the
  current process build.

Historical audit-only roots are unavailable to this reader because their
original ownership anchor is not verified. Refund work-item state embedded in
legacy response JSON is unavailable. Effect-free recovery can delete an
idempotency record; completely unrecorded ingress remains invisible. The
legacy audit reason summary and 200-row receipt/export defaults are not cohort
sources. The 168-hour telemetry setting is not a receipt, audit, idempotency,
or insight-event retention guarantee. Treat a source gap as a coverage gap,
not a measured zero. A missing recovery row is not proof that it was deleted;
record deletion only when independently verified.

## Inspect and reconcile an incident

Use the operation's evidence refs and ordered timestamps to identify the
original reason code, observed fault or denial, stage, and any clock skew or
conflict. Review the scoped durable dispatch, idempotency, ledger and receipt
facts; a no-receipt incident can still have surviving roots. Retain unknown
`unresolved_since` and `next_action` findings. The permitted investigation
actions are `inspect`, `reconcile`, and `manual_review`. A status lookup or
same-key replay is distinct from a fresh execution attempt. Do not infer a
safe executable retry from a refund, missing receipt, or dispatch claim.
Unknown downstream effect, expired/revoked authority, conflicting records, or
an unverified native replay contract requires manual review. This report never
performs a retry, refund, recovery write, or customer outreach.

If an event observer fails, record the delivery coverage gap and inspect the
business path independently. Observer failure must not roll back a business
transaction, redispatch, invoke recovery, or change the gateway response.
`get_delivery_metrics()` exposes `generated`, `delivered`, `failures`, and `pending`
counts in the current process; these worker-local counters are not durable
cluster-wide delivery certification. A terminal-only event is an orphan, and
a missing terminal remains open/unknown. Compare event lag and retained
ingress/attempt/terminal linkage before treating a prospective cohort as
complete.

## Export limits, integrity, and revisions

The implemented limits are 1,000 rows per read page, at most 100,000 output
operations, 7- or 30-day windows, and a shared 300-second request budget.
Keep the report and export within one authorized read-only repeatable-read
snapshot. A cap produces `coverage.truncated` and a partial artifact; use a
narrower window before drawing exact conclusions. If the read or serialization
cannot finish with a defensible snapshot, the HTTP route returns a generic
503 with no artifact. Retry only the **read** after investigating the limit;
this is not permission to repeat a business operation.

JSON is canonical. A CSV ZIP contains `report.json`, `report.csv`,
`operations.csv`, `evidence.csv`, `aggregates.csv`, and `manifest.json`. Check
the manifest's report ID, per-file SHA-256, row count, and completeness against
the extracted files. Compare JSON operation/metric counts to their CSV grains;
an evidence row may be linked to more than one operation. The writer uses a
private destination directory, 0600 files, atomic publication, and CSV formula
escaping. The caller still needs an approved export location, access policy,
retention period, and deletion procedure before production use. Keep exports
out of public storage and logs; do not include customer payloads or secrets.

Late evidence can revise an earlier window. Rerun that same `as_of`, window,
time basis, and scope under a new snapshot cutoff; retain both report IDs and
record the revised counts and coverage. `post_window_ingress_events` counts
late-ingested ingress at event grain; `post_window_observed_updates` counts
observed-activity operations updated after their window. These flag revision
exposure rather than a new request or a causal explanation. Do not move an old
operation into today's ingress cohort because its terminal event arrived
today. A changed mapping version or wallet ownership certification needs
separate attribution review; mapping cannot grant access or rewrite an old
owner's epoch.

## Release and rollback gates

Before **reporting exposure**, obtain separate approval for the deployed
revision and mounted routes; verified resource-audience issuer; grant issuance,
revocation, and append-only certified wallet ownership history; exact wallet
assignments; read-only database role or replica; schema and migration parity;
source permissions and retention; canonical account boundary and exclusions;
snapshot/replica lag; volume and query plans; and export access and retention.
Do not use a client-ID audience as the reporting resource audience. No trusted
issuer, epoch history, or grant means default denial.

Before **capture activation**, additionally verify in an approved non-production
environment that ingress and terminal correlation, allowlisted codes and
client versions, redaction, generated-versus-delivered coverage, wallet/epoch
resolution, and crash/observer isolation meet the acceptance fixtures. Qualify
the compatible recovery image and migration sequence before enabling workers.
Production activation needs its own acceptance. If a gate fails, leave both
flags off and retain synthetic artifacts. After an approved activation,
disable capture and/or reporting exposure through approved configuration to
stop new capture or reads. Preserve retained evidence and its retention policy;
do not delete records to make a downgrade succeed. Do not start automated
business recovery or outreach as part of rollback.
