"""Timezone helpers for displaying and storing Synchrono timestamps in WIB."""

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

WIB = timezone(timedelta(hours=7), name="WIB")
WIB_LABEL = "Asia/Jakarta"


def now_wib() -> datetime:
    """Return the current timezone-aware WIB datetime."""
    return datetime.now(WIB)


def to_wib(value: Optional[datetime]) -> Optional[datetime]:
    """Convert a datetime to WIB; treat naive database values as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(WIB)


def to_wib_iso(value: Optional[datetime]) -> Optional[str]:
    """Render a datetime as ISO-8601 with an explicit +07:00 offset."""
    converted = to_wib(value)
    return converted.isoformat(timespec="seconds") if converted is not None else None


def format_wib_timestamp(value: Optional[datetime] = None) -> str:
    """Format datetime as 'YYYY-MM-DD HH:MM:SS.fff' in WIB (3 decimal places for milliseconds)."""
    converted = to_wib(value) if value is not None else now_wib()
    return converted.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def wib_day_bounds(target_date: date) -> tuple[datetime, datetime]:
    """Return the inclusive start and exclusive end of a WIB calendar day."""
    start = datetime.combine(target_date, time.min, tzinfo=WIB)
    return start, start + timedelta(days=1)
