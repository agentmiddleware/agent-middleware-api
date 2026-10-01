# Contributing

Thanks for contributing to Agent Middleware API.

This project is maintained by one person. That is a real risk to anyone
depending on it, and the fastest way to reduce it is to make the project easy
to contribute to without a conversation first. Read
[`GOVERNANCE.md`](GOVERNANCE.md) for how decisions get made and what happens if
the maintainer goes quiet.

## Before you start: two rules that are not negotiable

**1. The product boundary is narrow, and most of the repository is outside
it.** The product is the trust plane: governed MCP tool calls with signed
permits, wallet metering, replay safety, signed receipts, and audit chains.
Everything else — AWI, browser automation, content generation, oracle crawls,
media utilities, IoT bridges, red-team services, RTaaS, telemetry auto-PR, and
sandbox demos — is a **frozen proof surface**. Do not add features to them. See
[`WEDGE.md`](WEDGE.md) and [`docs/PROOF_SURFACES.md`](docs/PROOF_SURFACES.md)
for the inventory and the rules for unfreezing something.

**2. Do not overclaim, in code or in prose.** This repository treats an
inaccurate README line as a bug of the same class as an inaccurate response
body, and has tests that enforce it — discovery manifests must match runtime
truth, advertised capabilities must equal the actual product capability list,
and proof surfaces must be labeled as such. If your change makes the software
do less than the docs say, fix the docs in the same PR.
[`SECURITY_LIMITATIONS.md`](SECURITY_LIMITATIONS.md) is the canonical list of
things this project deliberately does not claim; adding a claim it contradicts
will be rejected.

## Licensing of contributions

The core (everything outside the MIT directories listed in
[`LICENSING.md`](LICENSING.md)) is under the Business Source License 1.1; the
SDKs, framework integrations, wrappers, and examples are MIT. By submitting a
contribution you agree that it is licensed under the license of the directory
it lands in, and you certify the Developer Certificate of Origin (DCO 1.1) for
it. Contributors keep their copyright.

## Where to start

Good first contributions, roughly easiest first:

- **Documentation drift.** Find a doc that disagrees with the code and fix the
  doc. This is genuinely valuable here and needs no architectural context.
- **Test coverage on trust modules.** `make trust-coverage-gate` enforces an
  80% floor over the trust-plane control modules and prints exactly which lines
  are uncovered. Raising real coverage on those modules is always welcome.
- **Negative-path tests.** The security posture depends on things failing
  closed. New tests that prove a denial, a fail-closed path, or a tamper
  detection are high-value and low-risk.
- **Hardening items in [`docs/settlement-rails.md`](docs/settlement-rails.md).**
  The "fixes worth doing regardless" list at the end is a set of small, scoped,
  in-boundary improvements to the money seam.
- **Cross-language receipt fixtures.** The offline Ed25519 verifier and a
  public portable-receipt fixture now ship. Small, self-contained ports or
  compatibility tests that verify the same signed bytes without a running
  server remain useful; do not describe the co-hosted key snapshot as an
  independent issuer-identity proof.

There are currently no open issues, so nothing carries the `good first issue`
label and this list is the entry point rather than the issue tracker. Note that
[`docs/tech-debt-remediation-plan.md`](docs/tech-debt-remediation-plan.md) is
**complete** — its remaining two items are blocked on product decisions, not on
engineering capacity, so it is a historical record rather than a backlog.

Please avoid, unless you have discussed it first: new proof surfaces, new
governed adapters beyond MCP, settlement or payment rails, KMS integrations,
and anything in the freeze list in [`WEDGE.md`](WEDGE.md).

## Development Setup

1. Clone the repository.
2. Create a virtual environment.
3. Install dependencies.
4. Run tests.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

### Running the API locally

`make quickstart` is the golden path — it boots the real strict-trust server on
`127.0.0.1:8000`, generates and persists an Ed25519 signing seed, enables
self-serve key minting and one governed tool, and matches
[`docs/quickstart.md`](docs/quickstart.md) step for step.

To launch `uvicorn` directly instead, keep strict trust mode on and use local
SQLite files. Generate the signing seed once per database and reuse it on every
restart — changing key material under an existing key ID is rejected so that
historical receipts stay verifiable:

```bash
python3 -c 'import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())'
```

