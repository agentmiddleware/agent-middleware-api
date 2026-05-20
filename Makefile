.PHONY: demo-trust-plane demo-trust-plane-check agent-ops-war-room agent-ops-war-room-check demo-regengine-bridge demo-regengine-bridge-check trust-coverage-gate trust-release-gate

demo-trust-plane:
	uv run python scripts/demo_trust_plane.py

demo-trust-plane-check:
	uv run python scripts/demo_trust_plane.py --assert

agent-ops-war-room:
	uv run python scripts/agent_ops_war_room_demo.py

agent-ops-war-room-check:
	uv run python scripts/agent_ops_war_room_demo.py --assert --json

demo-regengine-bridge:
	uv run python scripts/demo_regengine_bridge.py

demo-regengine-bridge-check:
	uv run python scripts/demo_regengine_bridge.py --assert --json

trust-coverage-gate:
	scripts/trust_coverage_gate.sh

trust-release-gate:
	scripts/trust_release_gate.sh
