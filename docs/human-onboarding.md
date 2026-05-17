# Human onboarding — what to verify before trusting this API

**Audience:** Human **operators** who deploy or secure this service. Autonomous
clients should **not** start here — use `GET /.well-known/agent.json`,
`GET /llm.txt`, and `GET /openapi.json` first (see `agent_first` in the manifest).

This API is **agent-first**: many endpoints look like normal SaaS, but several
product areas **default to simulation** (synthetic data) until real
integrations are wired. Use this page as a **human operator** checklist so you
do not mistake demos for production behavior.

## 1. “It runs” vs “it’s real”

**Risk:** Assuming oracle, red-team, IoT, media, RTaaS, telemetry PM, comms, or
content factory perform real external work when they are still simulated.

**Do this:**

- [ ] Call `GET /health/dependencies` and read `simulation_modes`. Any service
      with value `true` is using **simulation** behavior for that domain (see
      `app/core/runtime_mode.py`).
- [ ] Regenerate and skim [Simulation & MCP honesty inventory](simulations-inventory.md)
      (`python scripts/generate_sim_inventory.py`) for a pillar × MCP tool matrix.
- [ ] Compare deployed configuration to `.env.example` (`SIMULATION_MODE_*`
      variables). Defaults in code treat simulation as **on** for those domains.
- [ ] If you need a real integration, set the corresponding flag to `false`
      **only after** the real backend is implemented and tested; otherwise you
      may hit `NotImplementedError` paths.

**Related:** [Production beta roadmap](production-beta-roadmap.md) (what
“credible beta” means).

## 2. Know which hat you are wearing

| Role | You are responsible for | Start here |
|------|-------------------------|------------|
| **Operator** | Hosting, secrets, DB, migrations, Stripe/KYC env, sandbox isolation | This doc + [Threat model](threat-model.md) |
| **Integrator** | Calling the API from code or agents, keys, wallet scope | [Golden path](golden-path.md) + OpenAPI `/docs` |
| **End user** | Often **none** — the designed “customer” may be an autonomous agent | Your product’s UX, if any |

If you are “just trying the product,” you are usually **integrator + partial
operator** (local or Docker/Railway).

## 3. Money, keys, and dry-run (rehearse once)

**Risk:** Accidental real charges, confused wallet boundaries, or agents using
overpowered keys.

**Do this:**

- [ ] Walk [Golden path: wallet-scoped agent tool call](golden-path.md)
      end-to-end with **bootstrap** vs **DB-issued** keys as documented.
- [ ] Confirm **cross-wallet denial** (`403`) with an agent key before relying on
      tenancy.
- [ ] Use **Stripe test mode** and test webhooks until you intentionally move to
      production billing.
- [ ] Use **dry-run** flows where available before committing charges.

## 4. Sandbox and untrusted code

**Risk:** Treating behavioral Python execution as “safe” because it is behind
auth.

**Do this:**

- [ ] Read the README section on **behavioral sandbox** (Docker vs host Python).
- [ ] Read **Sandbox execution** and **Tool invocation** sections in
      [Threat model](threat-model.md).
- [ ] Do **not** enable `ALLOW_UNSAFE_HOST_PYTHON_SANDBOX=true` outside local
      development.

## 5. Discovery surfaces must agree

**Risk:** Agents read `agent.json`, `llm.txt`, and MCP manifests and assume
capabilities that are simulated or undocumented.

**Do this:**

- [ ] Fetch and skim:
      - `GET /.well-known/agent.json`
      - `GET /v1/discover` (full capability index; includes the same `agent_first`
        block as the manifest — they must stay in sync)
      - `GET /llm.txt`
      - `GET /mcp/tools.json` (canonical MCP manifest from the MCP router)
- [ ] Optionally compare with `GET /.well-known/mcp/tools.json` (separate route;
      may differ — if in doubt, treat `/mcp/tools.json` as the primary tool
      discovery path used in examples).
- [ ] Cross-check risky capabilities against `/health/dependencies` and
      `simulation_modes`.

**Automation:** Run `scripts/human_preflight.sh` against your base URL (see
below).

## 6. Beta scope vs your expectations

**Risk:** Expecting general-purpose serverless compute, full marketplace
settlement, or public arbitrary-code execution without strong isolation.

**Do this:**

- [ ] Read **Non-goals for beta** and milestones in
      [Production beta roadmap](production-beta-roadmap.md).
- [ ] Treat **audit export**, **stronger sandbox isolation**, and **commercial
      beta** checklists as ongoing work unless your deployment explicitly
      satisfies them.

---

## Preflight script

From the repository root, with the API running:

```bash
export API_URL=http://127.0.0.1:8000   # or your deployed URL
bash scripts/human_preflight.sh
```

Optional: install `jq` for formatted `simulation_modes` output.

The script checks liveness, dependency report (including simulation flags), and
public discovery URLs. It does **not** perform authenticated wallet flows; use
the golden path for that.

---

## Quick reference

| Question | Where to look |
|----------|----------------|
| What is simulated right now? | `GET /health/dependencies` → `simulation_modes` |
| Can I trust sandbox isolation? | README + `docs/threat-model.md` |
| End-to-end wallet + key + tool flow | `docs/golden-path.md` |
| What “beta” still means | `docs/production-beta-roadmap.md` |
| Env flags | `.env.example` |
