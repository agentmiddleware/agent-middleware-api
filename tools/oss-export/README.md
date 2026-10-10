# OSS export tooling

These scripts build the public-candidate repository `agent-middleware` from this
source repository. They were written on Oct 3, 2026 and used for the
fresh-history import in `agent-middleware` (Oct 3, 2026). This directory versions
them so the export is reviewable and repeatable.

## Files

| File | Purpose |
|---|---|
| `export.sh` | Copies the curated subset of this repo into the public layout: `gateway/` (FSL), `sdk/python`, `integrations/`, `examples/` (Apache-2.0), plus root trust docs. It carries `WEDGE.md` and `DESIGN_PARTNER_GUIDE.md` into `gateway/` for the wording pass. Excludes IP, data-room, site and internal deploy material, and operator-only scripts and their dependent tests. |
| `rewrite_paths.py` | Rewrites paths in gateway Python, shell, Makefile and pytest configuration, plus sibling example files, so they resolve in the public layout (`b2a_sdk` to `sdk/python`, `wrappers` to `integrations`, and so on). Usage: `python rewrite_paths.py <export>/gateway`. |
| `fix_wording.py` | Applies the claims wording rules to the exported docs: no "exactly-once" claims; the guarantee is described as at most one dispatch and one debit per accepted idempotency key. Run from the export root. Prints `MISS` for any pattern that no longer matches. |
| `drop_tests.py` | Removes named top-level test functions from a test file. Usage: `python drop_tests.py <file> <test_name> [...]`. |

## Notes before the next export

- Run `export.sh`, then `python3 rewrite_paths.py <export>/gateway`, then run
  `python3 <source>/tools/oss-export/fix_wording.py` from the export root.
  All three stages are required before validating or publishing the candidate.
- `export.sh` defaults to `~/tmp/amw-oss/src` and
  `~/tmp/amw-oss/agent-middleware`. Set `AMW_EXPORT_SRC` and `AMW_EXPORT_DST`
  to use a clean exact-SHA source checkout and a public working copy elsewhere.
  The destination must already be a Git working copy with `gateway/LICENSE.md`.
- `export.sh` replaces the gateway code, tests, scripts and curated docs on
  each run, removing stale files and newly excluded operator scripts. It keeps
  the hand-maintained FSL and Apache-2.0 license files, `spec/`, `verifier/`, CI
  and top-level README in `agent-middleware`; these files are not generated.
- The exported Dockerfiles use the public repository root as the build context
  so the gateway image can install the sibling Python SDK. Build with
  `docker build -f gateway/Dockerfile .` from the public root after staging the
  exact-SHA `gateway/.build_commit_sha` required by the production Dockerfile.
- `fix_wording.py` patterns are exact strings. After upstream doc edits, check
  its `MISS` output and update the pairs.
- Check emitted URLs for the legacy `PetrefiedThunder/` owner and use the
  canonical `agentmiddleware/` owner.
