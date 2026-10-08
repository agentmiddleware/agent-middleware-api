# Migration database policy: Postgres is canonical, SQLite is dev only

PostgreSQL is the only production database. SQLite files exist so a local
checkout can boot, run the suite, and rehearse migrations with zero setup.
Behavior verified on SQLite is a rehearsal, not production proof: types,
locks, and constraints can differ, and production boot refuses SQLite
(see `app/core/trust_mode.py`).

Known divergence: migration `036_permit_request_hash_anchor` enforces NOT
NULL on `permit_requests.original_request_hash` on PostgreSQL but leaves the
column nullable on SQLite, because SQLite cannot add a NOT NULL constraint
without a full table rebuild. The service layer closes the gap in both
environments: `original_request_hash` is a required model field
(`app/db/models.py`) and minting rejects a request whose `request_hash`
does not match it (`app/services/permit_requests.py`). Do not rely on the
database to enforce this column on SQLite, and do not read the SQLite schema
as the production contract.

Migration runner policy (`migrations/env.py`): when `DATABASE_URL` is
unset, the runner uses a local SQLite file. That fallback is for local
development only. On a production-like `ENVIRONMENT` (production, staging,
and siblings listed in `PRODUCTION_LIKE_ENVIRONMENTS`), or on a hosted
runtime with no explicit `ENVIRONMENT`, a missing `DATABASE_URL` is a hard
error instead. Set `DATABASE_URL` to the durable database before running
migrations anywhere that matters.
