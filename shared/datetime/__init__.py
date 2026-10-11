"""Timezone-aware timestamps; no dependency on the Windows tz database."""
from datetime import datetime, timedelta, timezone

MARKET_TZ = timezone(timedelta(hours=8))


def aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required")
    return value


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return aware(value).astimezone(timezone.utc).isoformat(timespec="microseconds")
