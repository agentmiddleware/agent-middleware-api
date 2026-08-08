## Summary

Describe what changed and why.

## Type of Change

- [ ] feat
- [ ] fix
- [ ] docs
- [ ] refactor
- [ ] test
- [ ] chore

## Validation

- [ ] `pytest -q`
- [ ] `python scripts/export_openapi.py --check` (or refreshed `docs/openapi.json`)
- [ ] `python scripts/generate_sim_inventory.py --check` (or regenerated inventory)
- [ ] manually tested key endpoint paths
- [ ] updated docs/config examples if needed
- [ ] no new claim contradicts `SECURITY_LIMITATIONS.md`

For trust-plane changes (permits, receipts, metering, idempotency, audit, or
the governed MCP path), also run `make trust-release-gate` and paste the
relevant proof output below. See [`docs/PROOF_MATRIX.md`](../docs/PROOF_MATRIX.md).

## Risk

- [ ] low
- [ ] medium
- [ ] high

Notes on migration, rollout, or rollback concerns:
