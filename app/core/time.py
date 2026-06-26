"""Time helpers.

`utc_now` returns a naive UTC datetime — the same semantics as
`datetime.datetime.utcnow()`, which is deprecated in Python 3.12 and slated
for removal. Keep call sites simple: replace `datetime.utcnow()` with
`utc_now()` everywhere. Persisted datetimes throughout the codebase are
naive UTC; introducing tz-aware datetimes at random call sites would break
comparisons against values loaded from the database. A full tz-aware
migration is tracked separately.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current UTC time as a naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
