.PHONY: test test-all test-proof coverage prove-trust-plane prove-trust-plane-postgres demo-trust-plane demo-trust-plane-check dogfood-trust-plane dogfood-trust-plane-check red-team-trust-plane red-team-trust-plane-check agent-ops-war-room agent-ops-war-room-check trust-coverage-gate trust-release-gate railway-preflight railway-preflight-live

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

prove-trust-plane-postgres:
	# Requires DATABASE_URL=postgresql+asyncpg://... and STATE_BACKEND=postgres
	alembic upgrade head
	uv run --with-requirements requirements.txt python scripts/demo_trust_plane.py --assert

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

trust-coverage-gate:
	scripts/trust_coverage_gate.sh

trust-release-gate:
	scripts/trust_release_gate.sh

# Railway deploy gate. Run under `railway run` (or with DATABASE_URL +
# PUBLIC_URL exported) to check migration parity and live posture together.
railway-preflight:
	uv run --with-requirements requirements.txt python scripts/railway_preflight.py

railway-preflight-live:
	uv run --with-requirements requirements.txt python scripts/railway_preflight.py --live
