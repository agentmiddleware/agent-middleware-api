# Governance

## Current state, stated plainly

This project has **one maintainer**. `CODEOWNERS` assigns every path to
`@PetrefiedThunder`, and the commit history is one human author plus Dependabot
and AI-assisted commits — most co-authored under that account, seven authored
directly as `Claude <noreply@anthropic.com>`. There is no second reviewer, no
organization behind the repository, and no funding.

Anyone evaluating this project for production use should weigh that directly.
The code has real release gates and a genuine security posture, but the
**bus factor is one**. That is the single largest non-technical risk in
depending on it, and it is more important than any feature gap on the roadmap.

This document exists so that risk is legible and reducible rather than
discovered later.

## How decisions are made today

The maintainer decides. In practice the decisions that matter are constrained
by documents rather than taste, which is deliberate — it means a contributor can
predict an answer without asking:

- **Is this in scope?** [`WEDGE.md`](WEDGE.md) defines the product boundary and
  the freeze list. If a change expands a proof surface or adds something on the
  freeze list, the default answer is no.
- **Can we claim this?** [`SECURITY_LIMITATIONS.md`](SECURITY_LIMITATIONS.md)
  is the canonical list of non-claims. A change that contradicts it needs the
  limitation removed first, with evidence.
- **Is it proven?** [`docs/PROOF_MATRIX.md`](docs/PROOF_MATRIX.md) maps claims
  to executable proofs. New trust-plane behavior should extend a proof, not
  just add a test.

When those documents conflict with the code, the code wins and the document is
a bug.

## Merge requirements

- CI green on the pull request.
- For trust-plane changes: `make trust-release-gate` passing locally, and the
  relevant proof command's output included in the PR description.
- Maintainer approval.

The maintainer self-merges their own work. With one reviewer this is
unavoidable rather than ideal; the compensating controls are the automated
gates, which run identically regardless of who opened the PR, and the fact that
security-relevant surfaces are covered by negative-path tests that a careless
change fails loudly.

## Becoming a maintainer

There is no committee and no waiting period. The path is:

1. Land three or four non-trivial PRs — trust-plane tests, remediation-plan
   items, or documentation-drift fixes all count.
2. Demonstrate the two habits this codebase depends on: failing closed by
   default, and not letting docs drift ahead of behavior.
3. Ask. Commit access follows demonstrated judgment about scope and claims, not
   volume of code.

A second maintainer with review rights is the highest-value contribution
available to this project right now, ahead of any feature.

## If the maintainer goes quiet

The project is MIT licensed. If the maintainer is unresponsive for an extended
period, forking is explicitly endorsed — no permission needed, and no hard
feelings. To make a fork viable rather than a dead end:

- The trust-plane release gates are checked-in scripts
  (`scripts/trust_release_gate.sh`, `scripts/trust_coverage_gate.sh`) rather
  than CI-only configuration, and the remaining gates — production-trust
  posture, secret scanning, lint — live in the checked-in workflow file, so a
  fork inherits the quality bar.
- Deployment is one documented path
  ([`docs/deploy-railway.md`](docs/deploy-railway.md)) from the repository
  Dockerfile, with no private build steps.
- Secrets are injected at runtime and are not present in the working tree.
  A production API key was committed once and **remains in git history** — see
  [`docs/api-key-rotation.md`](docs/api-key-rotation.md); the key was rotated
  and a gitleaks secret-scan CI job now guards against a repeat. Nothing in the
  repository must be re-issued by the original maintainer to run a fork.
- The proof commands run on a throwaway local database with no credentials, so a
  fork can verify the core claims on day one.

Security disclosures should follow [`SECURITY.md`](SECURITY.md). If the private
advisory flow gets no response within the stated triage window and the issue is
being actively exploited, disclose publicly rather than sitting on it
indefinitely.

## Funding

The project currently has no funding and does not solicit any. Sustained
maintenance is the constraint, not compute or infrastructure cost.

A strategy input suggested applying to a16z crypto, Coinbase Ventures, or the
AI Safety Fund. That advice needs correcting before anyone acts on it:

- **a16z crypto and Coinbase Ventures are venture investors, not grant
  makers.** They buy equity and underwrite growth expectations. Taking that
  money would convert a narrow, deliberately un-hyped infrastructure project
  into one carrying a venture growth obligation — and both firms invest along a
  crypto thesis that this project explicitly does not have. `WEDGE.md` freezes
  settlement, and the ledger here is closed-loop internal credits with no
  settlement claim. Pitching a crypto fund would require either misrepresenting
  the project or changing it to fit the pitch. Neither is acceptable.
- **The AI Safety Fund supports safety research**, typically evaluations and
  measurement rather than infrastructure maintenance. There is a plausible
  framing — verifiable accountability for autonomous agent actions is a real
  safety primitive — but it would fund a research output, not ongoing upkeep.
  Be honest about the fit before applying: this repository's safety-adjacent
  artifacts are an operational threat model and an adversarial smoke test.
  That is engineering hardening, not safety research, and reviewers will
  recognize the difference.

Better-matched sources for an open-source infrastructure project of this shape,
which fund maintenance directly and take no equity:

- **Sovereign Tech Agency** — funds maintenance and hardening of critical open
  digital infrastructure.
- **NLnet / NGI Zero** — grants for open protocols and trust, privacy, and
  security infrastructure; small-grant sizes suit a single-maintainer project.
- **Alpha-Omega** — targets security posture in critical open-source projects.
- **GitHub Sponsors / Open Collective** — low-overhead recurring support with no
  strings.

The honest sequencing: **design-partner revenue first, grants second, venture
capital probably never** for this repository as scoped. `WEDGE.md` already names
a first paid use case, and one paying design partner would do more for
sustainability — and for proving the product — than any grant application
written before that partner exists.

## Code of conduct

See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). The maintainer arbitrates, and
there is currently no appeal body — another honest consequence of a one-person
project.
