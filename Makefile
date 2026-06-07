PYTHON ?= $(shell command -v python3.12 2>/dev/null || command -v python3 2>/dev/null || command -v python 2>/dev/null)
PYTEST ?= $(PYTHON) -m pytest

.PHONY: test prove-trust-plane demo-trust-plane demo-trust-plane-check agent-ops-war-room agent-ops-war-room-check core-quality-gate trust-coverage-gate trust-release-gate

test:
	$(PYTEST) tests/ -q

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
