.PHONY: demo-trust-plane demo-trust-plane-check trust-release-gate

demo-trust-plane:
	uv run python scripts/demo_trust_plane.py

demo-trust-plane-check:
	uv run python scripts/demo_trust_plane.py --assert

trust-release-gate:
	scripts/trust_release_gate.sh
