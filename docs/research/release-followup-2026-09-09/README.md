# Redis release follow-up rehearsal

This curated subset retains the portable, synthetic Redis upgrade rehearsal:

- `redis-source-manifest.json` pins the official 8.2.1 and 8.2.9 source archive
  checksums.
- `redis_upgrade_rehearsal.py` runs the local, loopback-only persistence and
  reconnect exercise.
- `redis-upgrade-validation.json` records the historical result and its limits.

The source archives and built Redis binaries are not vendored. The rehearsal
expects them under `/tmp/amw-redis-upgrade-20260909/`, as documented by the
script. Its JSON output overwrites `redis-upgrade-validation.json`; preserve the
historical result before rerunning if the comparison matters.

Provider readbacks, deployment/configuration identifiers, production state,
staged-change snapshots, logs, and JUnit XML are intentionally excluded. This
rehearsal does not authorize or perform a provider deployment and does not prove
production backup, restore, or zero-downtime behavior.
