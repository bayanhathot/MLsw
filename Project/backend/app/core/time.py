"""UTC clock helpers matching the project's timezone-naive database columns."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return current UTC without tzinfo for existing portable DateTime columns."""

    return datetime.now(UTC).replace(tzinfo=None)
