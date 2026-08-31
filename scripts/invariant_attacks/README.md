# Invariant attack harness

Adversarial, concurrency-aware tests that try to make the trust plane **violate
its own promises** — double-charge, overspend a permit, escape a permit's scope,
pass off a forged receipt, lose accounting integrity across a crash, or act
outside a credential's authority. Companion to
[`../../Invariant Attack Report.md`](../../Invariant%20Attack%20Report.md),
which records the exact requests, observed responses, and HELD/BROKE/PARTIAL
verdict for each.

Stdlib only (`urllib` + `threading` + `sqlite3`) — no test dependencies. Threads
release from a `threading.Barrier` so concurrent requests leave at the same
instant and actually exercise races (not just interleaved awaits). DB
reconciliation for the crash test reads the SQLite file **read-only** so it never
perturbs the state it is measuring.

## Run against a stock quickstart

```bash
# terminal 1 — boot the real local trust plane (SQLite, self-serve keys, one tool)
make quickstart

# terminal 2 — from the repo root
cd scripts/invariant_attacks
export API_URL=http://127.0.0.1:8000
export TP_DB_PATH=../../data/quickstart/api.db          # crash reconciliation reads this
export TP_NOTES_PATH=../../data/dogfood_partner_notes.jsonl

python attack1_double_charge.py     # double charging          -> HELD
python attack2_budget.py            # budget overspend         -> BROKE on sqlite
python attack2_mechanism_sqlite.py  #   ^ shows the lost update on permit.spent_credits
python attack3_scope.py             # scope escape             -> HELD
python attack4_forgery.py           # forged receipts          -> HELD
python attack6_key_misuse.py        # credential misuse        -> HELD
```

Each script provisions its own wallet(s) via `POST /v1/dev-keys/self-provision`,
prints a JSON evidence blob, writes `evidence_attack*.json`, and never prints a
full API key (keys are redacted to an 8-char prefix).

## Attack 2 root cause: SQLite vs Postgres

`attack2_budget.py` overspends the permit cap under concurrency **on SQLite**
because `authorize_and_reserve` (`app/services/permits.py:427`) guards the
check-and-reserve with `SELECT ... FOR UPDATE`, which SQLAlchemy **silently drops
on SQLite** (no row locking) — degrading it to a lost update. To confirm it is a
storage-engine artifact, not the shipped invariant logic, run the identical race
against Postgres, where the row lock is real:

```bash
# start a throwaway Postgres and a Postgres-backed instance on :8001, then:
API_URL=http://127.0.0.1:8001 python attack2_budget_postgres.py   # -> no overspend
```

## Attack 5 crash consistency

The authoritative proof already lives in the repo and kills workers at **exact
commit boundaries** (not a random `kill -9`):

```bash
make prove-crash-recovery      # 6 Postgres multi-process boundary-kill tests
```

`attack5_crash_sqlite.py` is the complementary live-instance test: it needs the
server booted under a controllable pid via `boot_controlled.sh` (so it can
`kill -9` and restart it), driven by env vars:

```bash
export TP_WORKDIR=/tmp/tp-crash TP_STATE_DIR=/tmp/tp-crash/state
export TP_PIDFILE=$TP_WORKDIR/server.pid TP_BOOT=$PWD/boot_controlled.sh
mkdir -p "$TP_STATE_DIR"
# boot once so the pid file exists, then run the test (it kills + restarts):
TP_PORT=8000 "$TP_BOOT" & echo $! > "$TP_PIDFILE"
TP_DB_PATH=$TP_STATE_DIR/api.db python attack5_crash_sqlite.py
```

`reconcile_probe.py` forces `reconcile_stuck_records(idle_seconds=0)` against the
live SQLite DB to show crash-orphaned records are repaired or flagged
`needs_review`, never silently dropped.

## Six-vector simultaneous attack

`attack_combined.py` runs **all six vectors at once** against shared victim +
attacker state, then kills the server mid-storm. The per-vector scripts prove
each invariant in isolation; this proves they still hold when a budget race, a
dedup race, a scope-escape, a confused-deputy and a `kill -9` all hit the same
victim wallet simultaneously. A pool of workers pulls an interleaved job queue
so every vector is in flight when a killer thread `SIGKILL`s the server the
instant committed debits cross a threshold; after restart every load/budget key
is replayed, then the money invariants are checked against the ledger, and a
receipt **minted during the storm** is tamper-checked offline.

It boots via `boot_controlled_uv.sh` (uv-based, so it runs on a fresh clone
without an activated venv). Because `uv run` keeps uvicorn as a child, the
launcher must be a **session leader** so the killer can `killpg` the whole group
— hence the `start_new_session` launch below (`setsid` does not exist on macOS).
The rate limiter is raised so the invariant under test — not the throttle — is
what the storm exercises:

```bash
export TP_STATE_DIR=/tmp/tp-combined TP_PIDFILE=$TP_STATE_DIR/server.pid
export TP_BOOT=$PWD/boot_controlled_uv.sh TP_DB_PATH=$TP_STATE_DIR/api.db
export TP_PORT=8000 RATE_LIMIT_PER_MINUTE=1000000
mkdir -p "$TP_STATE_DIR"
# boot once as a session leader, writing the group-leader PID to the pidfile:
python3 -c 'import subprocess,os; p=subprocess.Popen(["bash",os.environ["TP_BOOT"]],\
  start_new_session=True, stdout=open(os.environ["TP_STATE_DIR"]+"/server.log","ab"),\
  stderr=subprocess.STDOUT); open(os.environ["TP_PIDFILE"],"w").write(str(p.pid))'
# wait for http://127.0.0.1:8000/health to be 200, then:
python attack_combined.py     # -> verdict HELD, crash_happened true
```

Verdict is `HELD` only if the crash actually fired **and** every money invariant
held: no double charge, budget contained at the cap, charge⇔receipt paired, no
scope/credential escape produced a success, and the storm-minted receipt still
verifies and cannot be forged.
