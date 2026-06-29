.PHONY: test test-all test-proof prove-trust-plane demo-trust-plane demo-trust-plane-check red-team-trust-plane red-team-trust-plane-check agent-ops-war-room agent-ops-war-room-check trust-coverage-gate trust-release-gate

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

prove-trust-plane:
	uv run python scripts/demo_trust_plane.py --assert

demo-trust-plane:
	uv run python scripts/demo_trust_plane.py

demo-trust-plane-check:
	uv run python scripts/demo_trust_plane.py --assert

red-team-trust-plane:
	uv run python scripts/red_team_trust_plane.py

red-team-trust-plane-check:
	uv run python scripts/red_team_trust_plane.py --assert

agent-ops-war-room:
	uv run python scripts/agent_ops_war_room_demo.py

agent-ops-war-room-check:
	uv run python scripts/agent_ops_war_room_demo.py --assert --json

trust-coverage-gate:
	scripts/trust_coverage_gate.sh

trust-release-gate:
	scripts/trust_release_gate.sh
