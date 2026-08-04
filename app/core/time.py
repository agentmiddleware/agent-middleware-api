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


def to_naive_utc(value: datetime) -> datetime:
    """Normalize a datetime to the naive-UTC form used for persistence.

    Tz-aware input is converted to UTC before ``tzinfo`` is dropped, so the
    instant is preserved. Naive input is returned unchanged (already the
    storage convention). Every datetime column in this schema is
    ``TIMESTAMP WITHOUT TIME ZONE`` (see ``migrations/versions``), and asyncpg
    refuses a tz-aware value for such a column with ``DataError: can't
    subtract offset-naive and offset-aware datetimes``.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