```bash
mkdir -p data
export ENVIRONMENT=local
export DATABASE_URL=sqlite+aiosqlite:///./data/local_api.db
export STATE_BACKEND=sqlite
export SQLITE_URL=./data/local_state.db
export VALID_API_KEYS=local-bootstrap-key
export TRUST_MODE_ENABLED=true
export ALLOW_LEGACY_UNPERMITTED_MCP=false
export ENABLE_PROOF_SURFACES=false
export TRUST_SIGNING_KEY_ID=local-dev-ed25519
export TRUST_SIGNING_PRIVATE_KEY_B64='<saved-base64-seed>'

uv run --with-requirements requirements.txt \
  uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Without `TRUST_SIGNING_PRIVATE_KEY_B64` the server refuses to start in default
strict-trust mode (`SigningKeyError: trust_signing_private_key_required`).
Interactive OpenAPI docs are then at `http://localhost:8000/docs`. Do not reuse
these local secrets anywhere shared.

`VALID_API_KEYS` holds bootstrap **operator** credentials, not agent runtime
keys. Two local-only credential surfaces exist, and they are **not**
interchangeable:

- **Wallet-scoped, non-admin.** Set `ENABLE_DEV_KEY_SELF_PROVISION=true` and
  call `POST /v1/dev-keys/self-provision`. This is the credential class that
  exercises the real permit → invoke → receipt loop as a governed non-admin
  caller, and the one to reach for by default.
- **Static `amw_dev_` keys** from `python scripts/generate_static_dev_keys.py`
  authenticate as **bootstrap admin** (`is_bootstrap_admin=True`), never
  wallet-scoped. They are for admin-shaped local testing and training material
  needing a credential that never rotates — they do not exercise wallet scoping
  and must not stand in for a governed caller.

Both surfaces are refused at boot by production-like deployments; details in
[`docs/static-dev-api-keys.md`](docs/static-dev-api-keys.md).

### Dependencies

`requirements.txt` is the **single source of truth** for dependencies. CI,
Docker, and `make test` (`uv run --with-requirements requirements.txt`) all
install from it, and Dependabot updates it.

`uv.lock` is gitignored — `uv run` may regenerate it locally, but it must
never be committed, and there is no `pyproject` `[project.dependencies]`.
Keeping a committed lock alongside `requirements.txt` let the two drift, which
once left a patched CVE unfixed (the lock pinned the vulnerable version while
`requirements.txt` already required the fix). Don't reintroduce a committed
lock without wiring the build/CI to consume it.

## Branching

- Default branch: `main`
- Feature branches: `feature/<short-description>`
- Fix branches: `fix/<short-description>`

## Pull Requests

Before opening a PR:

- Keep changes focused to one concern.
- Add or update tests for behavioral changes.
- Run `pytest -q` locally.
- If you add or change routes or response models, refresh the committed spec:
  `python scripts/export_openapi.py`
- If you add `SIMULATION_MODE_*` fields or MCP tools, refresh inventory:
  `python scripts/generate_sim_inventory.py`
- Update docs (`README.md`, env examples, or API docs) when behavior/config changes.

PR checklist:

- [ ] Tests pass
- [ ] `python scripts/export_openapi.py --check` passes (or run `export_openapi.py` to refresh `docs/openapi.json`)
- [ ] `python scripts/generate_sim_inventory.py --check` passes (or regenerate inventory)
- [ ] Backward compatibility considered
- [ ] New env vars documented
- [ ] Security impact reviewed
- [ ] No new claim contradicts `SECURITY_LIMITATIONS.md`

If your change touches the trust plane — permits, receipts, metering,
idempotency, audit, or the governed MCP path — run the release gate before
opening the PR:

```bash
make trust-release-gate
```

[`docs/PROOF_MATRIX.md`](docs/PROOF_MATRIX.md) lists every proof command and the
invariant it asserts, which is the fastest way to find the one that covers the
area you changed.

### What review looks like

One maintainer reviews everything, so throughput is the bottleneck and small,
focused PRs get merged much faster than large ones. To make review cheap:

- Say in the PR description what you verified and how, not just what changed.
- Include the output of the relevant proof command when you change trust-plane
  behavior.
- Split mechanical changes (formatting, renames) into their own commit or PR so
  the substantive diff stays readable.

If a PR sits without response for two weeks, comment on it to bump. That is a
reasonable thing to do, not a nuisance — see [`GOVERNANCE.md`](GOVERNANCE.md).

## Commit Style

Preferred format:

- `feat: ...`
- `fix: ...`
- `docs: ...`
- `chore: ...`

## Reporting Bugs

Use GitHub Issues and include:

- expected behavior
- actual behavior
- steps to reproduce
- request/response payloads (redacted)
- runtime info (Python version, environment, deployment target)

## Security Issues

Do not open public issues for sensitive vulnerabilities.  
Follow `SECURITY.md` for responsible disclosure.
