# Trial run: permit to signed receipt to offline verify in one command

Five minutes, one command, no operator, no pre-shared key, no second
terminal. The trial boots its own throwaway server on loopback, mints a
wallet-scoped key, issues a permit, invokes the governed tool
`partner.notes.write`, exports the signed receipt, verifies it offline
with the SDK verifier, then stops the server and deletes all throwaway
state:

```bash
make trial
```

Expected ending (ids differ per run):

```text
[1/6] boot      server is up at http://127.0.0.1:54321
[2/6] key       minted wallet-scoped key ... on wallet ...
[3/6] permit    ... allows partner.notes.write, capped at 10 credits
[4/6] invoke    partner.notes.write ran, receipt ..., charged 2.00000000
[5/6] receipt   portable bundle exported to receipt-bundle.json
[6/6] verify    VERIFIED  ...

Trial passed in 6 stages: ...
```

Any stage that breaks its invariant exits non-zero before the summary
line: a passing run means the key mint, the permit check, the 2-credit
charge, the ledger linkage, and the offline signature check all held.

## Re-verify by hand

The run keeps two files in `data/trial-run/` and nothing
credential-bearing: `receipt-bundle.json` and `trust-keys.json`. Re-run
the verifier yourself from the repo root:

```bash
PYTHONPATH=b2a_sdk/src python -m b2a_sdk.verify_cli \
  --bundle data/trial-run/receipt-bundle.json \
  --keys data/trial-run/trust-keys.json
```

Exit codes: `0` verified, `1` well-formed but does not verify (treat as
tampered), `2` undetermined (unknown key or malformed input).

## Options

```bash
python scripts/trial_run.py --help
```

`--port` pins the loopback port instead of picking a free one,
`--output-dir` moves the kept bundle, and `--keep-state` keeps the
throwaway server directory (database, signing seed, server log) for
debugging instead of deleting it.

## What this proves, and what it does not

The trial proves the core loop runs end to end on a local machine:
authority before money, a real debit behind the receipt, and a receipt
that verifies without the server. It is exercised in CI on every push
(`trial-run` job plus `tests/test_trial_run.py`), so if this page and
the code disagree, the build breaks.

It does not prove production posture (operator-issued keys, key
rotation, real settlement), remote-upstream failure handling (see
[docs/failure-semantics.md](failure-semantics.md)), or anything about
performance: timings here are loopback against throwaway SQLite.

## Where to go next

- Walk each step by hand, including the double-charge and overspend
  attacks: [docs/quickstart.md](quickstart.md) (about 15 minutes).
- Hand a receipt bundle to someone else to verify with no account:
  `make live-loop-proof` against a running quickstart server.
- Operate it like an operator: [docs/golden-path.md](golden-path.md).
