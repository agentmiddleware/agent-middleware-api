.PHONY: quickstart quickstart-check live-loop-proof test test-all test-proof coverage prove-trust-plane prove-trust-plane-postgres prove-crash-recovery demo-trust-plane demo-trust-plane-check dogfood-trust-plane dogfood-trust-plane-check red-team-trust-plane red-team-trust-plane-check agent-ops-war-room agent-ops-war-room-check check-doc-references trust-coverage-gate trust-release-gate trust-conformance-live adversarial-battery-live railway-preflight railway-preflight-live

# The 15-minute golden path: boot a real local trust plane on loopback with
# self-serve key minting and one invokable governed tool, then follow
# docs/quickstart.md from `git clone` to an offline-verified signed receipt.
# State persists in data/quickstart/; `--reset` via QUICKSTART_ARGS wipes it.
quickstart:
	uv run --with-requirements requirements.txt python scripts/quickstart.py $(QUICKSTART_ARGS)

# CI guard for the documented golden path: boots the quickstart server in a
# throwaway state dir and drives every step of docs/quickstart.md over real
# HTTP, including offline verification and the tamper check.
quickstart-check:
	uv run --with-requirements requirements.txt pytest tests/test_quickstart_path.py -v

# One-command live proof against an already-running quickstart server
# (terminal 1: `make quickstart`). Drives discover -> authenticate ->
# authorize -> invoke -> meter -> receipt -> replay -> audit -> govern over
# real HTTP as a self-provisioned non-admin caller, verifies both the
# success and denial receipts offline, and writes a partner handoff bundle
# to data/live-loop-proof/.
live-loop-proof:
	uv run --with-requirements requirements.txt python scripts/live_loop_proof.py $(LIVE_LOOP_PROOF_ARGS)

# Fast inner loop: trust-plane (product) tests only. Proof-surface workloads
# are skipped here — run them with `make test-all` (what CI runs) or `make test-proof`.
# `--with-requirements` makes these self-contained: uv installs the runtime +
# test deps for the run, so `make test` works on a fresh checkout without a
# separate `pip install -r requirements.txt` (deps live in requirements.txt,
# not pyproject [project.dependencies]).
test:
	uv run --with-requirements requirements.txt pytest tests/ -q -m "not proof"

test-all:
	uv run --with-requirements requirements.txt pytest tests/ -q

test-proof:
	uv run --with-requirements requirements.txt pytest tests/ -q -m proof

# Reproducible whole-application coverage baseline. Production-posture tests run
# in their dedicated CI job because they require a different environment.
coverage:
	uv run --with-requirements requirements.txt pytest tests/ -q -m "not production_trust" --cov=app --cov-report=term-missing

prove-trust-plane:
	uv run --with-requirements requirements.txt python scripts/demo_trust_plane.py --assert

# NOTE: despite the name, this does not run the assertions on PostgreSQL.
# `alembic upgrade head` uses DATABASE_URL, but demo_trust_plane.py overwrites
# DATABASE_URL with a throwaway SQLite file before importing the app, so every
# assertion runs on SQLite. Treat this as a migration check. See the defect
# note in docs/PROOF_MATRIX.md; real PostgreSQL coverage is prove-crash-recovery.
prove-trust-plane-postgres:
	# Requires DATABASE_URL=postgresql+asyncpg://... and STATE_BACKEND=postgres
	alembic upgrade head
	uv run --with-requirements requirements.txt python scripts/demo_trust_plane.py --assert

# Two-process crash-consistency proof. Starts independent Uvicorn workers
# against one shared PostgreSQL database and kills a worker at durable commit
# boundaries, proving one side effect / debit / receipt, receipt-commit
# recovery, and fail-closed manual review after an ambiguous side effect
# (never an automatic redispatch).
#
# Requires DATABASE_URL=postgresql+asyncpg://... pointing at a DEDICATED,
# EMPTY database. The harness refuses to run otherwise: it fails closed on a
# non-PostgreSQL URL, a production-like ENVIRONMENT, a stale Alembic revision,
# or any application table that already holds rows, and it takes an advisory
# lock so two runs cannot overlap. This is the same proof CI runs.
prove-crash-recovery:
	alembic upgrade head
	RUN_MCP_MULTIPROCESS_TESTS=1 MCP_STRESS_DB_ISOLATED=1 \
	STATE_BACKEND=postgres ENVIRONMENT=test \
	uv run --with-requirements requirements.txt \
	  pytest tests/test_mcp_postgres_multiprocess.py -v --tb=short

demo-trust-plane:
	uv run --with-requirements requirements.txt python scripts/demo_trust_plane.py

demo-trust-plane-check:
	uv run --with-requirements requirements.txt python scripts/demo_trust_plane.py --assert

dogfood-trust-plane:
	uv run --with-requirements requirements.txt python scripts/dogfood_trust_plane.py

dogfood-trust-plane-check:
	uv run --with-requirements requirements.txt python scripts/dogfood_trust_plane.py --assert

red-team-trust-plane:
	uv run --with-requirements requirements.txt python scripts/red_team_trust_plane.py

red-team-trust-plane-check:
	uv run --with-requirements requirements.txt python scripts/red_team_trust_plane.py --assert

agent-ops-war-room:
	uv run --with-requirements requirements.txt python scripts/agent_ops_war_room_demo.py

agent-ops-war-room-check:
	uv run --with-requirements requirements.txt python scripts/agent_ops_war_room_demo.py --assert --json

# Fail if a comment or docstring names a symbol the tree no longer defines.
check-doc-references:
	python scripts/check_doc_references.py

trust-coverage-gate:
	scripts/trust_coverage_gate.sh

trust-release-gate:
	scripts/trust_release_gate.sh

# Live invariant suites target an operator-selected deployment. The conformance
# suite provisions persistent test rows and has no cleanup, so use staging unless
# you intend to retain that data on the selected target.
#
# trust-conformance-live asserts the invariants the product sells against a
# running instance: golden path, sequential replay, 15-way identical concurrent
# admission with safe in-progress responses, post-completion replay,
# idempotency-key conflict on a changed payload, budget denial, expired and
# forged permits, receipt and audit-chain verification, and tenant isolation.
# Requires AGENT_MIDDLEWARE_API_KEY (a bootstrap/admin key) plus either an
# explicit AGENT_MIDDLEWARE_API_URL or `TRUST_CONFORMANCE_ARGS="--api-url ..."`.
# The canonical production origin also requires `--confirm-production` in
# TRUST_CONFORMANCE_ARGS.
trust-conformance-live:
	uv run --with-requirements requirements.txt python scripts/trust_plane_conformance.py $(TRUST_CONFORMANCE_ARGS)

# adversarial-battery-live probes a deployment you operate for wallet
# isolation, invalid keys, forged receipts, permit key binding, expired
# permits, revoked keys, and replay idempotency, then revokes every key it
# minted. Requires API_URL (no default, by design) and BOOTSTRAP_KEY.
# MCP-invocation checks report SKIP when no invokable golden-path-echo tool is
# exposed; over-spend containment is not exercised.
adversarial-battery-live:
	uv run --with-requirements requirements.txt python scripts/adversarial_battery.py

# Railway deploy gate. Run under `railway run` (or with DATABASE_URL +
# PUBLIC_URL exported) to check migration parity and live posture together.
railway-preflight:
	uv run --with-requirements requirements.txt python scripts/railway_preflight.py

railway-preflight-live:
	uv run --with-requirements requirements.txt python scripts/railway_preflight.py --live
