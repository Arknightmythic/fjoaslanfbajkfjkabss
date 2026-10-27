"""Archive chat trace logs to SeaweedFS as daily WIB ``.log`` objects."""

import argparse
import io
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from loguru import logger

from src.storage.seaweedfs import ensure_bucket_exists, get_s3_client
from src.time_utils import WIB, now_wib, wib_day_bounds

load_dotenv()

DEFAULT_LOG_BUCKET = "chatbot-logs"


def _trace_log_path() -> Path:
    return Path(os.getenv("CHATBOT_TRACE_FILE", "/app/data/logs/chatbot-traces.jsonl"))


def _candidate_log_paths(log_path: Path) -> list[Path]:
    backup_count = max(1, int(os.getenv("CHATBOT_TRACE_BACKUP_COUNT", "5")))
    paths = [log_path]
    for index in range(1, backup_count + 1):
        paths.append(log_path.with_name(f"{log_path.name}.{index}"))
    return paths


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def collect_day_records(target_date: date, log_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Read current and rotated trace files, returning records for one WIB day."""
    start, end = wib_day_bounds(target_date)
    source_path = log_path or _trace_log_path()
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for path in _candidate_log_paths(source_path):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line in seen:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    timestamp = _parse_timestamp(record.get("timestamp"))
                    if timestamp is None or not (start <= timestamp < end):
                        continue
                    seen.add(line)
                    record = dict(record)
                    record["timestamp_wib"] = timestamp.astimezone(WIB).isoformat(timespec="seconds")
                    records.append(record)
        except OSError as exc:
            logger.warning(f"[LogArchiver] Could not read {path}: {exc}")

    records.sort(key=lambda item: _parse_timestamp(item.get("timestamp")) or start)
    return records


def build_log_bytes(records: list[dict[str, Any]], target_date: date) -> bytes:
    """Serialize records as newline-delimited JSON with a small text header."""
    header = f"# Synchrono chatbot log for {target_date.isoformat()} (WIB, UTC+07:00)\n"
    body = "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in records
    )
    return (header + body).encode("utf-8")


def archive_daily_log(
    target_date: Optional[date] = None,
    *,
    log_path: Optional[Path] = None,
    bucket: Optional[str] = None,
    client: Any = None,
) -> dict[str, Any]:
    """Build one day's WIB log and upload it to ``bucket/YYYY/MM/DD/``."""
    if target_date is None:
        target_date = (now_wib() - timedelta(days=1)).date()
    records = collect_day_records(target_date, log_path=log_path)
    payload = build_log_bytes(records, target_date)
    key = f"{target_date:%Y/%m/%d}/chatbot-{target_date.isoformat()}.log"
    resolved_bucket = bucket or os.getenv("CHATBOT_LOG_BUCKET", DEFAULT_LOG_BUCKET)
    s3 = client or get_s3_client()
    ensure_bucket_exists(s3, resolved_bucket)

    stream = io.BytesIO(payload)
    try:
        s3.upload_fileobj(
            stream,
            resolved_bucket,
            key,
            ExtraArgs={"ContentType": "text/plain; charset=utf-8"},
        )
    except TypeError:
        stream.seek(0)
        s3.upload_fileobj(stream, resolved_bucket, key)

    logger.info(
        f"[LogArchiver] Uploaded {len(records)} records to s3://{resolved_bucket}/{key} "
        f"({len(payload)} bytes)"
    )
    return {
        "bucket": resolved_bucket,
        "key": key,
        "record_count": len(records),
        "bytes": len(payload),
        "date": target_date.isoformat(),
        "timezone": "Asia/Jakarta",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive one day of chatbot traces to SeaweedFS")
    parser.add_argument("--date", help="WIB date to archive (YYYY-MM-DD); defaults to yesterday")
    args = parser.parse_args()
    target = date.fromisoformat(args.date) if args.date else None
    print(archive_daily_log(target))


if __name__ == "__main__":
    main()
