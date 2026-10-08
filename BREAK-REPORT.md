# Break report: migrations and Alembic models

Summary: 1 break found, 1 fixed and tested, 0 fixed but still failing, 0 blocked.

Fresh SQLite databases created from these migrations stored three meant-to-be-false flags as the text `false`. SQLAlchemy then read that text as true. PostgreSQL already stored a real boolean false, so this fix does not change a database that has already applied revisions 022 and 023.

## High: omitted false flags read back as true on SQLite

What broke. After a full upgrade to head, an insert that left the column out stored text, not an integer 0, for:

- `permits.requires_human_approval` (a permit looked human-gated)
- `human_approvals.simulated` (an approval looked simulated)
- `refresh_tokens.revoked` (a refresh token looked revoked)

SQLAlchemy's SQLite Boolean treats any non-empty string as true, including the text `false`. The app's own ORM writes a Python false, so this hits inserts that rely on the database default (raw SQL and older workers that omit the column).

How to reproduce. Point Alembic at a new SQLite file, upgrade to head, and insert a wallet, a signing key, a permit, a human approval, and a refresh token while omitting those three columns. `typeof` on each value is `text`. Reading them back through a SQLAlchemy Boolean returns true.

Root cause. The migrations used `server_default="false"`, which SQLite stores as text:

- `migrations/versions/022_refresh_tokens.py:28` (`refresh_tokens.revoked`)
- `migrations/versions/023_human_approval_gate.py:38` (`permits.requires_human_approval`)
- `migrations/versions/023_human_approval_gate.py:53` (`human_approvals.simulated`)

Revision 024 repaired existing permit rows on SQLite, but it did not change the column default, and it did not repair the other two columns. Later table rebuilds kept the text default through head. A fresh upgrade still returned `('text', 'text', 'text')` before this fix.

PostgreSQL parses the string `false` as boolean false, so production rows were not flipped. Compiling `sa.false()` locally renders `DEFAULT false` on PostgreSQL and `DEFAULT 0` on SQLite.

Fix. Those three defaults are now `sa.false()`. Revision 024 still rewrites known text values on existing permit rows, so a database that already stored the text `false` is repaired when it passes through 024. No new migration was added.

Test results.

- Before the fix, `~/metacode/fleet/heavy .venv/bin/python -m pytest tests/test_migrations.py::test_sqlite_boolean_server_defaults_read_as_false -q --tb=short` failed in 1.36s: `AssertionError: ('text', 'text', 'text')`.
- After the fix, that test plus `test_024_repairs_sqlite_boolean_backfill` passed: `2 passed in 1.06s`.
- `~/metacode/fleet/heavy .venv/bin/python -m pytest tests/test_migrations.py tests/test_migration_rollout_notes.py -q --tb=line -x` : `21 passed, 1 warning in 7.56s`. The warning is SQLite skipping reflection of the expression index `uq_idempotency_governed_mcp_identity`.
- `~/metacode/fleet/heavy .venv/bin/python -m pytest tests/test_action_migrations.py tests/test_schema_boot.py tests/test_dispatch_claim_migration.py -q --tb=line -x` : `77 passed, 1 skipped, 1 warning in 52.08s`. The skip is `test_postgres_legacy_roundtrip_and_fail_closed_downgrade`, which runs only when `ACTION_MIGRATION_DATABASE_URL` is set. It was not set, and no shared database was used.
- `.venv/bin/ruff check` on the three migration files and `tests/test_migrations.py`: `All checks passed!`

## Open questions

Already-stamped SQLite files keep the old text default. Alembic will not run 022 or 023 again. Rebuilding the local SQLite file picks up the fix. A new revision could alter the three defaults in place, but it would move head, and startup refuses a stamp that is behind head. Production PostgreSQL already stores boolean false, so no migration was added. Revision number 043 was left untouched. C.Lee can decide if local SQLite files that are already at head must be repaired in place.

Migration 038's concurrent index was not re-tested for an interrupted retry in this pass. An earlier upgrade through 038 on the throwaway database `fleet_brk_api_migrations` succeeded, and that database has been dropped. That path is not a confirmed break.
