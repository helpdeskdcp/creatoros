"""Timezone-safety helper.

PostgreSQL preserves timezone info on TIMESTAMPTZ columns, but SQLite (used
in the test suite) hands back naive datetimes. Any code comparing a
DB-loaded datetime against datetime.now(UTC) must go through this first, or
it works in production and breaks under SQLite (or vice versa).
"""
from datetime import UTC, datetime


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
