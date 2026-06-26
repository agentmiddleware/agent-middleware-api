PYTHON ?= $(shell command -v python3.12 2>/dev/null || command -v python3 2>/dev/null || command -v python 2>/dev/null)
PYTEST ?= $(PYTHON) -m pytest

.PHONY: test test-all test-proof prove-trust-plane demo-trust-plane demo-trust-plane-check agent-ops-war-room agent-ops-war-room-check core-quality-gate trust-coverage-gate trust-release-gate

# Fast inner loop: trust-plane (product) tests only. Proof-surface workloads
# are skipped here — run them with `make test-all` (what CI runs) or `make test-proof`.
test:
	$(PYTEST) tests/ -q -m "not proof"

test-all:
	$(PYTEST) tests/ -q

test-proof:
	$(PYTEST) tests/ -q -m proof

prove-trust-plane:
	$(PYTHON) scripts/demo_trust_plane.py --assert

demo-trust-plane:
	$(PYTHON) scripts/demo_trust_plane.py

demo-trust-plane-check:
	$(PYTHON) scripts/demo_trust_plane.py --assert

agent-ops-war-room:
	$(PYTHON) scripts/agent_ops_war_room_demo.py

agent-ops-war-room-check:
	$(PYTHON) scripts/agent_ops_war_room_demo.py --assert --json

core-quality-gate:
	scripts/core_quality_gate.sh

trust-coverage-gate:
	scripts/trust_coverage_gate.sh

trust-release-gate:
	scripts/trust_release_gate.sh
