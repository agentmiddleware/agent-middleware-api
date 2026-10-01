# Licensing

This repository is licensed by directory. Two licenses apply.

| Path | License | License file |
|---|---|---|
| Everything not listed below: `app/`, `migrations/`, `scripts/`, `tests/`, `docs/`, `site/`, `failure_lab/`, `static/`, root files | [Business Source License 1.1](LICENSE) | `LICENSE` |
| `b2a_sdk/` | MIT | `b2a_sdk/LICENSE` |
| `awi_sdk/` | MIT | `awi_sdk/LICENSE` (copied into `awi_sdk/typescript/LICENSE` so the npm tarball carries it) |
| `framework_integrations/` | MIT | `framework_integrations/LICENSE` |
| `wrappers/*` (each package) | MIT | `wrappers/<package>/LICENSE` |
| `examples/` | MIT | `examples/LICENSE` |

## What the Business Source License allows

The core (the gateway: permits, idempotency, metering, dispatch, receipts,
audit chain, and everything that serves them) is **source-available**, not
open source in the OSI sense. Under the BSL 1.1 as parameterized in
[`LICENSE`](LICENSE) you may:

- read, copy, modify, and redistribute the code;
- run it in production to govern **your own** agents and tools, on
  infrastructure you own or rent;
- fork it, including if the maintainer goes quiet (see
  [`GOVERNANCE.md`](GOVERNANCE.md)).

The one thing the Additional Use Grant withholds: offering the core to third
parties as a hosted or embedded service that competes with the Licensor's
products or services built on it. That use needs a commercial license.

Each version converts to the **MIT License** four years after it is first
published under the BSL (the Change Date).

## Why the SDKs are MIT

Receipts are only "verifiable without us" if the verifier can be embedded
anywhere, so the offline verifier in `b2a_sdk/`, the client SDKs, the
framework integrations, the wrappers, and the examples stay MIT.

## History

Every version of this repository published before the licensing change
recorded in [`CHANGELOG.md`](CHANGELOG.md) was released under the MIT License.
That grant is irrevocable for those versions; it does not extend to later
versions.

## Commercial licenses

For a commercial license, or to run the core as a managed deployment, open a
GitHub issue titled "Commercial license" or contact the maintainer through
the GitHub profile at <https://github.com/PetrefiedThunder>. Pricing is not
public during the design-partner phase (see [`WEDGE.md`](WEDGE.md)).

## Contributions

Contributions are accepted under the license of the directory they land in.
See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Note on the Additional Use Grant wording

The Additional Use Grant text in `LICENSE` was drafted by the maintainer, not
by counsel. Have it reviewed before relying on it in a commercial negotiation.
