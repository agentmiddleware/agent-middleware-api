# Discovery Standards Proposal (Draft)

**Status:** internal draft. Nothing here has been submitted to any standards
body, and this project has no prior relationship with one.

## The correction this draft starts from

The strategy input behind this document read:

> Own the discovery layer. `agent.json`, `llm.txt`, and `mcp/tools.json` are
> standards in the making. Propose them to the Agentic AI Foundation before A2A
> Agent Cards absorb the use case.

That framing cannot be adopted as written, because this repository already
documents the opposite about all three files:

- `/.well-known/agent.json` is **this project's bootstrap convention, and the
  code says so explicitly** — the model docstring, the route description, and
  the handler all state it is *not* an A2A Agent Card.
- `llms.txt` is **someone else's proposal** (llmstxt.org). This project adopts
  the path; it did not originate it, and the file it serves does not follow the
  proposal's structured format.
- `/mcp/tools.json` is **explicitly a convenience mirror** of the MCP-native
  `tools/list` JSON-RPC method. Code comments state that conformant MCP servers
  expose discovery through `tools/list`, and that `/mcp/messages` does not
  implement the complete MCP initialization lifecycle.

Proposing three file names as standards — two of which the project does not own
and one of which it documents as non-conformant — would fail this repository's
own honesty posture on contact with any competent reviewer. It would also be
strategically weak: file names are the least defensible part of what has been
built here.

**The defensible contribution is not the file names. It is the enforced
honesty contract underneath them.**

Nothing in the existing discovery ecosystem specifies that a manifest must be
*continuously true*. Agent Cards, llms.txt, and MCP `tools/list` all describe
shape. None of them specify that a server must prove its advertisement matches
its runtime behavior. This project does specify that, and enforces it in CI.
That is the thing worth standardizing.

## What is actually novel here

Four invariant families, each enforced by tests that run on every change.

### 1. Bootstrap liveness

The manifest publishes an ordered `bootstrap_sequence` telling an agent which
URLs to fetch and in what order. A test walks every URL in that list and
requires a public `200`. A manifest cannot advertise a bootstrap path it does
not serve.

*Enforced by* `tests/test_agent_first_contract.py`.

### 2. Simulation truth-linking

Every tool in `/mcp/tools.json` carries a `simulation` boolean and an
`integrationStatus` drawn from a closed set (`simulated`, `integrated`,
`postgres`, `platform`). For tools backed by a runtime pillar, a test asserts
the advertised `simulation` value **equals the live runtime value** that
`/health/dependencies` reports. A server cannot advertise a tool as really
integrated while running it in simulation.

This is the strongest invariant in the set, and the one with no analogue
anywhere else: it makes "is this capability real?" a machine-checkable
question rather than a marketing claim.

*Enforced by* `tests/test_discovery_consistency.py`.

### 3. Product/proof-surface labeling

The manifest's `capabilities` list must equal the product capability list
exactly — no aspirational additions. Every non-product surface must appear in a
separately labeled `proof_surfaces` catalog with `status: "proof_surface"`, and
each entry is stamped `mounted: false` when proof surfaces are disabled. The
aggregate discovery endpoint labels each capability `product` or
`proof_surface`.

An agent can therefore distinguish "this is the product" from "this is a demo"
without reading prose.

*Enforced by* `tests/test_discovery_honesty.py`, `tests/test_wedge_honesty.py`,
and `tests/test_mcp_discovery_wedge_gate.py`.

### 4. Mirror and alias consistency

Where the same information is served at more than one path, the payloads must
match: the well-known tools mirror must equal the canonical one modulo a
generated timestamp; `/llms.txt` must equal its `/llm.txt` alias; and the
`agent_first` block must be byte-identical across the manifest, the aggregate
discovery endpoint, and the root route. The static marketing site's pointer
manifest is contract-tested against the live server's values.

*Enforced by* `tests/test_discovery_drift.py`, `tests/test_discovery.py`, and
`tests/test_site_agent_interface.py`.

### Additional honesty properties worth specifying

- **No invented origin.** `canonical_api` is deliberately empty when
  `PUBLIC_URL` is unset rather than guessing `localhost`, and the served
  `llms.txt` never presents a bare localhost as a production base URL.
- **Credential-free verifiability.** The manifest carries a `try_it` block
  naming a command a reader can run locally, with no credentials, to verify the
  product's core claims. A test asserts that the block names the right command,
  requires no live credentials, and advertises at least `signed_receipt` and
  `replay_without_second_charge`. Nothing yet asserts that the advertised
  `proves` list is *exactly* what the command performs — closing that gap is
  one of the cheapest ways to make this property self-enforcing, and it should
  be done before the profile is proposed anywhere.
