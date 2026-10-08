# OSS export tooling

These scripts build the public-candidate repository `agent-middleware` from this
private repository. They were written on Oct 3, 2026 and used for the
fresh-history import in `agent-middleware` (Oct 3, 2026). Until now they lived
only on a local machine; this directory versions them unchanged so the export is
reviewable and repeatable.

## Files

| File | Purpose |
|---|---|
| `export.sh` | Copies the curated subset of this repo into the public layout: `gateway/` (FSL), `sdk/python`, `integrations/`, `examples/` (Apache-2.0), plus `SECURITY_LIMITATIONS.md` and `TRUST_MODEL.md`. Excludes IP, data-room, site and internal deploy material, and a fixed list of operator-only scripts. |
| `rewrite_paths.py` | Rewrites repo-relative paths in `.py`, `.sh` and `Makefile` files under the export so they resolve in the new layout (`b2a_sdk` to `sdk/python`, `wrappers` to `integrations`, and so on). Usage: `python rewrite_paths.py <export>/gateway`. |
| `fix_wording.py` | Applies the claims wording rules to the exported docs: no "exactly-once" claims; the guarantee is described as at most one dispatch and one debit per accepted idempotency key. Run from the export root. Prints `MISS` for any pattern that no longer matches. |
| `drop_tests.py` | Removes named top-level test functions from a test file. Usage: `python drop_tests.py <file> <test_name> [...]`. |

## Notes before the next export

- `export.sh` still hardcodes `SRC=~/tmp/amw-oss/src` and
  `DST=~/tmp/amw-oss/agent-middleware`. Point them at a clean exact-SHA checkout
  of this repo and a working copy of `agent-middleware` before running.
- `export.sh` deletes the old `LICENSE` files under `sdk/`, `integrations/` and
  `examples/`; the Apache-2.0 and FSL license files, `spec/`, `verifier/`, CI and
  the top-level README in `agent-middleware` were added by hand during the first
  import and are not produced by these scripts.
- `fix_wording.py` patterns are exact strings. After upstream doc edits, check
  its `MISS` output and update the pairs.
- After the repositories move to the `agentmiddleware` organization, update any
  `PetrefiedThunder/` URLs the export emits.
