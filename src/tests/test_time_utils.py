from datetime import date, datetime, timezone

from src.time_utils import format_wib_timestamp, to_wib, to_wib_iso, wib_day_bounds


def test_naive_utc_timestamp_is_rendered_as_wib():
    assert to_wib_iso(datetime(2026, 10, 26, 2, 15)) == "2026-10-26T09:15:00+07:00"


def test_format_wib_timestamp_milliseconds():
    dt = datetime(2026, 10, 26, 7, 35, 29, 566123, tzinfo=timezone.utc)
    # In WIB (+7 hours), 07:35:29.566 UTC becomes 14:35:29.566 WIB
    assert format_wib_timestamp(dt) == "2026-10-26 14:35:29.566"


def test_timezone_aware_timestamp_is_converted_to_wib():
    value = datetime(2026, 10, 26, 1, 0, tzinfo=timezone.utc)
    converted = to_wib(value)
    assert converted.hour == 8
    assert converted.utcoffset().total_seconds() == 7 * 3600


def test_wib_day_bounds_cover_exactly_24_hours():
    start, end = wib_day_bounds(date(2026, 10, 26))
    assert start.isoformat() == "2026-10-26T00:00:00+07:00"
    assert end.isoformat() == "2026-10-27T00:00:00+07:00"