- **Honest commercial state.** Pricing is labeled a controlled design-partner
  pilot with `public_pricing: false` and `public_sla: false`; authentication
  declares `public_self_serve: false`. The manifest states that there is no
  self-serve key mint rather than implying one.

## Relationship to A2A Agent Cards

The absorption risk in the original framing needs adjusting: **the ecosystems
have already diverged on the filename.** A2A's current well-known path is
`/.well-known/agent-card.json`, not `agent.json`. This project makes no A2A
conformance claim.

Field overlap is real but shallow. Shared names — `name`, `description`,
`version`, `provider`, `capabilities`, plus endpoint and documentation pointers
— hide a semantic mismatch: this project's `capabilities` is a flat list of
product-capability strings, whereas an A2A Agent Card uses a structured
capabilities object alongside a `skills` array.

What this manifest carries that Agent Cards do not specify:

| Property | Here | A2A Agent Card |
|---|---|---|
| Labeled non-product surfaces | `proof_surfaces[]` with mount state | Not specified |
| Runtime simulation truth | Per-tool, cross-checked against health | Not specified |
| Ordered bootstrap sequence | `bootstrap_sequence`, liveness-tested | Not specified |
| Credential-free local proof | `try_it` command | Not specified |
| Commercial honesty flags | `public_pricing`, `public_sla`, `public_self_serve` | Not specified |

The right posture is therefore **complementary, not competitive**: propose an
honesty *extension profile* that could apply to an Agent Card, an MCP server
descriptor, or this manifest. Competing on filename is a fight this project
would lose and should not pick.

## Prerequisites before any external submission

These are ordered. None is optional.

1. **Publish a schema artifact.** The manifest shape currently exists only as a
   Pydantic model with `schema_version` pinned to a default `"1.0"`. There is no
   standalone JSON Schema, no versioning policy, and no changelog for the
   manifest itself. A proposal without a schema is not reviewable. The schema
   can be generated from the existing model and guarded by a test asserting the
   live manifest validates against the checked-in copy.

2. **Separate normative from deployment-dependent fields.** The manifest is
   environment-dependent today: `bootstrap_sequence`, `endpoints`,
   `documentation`, and `proof_surfaces` all change with
   `ENABLE_PROOF_SURFACES`, and `canonical_api` is empty without `PUBLIC_URL`.
   A spec must say which parts are fixed and which are deployment-shaped.

3. **Resolve the llms.txt position.** Either reformat the served file to the
   llmstxt.org structure or state the divergence explicitly. Proposing
   stewardship of a format the project does not follow is untenable. The honest
   current claim is "early adopter with tested serving semantics", not author.

4. **Present the annotations as a proposed extension, not as MCP.** The
   `simulation`, `integrationStatus`, `runtimeService`, and `creditsPerCallExact`
   annotations are repo-defined extensions living inside MCP's open-ended
   `annotations` field. They are not MCP semantics and must not be presented as
   such.

5. **Fix outward-facing overclaims first.** Two were found and corrected
   alongside this draft: the registry submission payload advertised
   `sse: true` and an `/mcp/sse` endpoint that no route implements, and the
   repo-root `.mcp.json` still carried pre-wedge "B2A control plane + AWI"
   branding. Both are fixed in this change. Any future submission must be
   re-audited against the shipped surface before it goes out.

6. **Do not claim adoption that does not exist.** The only deployments of these
   conventions are this project's own API and its marketing pointer site. The
   registry and marketplace documents in `docs/` are *prepared* submissions, not
   confirmed listings. A standards proposal that implies broader adoption is
   the same class of error this profile is meant to prevent.

## Honest assessment of the strategy

Standardization is a **low-priority, high-patience** track for this project.

The argument for doing it: the honesty contract is genuinely differentiated,
costs nothing extra to specify because it is already enforced, and being early
to name a category is cheap leverage.

The argument against doing it *now*: standards bodies reward demonstrated
adoption, and this project has one deployment and no design partners in
production yet. A proposal from a single-deployment project with no
adopters reads as premature and can burn the first-contact opportunity.

**Recommendation:** publish the schema and the profile as versioned documents in
this repository first, cite them from `related-work.md`, and let a design
partner's independent deployment supply the adoption evidence. Approach a
standards body only once at least one external deployment enforces the same
invariants. The profile is the asset; submission is a distribution choice that
can wait.

Do not, in the meantime, describe this project as engaged with any standards
body. It is not.
