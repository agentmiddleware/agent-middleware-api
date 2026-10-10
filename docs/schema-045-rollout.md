# Schema 045: prospective insight events (local draft)

Migration `amw_insights_events_20261010` follows
`amw_insights_authority_20261010` and creates `operation_insight_events`.
Capture remains disabled by default under `OPERATION_INSIGHTS_EVENTS_ENABLED`.
This draft was prepared for synthetic local tests. No production migration,
capture activation, backfill, or deployment is approved by this note.

The table stores bounded event identity, request/attempt/logical correlation,
verified wallet when available, occurrence and ingestion times, typed outcome
fields, and allowlisted runtime provenance. It has no request or response body,
credential, idempotency key, hash, IP address, email, or raw error column.

Preauthentication ingress has a server-issued request and event ID and a null
wallet, original-operation anchor, and ownership epoch. Once the handler
verifies wallet access, the original-operation anchor is the durable
`idempotency_records.record_id` when one exists. A verified execution-intent
denial without such a record uses its server-issued ingress event ID. A
same-key replay shares the durable logical operation ID and creates no attempt.
The ownership epoch stays null at capture; a scoped reader must resolve it
from verified original evidence and complete ownership history before exposing
raw events. A late terminal does not establish downstream effect.

Ingress and terminal writes have a 100 ms wait bound; dispatch and local-tool
attempt writes run in a bounded worker-local task set after trusted facts are
captured in the request. Generated, delivered, failed, and pending counts expose
local delivery gaps. A process crash can lose a pending attempt, especially
before a synchronous local tool returns; the reader must treat missing events
as incomplete coverage, not proof that no execution happened. Only fixed
allowlisted reason codes enter events. HTTP 200 JSON-RPC denials are classified
by trusted handlers, while missing outcome evidence remains unknown.

## Release prerequisites

Before a separately authorized deployment, record current database head and
schema parity, qualify a compatible recovery image, apply the migration on a
disposable PostgreSQL copy, and verify event redaction, generated-versus-
delivered coverage, and authoritative wallet/epoch resolution in an approved
non-production environment. Then plan a compatible image and migration rollout
without mixed-schema workers. Keep capture off until that gate passes and
production acceptance is explicit.

## Rollback after activation

Disable capture first. The migration refuses to drop a populated event table;
retained ingress and attempts may be the only evidence of a failed operation.
Do not delete those rows to make downgrade pass. An empty-table downgrade is
only a disposable local schema roundtrip. A production rollback would need a
separately reviewed recovery image and evidence-retention plan.
