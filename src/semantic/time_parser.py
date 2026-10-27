from datetime import date, datetime, time as dt_time, timedelta
from typing import Any, Mapping, Optional

from src.time_utils import WIB, now_wib


def _start_of_day(d: date) -> datetime:
    return datetime.combine(d, dt_time.min, tzinfo=WIB)


def _format_db_datetime(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_time_range(spec: Optional[Any] = None) -> dict[str, Any]:
    current_now = now_wib()
    today = current_now.date()

    if spec is None or spec == "" or spec == "all_time":
        preset = "all_time"
        return {
            "preset": preset,
            "start_at": None,
            "end_at": None,
            "timezone": "Asia/Jakarta",
            "description": "Seluruh waktu (tanpa batas waktu)",
        }

    preset = None
    custom_from = None
    custom_to = None

    if isinstance(spec, str):
        preset = spec.strip().lower()
    elif isinstance(spec, Mapping):
        preset = (spec.get("preset") or "").strip().lower() or None
        custom_from = spec.get("date_from") or spec.get("start") or spec.get("from")
        custom_to = spec.get("date_to") or spec.get("end") or spec.get("to")
    else:
        preset = "all_time"

    if preset == "today" or preset == "hari_ini":
        start_dt = _start_of_day(today)
        end_dt = start_dt + timedelta(days=1)
        return {
            "preset": "today",
            "start_at": _format_db_datetime(start_dt),
            "end_at": _format_db_datetime(end_dt),
            "timezone": "Asia/Jakarta",
            "description": f"Hari ini ({today.isoformat()}) WIB",
        }

    if preset == "yesterday" or preset == "kemarin":
        start_dt = _start_of_day(today - timedelta(days=1))
        end_dt = _start_of_day(today)
        return {
            "preset": "yesterday",
            "start_at": _format_db_datetime(start_dt),
            "end_at": _format_db_datetime(end_dt),
            "timezone": "Asia/Jakarta",
            "description": f"Kemarin ({(today - timedelta(days=1)).isoformat()}) WIB",
        }

    if preset in ("this_week", "minggu_ini"):
        monday = today - timedelta(days=today.weekday())
        start_dt = _start_of_day(monday)
        end_dt = start_dt + timedelta(days=7)
        return {
            "preset": "this_week",
            "start_at": _format_db_datetime(start_dt),
            "end_at": _format_db_datetime(end_dt),
            "timezone": "Asia/Jakarta",
            "description": f"Minggu ini (mulai Senin {monday.isoformat()}) WIB",
        }

    if preset in ("last_week", "minggu_lalu"):
        current_monday = today - timedelta(days=today.weekday())
        last_monday = current_monday - timedelta(days=7)
        start_dt = _start_of_day(last_monday)
        end_dt = _start_of_day(current_monday)
        return {
            "preset": "last_week",
            "start_at": _format_db_datetime(start_dt),
            "end_at": _format_db_datetime(end_dt),
            "timezone": "Asia/Jakarta",
            "description": f"Minggu lalu ({last_monday.isoformat()} s/d {current_monday.isoformat()}) WIB",
        }

    if preset in ("last_7_days", "7_hari_terakhir", "7d"):
        start_dt = _start_of_day(today - timedelta(days=6))
        end_dt = _start_of_day(today + timedelta(days=1))
        return {
            "preset": "last_7_days",
            "start_at": _format_db_datetime(start_dt),
            "end_at": _format_db_datetime(end_dt),
            "timezone": "Asia/Jakarta",
            "description": "7 hari kalender terakhir WIB",
        }

    if preset in ("this_month", "bulan_ini"):
        first_of_month = today.replace(day=1)
        # Next month first day:
        if first_of_month.month == 12:
            next_month = first_of_month.replace(year=first_of_month.year + 1, month=1)
        else:
            next_month = first_of_month.replace(month=first_of_month.month + 1)
        start_dt = _start_of_day(first_of_month)
        end_dt = _start_of_day(next_month)
        return {
            "preset": "this_month",
            "start_at": _format_db_datetime(start_dt),
            "end_at": _format_db_datetime(end_dt),
            "timezone": "Asia/Jakarta",
            "description": f"Bulan ini ({first_of_month.strftime('%Y-%m')}) WIB",
        }

    if preset in ("last_month", "bulan_lalu"):
        first_of_current = today.replace(day=1)
        if first_of_current.month == 1:
            first_of_last = first_of_current.replace(year=first_of_current.year - 1, month=12)
        else:
            first_of_last = first_of_current.replace(month=first_of_current.month - 1)
        start_dt = _start_of_day(first_of_last)
        end_dt = _start_of_day(first_of_current)
        return {
            "preset": "last_month",
            "start_at": _format_db_datetime(start_dt),
            "end_at": _format_db_datetime(end_dt),
            "timezone": "Asia/Jakarta",
            "description": f"Bulan lalu ({first_of_last.strftime('%Y-%m')}) WIB",
        }

    if preset in ("last_30_days", "30_hari_terakhir", "30d"):
        start_dt = _start_of_day(today - timedelta(days=29))
        end_dt = _start_of_day(today + timedelta(days=1))
        return {
            "preset": "last_30_days",
            "start_at": _format_db_datetime(start_dt),
            "end_at": _format_db_datetime(end_dt),
            "timezone": "Asia/Jakarta",
            "description": "30 hari terakhir WIB",
        }

    if preset in ("last_90_days", "90_hari_terakhir", "90d"):
        start_dt = _start_of_day(today - timedelta(days=89))
        end_dt = _start_of_day(today + timedelta(days=1))
        return {
            "preset": "last_90_days",
            "start_at": _format_db_datetime(start_dt),
            "end_at": _format_db_datetime(end_dt),
            "timezone": "Asia/Jakarta",
            "description": "90 hari terakhir WIB",
        }

    if preset == "custom" or custom_from or custom_to:
        start_dt = None
        end_dt = None
        if custom_from:
            try:
                if len(str(custom_from)) == 10:
                    start_dt = _start_of_day(date.fromisoformat(str(custom_from)))
                else:
                    start_dt = datetime.fromisoformat(str(custom_from))
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=WIB)
            except Exception as exc:
                raise ValueError(f"Invalid date_from format: {custom_from}") from exc

        if custom_to:
            try:
                if len(str(custom_to)) == 10:
                    end_dt = _start_of_day(date.fromisoformat(str(custom_to))) + timedelta(days=1)
                else:
                    end_dt = datetime.fromisoformat(str(custom_to))
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=WIB)
            except Exception as exc:
                raise ValueError(f"Invalid date_to format: {custom_to}") from exc

        return {
            "preset": "custom",
            "start_at": _format_db_datetime(start_dt),
            "end_at": _format_db_datetime(end_dt),
            "timezone": "Asia/Jakarta",
            "description": f"Rentang custom: {custom_from or 'awal'} s/d {custom_to or 'akhir'}",
        }

    return {
        "preset": "all_time",
        "start_at": None,
        "end_at": None,
        "timezone": "Asia/Jakarta",
        "description": "Seluruh waktu",
    }
