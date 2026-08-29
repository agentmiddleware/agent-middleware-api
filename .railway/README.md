# Railway IaC owner

This directory is the reviewable Railway project configuration for the
existing `api-service` only. The stable `partial = "api-service"` export keeps
PostgreSQL, Redis, the partner MCP service, volumes, and the PITR bucket outside
this repository's IaC ownership.

Use Node.js 24 or newer. The package declares that minimum and the checker
fails before importing the TypeScript graph on an unsupported runtime. Install
the pinned SDK without running package lifecycle scripts, then evaluate the
desired graph entirely offline:

```bash
npm ci --prefix .railway --ignore-scripts
npm test --prefix .railway
```

The check fails closed unless the graph contains exactly the intended API
service, selected repository-owned deploy settings, region, domain, and
complete variable-name set. It does not contact Railway or print variable
values.

## Read-only plan

Only an authorized operator should link a checkout to the intended project and
environment. Confirm that link explicitly, then preview the live difference:

```bash
railway status --json
railway config plan
```

Do not add `--show-values`; plan output and CI logs must remain value-redacted.
Never run `railway config apply` or `railway config migrate --apply`
automatically. A missing resource or variable in IaC is a deletion, so any
delete, service create/rename, unrelated-resource change, or unexpected source
change is an abort condition. The only expected production source delta is the
separately reviewed disconnect of the stale GitHub source binding; it is never
implicitly approved by an otherwise clean plan.

Every API environment key is represented by `preserve()`. Railway remains the
owner of each value, including secrets and service references; this repository
owns only the key's continued presence. Add a newly introduced live key here
before any later plan/apply review or IaC may propose deleting it.

Restart policy is deliberately omitted from the tracked graph. Railway owns
the documented effective defaults, `ON_FAILURE` with 10 retries. Railway CLI
`5.43.3` re-proposes both fields when those defaults are explicit, even after
an apply. Omitting them removes that known explicit-field false drift and is
the candidate convergent representation. A fresh disposable
plan/apply/second-plan proof remains required before activation. After a CLI
or SDK upgrade, repeat that validation before reintroducing either field. Any
plan that would actually change restart behavior remains an abort condition.

## Activation is a separate operation

The current production service is still managed by legacy Config as Code and
has stale source metadata. Disconnecting that legacy owner, reviewing the
resulting source change, applying this graph, and deploying are separate,
later maintenance-window decisions. Follow
[`docs/deploy-railway.md`](../docs/deploy-railway.md) for activation, abort,
rollback, and exact-SHA application deployment. `railway up` uploads an
application release; it does not apply this IaC file.
