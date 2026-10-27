import json
from datetime import date
from unittest.mock import MagicMock, patch

from src.observability.log_archiver import archive_daily_log, collect_day_records


def _write_jsonl(path, records):
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def test_collect_day_records_filters_by_wib_day_and_reads_rotated_files(tmp_path):
    log_path = tmp_path / "chatbot-traces.jsonl"
    _write_jsonl(
        log_path,
        [
            {"timestamp": "2026-10-26T01:00:00+00:00", "event": "included"},
            {"timestamp": "2026-10-25T16:59:59+00:00", "event": "previous-day"},
            {"timestamp": "2026-10-26T17:30:00+00:00", "event": "next-day"},
        ],
    )
    _write_jsonl(
        log_path.with_name("chatbot-traces.jsonl.1"),
        [{"timestamp": "2026-10-26T02:00:00+00:00", "event": "rotated"}],
    )

    records = collect_day_records(date(2026, 10, 26), log_path=log_path)

    assert [record["event"] for record in records] == ["included", "rotated"]
    assert records[0]["timestamp_wib"] == "2026-10-26T08:00:00+07:00"


def test_archive_daily_log_uploads_year_month_day_key(tmp_path):
    log_path = tmp_path / "chatbot-traces.jsonl"
    _write_jsonl(
        log_path,
        [{"timestamp": "2026-10-26T01:00:00+00:00", "event": "chat.request_completed"}],
    )
    s3 = MagicMock()
    uploaded = {}

    def capture(stream, bucket, key, **kwargs):
        uploaded.update(body=stream.read(), bucket=bucket, key=key, kwargs=kwargs)

    s3.upload_fileobj.side_effect = capture

    with patch("src.observability.log_archiver.ensure_bucket_exists", return_value="chatbot-logs"):
        result = archive_daily_log(
            date(2026, 10, 26),
            log_path=log_path,
            bucket="chatbot-logs",
            client=s3,
        )

    assert result["key"] == "2026/10/26/chatbot-2026-10-26.log"
    assert result["record_count"] == 1
    assert uploaded["bucket"] == "chatbot-logs"
    assert uploaded["key"] == result["key"]
    assert uploaded["body"].startswith(b"# Synchrono chatbot log for 2026-10-26")
    assert b'"timestamp_wib":"2026-10-26T08:00:00+07:00"' in uploaded["body"]
    assert uploaded["kwargs"]["ExtraArgs"]["ContentType"].startswith("text/plain")
