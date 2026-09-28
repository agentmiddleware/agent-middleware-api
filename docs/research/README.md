# Curated research artifacts

This directory keeps the smallest useful, reviewable source subset from five
local research packages produced September 5–9, 2026. The original local
packages were not moved, deleted, or modified during curation.

## Included packages

| Directory | Disposition | Curated contents |
| --- | --- | --- |
| `paid-pilot-2026-09-08` | Retain as a reproducible pilot source package. | Offer, validation record, workbook generator, and document renderer. |
| `pre-partner-readiness-2026-09-08` | Retain only the compact index layer. | Readiness and release decisions, check index, compact validation summaries, and secret-scan result. |
| `release-followup-2026-09-09` | Retain only the portable Redis rehearsal core. | Redis source checksums, synthetic upgrade rehearsal, and its compact validation result. |
| `unit-economics-2026-09-05` | Retain as superseded historical analysis. | Report, validation record, model and presentation source, inputs, and text/JSON/CSV outputs. |
| `unit-economics-reconsidered-2026-09-05` | Retain as the canonical economics analysis. | Report, validation record, model and presentation source, inputs, sanitized provider observation, public runtime observation, and text/JSON/CSV outputs. |

The reconsidered economics report supersedes the original report's weighting
and recommendation. The original remains useful for provenance and comparison.

## Excluded material

The curation intentionally excludes generated PDF, HTML, and XLSX files;
bytecode; raw logs and JUnit XML; screenshots and browser snapshots; local
temporary paths; provider deployment/configuration readbacks; and artifacts
containing point-in-time provider object identifiers. Generated presentation
files can be rebuilt from the retained source when needed. Filled pilot
trackers, customer data, credentials, and private correspondence must remain
outside the repository.

## Source inventory

The following immutable inventory was measured before curation. Each tree
digest is the SHA-256 of the sorted, per-file `shasum -a 256` output generated
from within that source directory, so the digest includes relative paths and
content hashes.

| Source directory | Files | Bytes | Source tree digest |
| --- | ---: | ---: | --- |
| `paid-pilot-2026-09-08` | 11 | 282,724 | `15f62bebeb8003593aea40ea83222c08f34e2d045c8ca836317eb9b06160b693` |
| `pre-partner-readiness-2026-09-08` | 93 | 944,648 | `a11287ce1eb8d6860486dc63d85f86273dfe88c00a05fc167cd7208fc3ad1c12` |
| `release-followup-2026-09-09` | 25 | 118,667 | `57bb30aa4790d097ef6a069730894dd4ca67ea539050e117ac2cd50215f46118` |
| `unit-economics-2026-09-05` | 13 | 594,665 | `89443f56182055b18ea58ee19527a9ef029a6b7a9d30a292be8d3ccfe561e328` |
| `unit-economics-reconsidered-2026-09-05` | 19 | 530,014 | `a4b2da6b7f62c379b52a80406ea539d9614a01dc8c04baeb11076b7b1784c02d` |

These digests describe the private source packages, not the curated directories.
The retained files are tracked normally and are covered by Git object hashes.
