import json
import os
import time as clock
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from threading import Lock
from typing import Any, Optional

from langchain_core.tools import tool
from loguru import logger

from src.databases import get_active_connector
from src.time_utils import now_wib, to_wib_iso

_ANOMALY_CACHE_TTL_SECONDS = max(0.0, float(os.getenv("ANOMALY_CACHE_TTL_SECONDS", "30")))
_anomaly_cache: dict[str, tuple[float, str]] = {}
_anomaly_cache_lock = Lock()


def _clear_anomaly_cache() -> None:
    with _anomaly_cache_lock:
        _anomaly_cache.clear()


def _get_cached_anomaly(key: str) -> Optional[str]:
    if _ANOMALY_CACHE_TTL_SECONDS <= 0:
        return None
    with _anomaly_cache_lock:
        cached = _anomaly_cache.get(key)
        if not cached:
            return None
        expires_at, payload = cached
        if clock.monotonic() >= expires_at:
            _anomaly_cache.pop(key, None)
            return None
        return payload


def _store_anomaly_cache(key: str, payload: str) -> None:
    if _ANOMALY_CACHE_TTL_SECONDS <= 0:
        return
    with _anomaly_cache_lock:
        _anomaly_cache[key] = (
            clock.monotonic() + _ANOMALY_CACHE_TTL_SECONDS,
            payload,
        )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime):
        return to_wib_iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _success(data: Any) -> str:
    payload = {
        "ok": True,
        "as_of": now_wib().isoformat(timespec="seconds"),
        "data": _json_safe(data),
    }
    return json.dumps(payload, ensure_ascii=False)


def _failure(tool_name: str, exc: Exception) -> str:
    logger.exception(f"{tool_name} failed: {exc}")
    payload = {
        "ok": False,
        "error": "Status query failed. Retry or use the generic query tool.",
    }
    return json.dumps(payload, ensure_ascii=False)


def _rows(connector: Any, query: str, params: Optional[Mapping[str, Any]] = None) -> list[dict[str, Any]]:
    return [_json_safe(row) for row in connector.fetch_all(query, dict(params or {}))]


def _clamp_limit(value: int, maximum: int = 50) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    return max(1, min(parsed, maximum))


def _clean_identifier(value: str, field_name: str = "identifier") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    clean = value.strip()
    if not clean:
        raise ValueError(f"{field_name} must not be empty")
    if len(clean) > 255:
        raise ValueError(f"{field_name} must be at most 255 characters")
    return clean


@tool
def get_grading_status_summary() -> str:
    """Return current grading job counts and row totals grouped by status.

    Use this tool for questions such as "berapa job grading yang selesai/gagal?"
    instead of writing SQL.
    """
    try:
        connector = get_active_connector()
        rows = _rows(
            connector,
            """
            SELECT status,
                   COUNT(*) AS job_count,
                   COALESCE(SUM(row_count), 0) AS total_rows
            FROM syncrono_service_grading_jobs
            GROUP BY status
            ORDER BY job_count DESC
            """,
        )
        total_jobs = sum(int(row.get("job_count") or 0) for row in rows)
        total_rows = sum(int(row.get("total_rows") or 0) for row in rows)
        return _success(
            {
                "status_counts": rows,
                "total_jobs": total_jobs,
                "total_rows": total_rows,
            }
        )
    except Exception as exc:
        return _failure("get_grading_status_summary", exc)


@tool
def get_matching_status_summary() -> str:
    """Return current matching job counts grouped by status.

    Use this tool for questions about MATCHING, COMPLETED, FAILED, or CANCELLED
    matching jobs instead of writing SQL.
    """
    try:
        connector = get_active_connector()
        rows = _rows(
            connector,
            """
            SELECT status,
                   COUNT(*) AS job_count,
                   COALESCE(SUM(total_incoming), 0) AS total_incoming,
                   COALESCE(SUM(total_candidates), 0) AS total_candidates,
                   COALESCE(SUM(auto_count), 0) AS auto_count,
                   COALESCE(SUM(review_count), 0) AS review_count,
                   COALESCE(SUM(unmatch_count), 0) AS unmatch_count,
                   COALESCE(SUM(conflict_count), 0) AS conflict_count
            FROM syncrono_portal_matching_jobs
            GROUP BY status
            ORDER BY job_count DESC
            """,
        )
        total_jobs = sum(int(row.get("job_count") or 0) for row in rows)
        return _success({"status_counts": rows, "total_jobs": total_jobs})
    except Exception as exc:
        return _failure("get_matching_status_summary", exc)


@tool
def get_failed_matching_jobs(limit: int = 20, include_cancelled: bool = False) -> str:
    """Return failed matching jobs with their recorded failure reason.

    The result always includes last_error and failed_at. Set include_cancelled
    to true when cancelled jobs and their reasons should also be returned.
    """
    try:
        safe_limit = _clamp_limit(limit)
        status_filter = "status IN ('FAILED', 'CANCELLED')" if include_cancelled else "status = 'FAILED'"
        connector = get_active_connector()
        rows = _rows(
            connector,
            f"""
            SELECT id,
                   file_id,
                   status,
                   current_stage,
                   total_incoming,
                   total_candidates,
                   auto_count,
                   review_count,
                   unmatch_count,
                   conflict_count,
                   last_error,
                   failed_at,
                   created_at,
                   completed_at
            FROM syncrono_portal_matching_jobs
            WHERE {status_filter}
            ORDER BY COALESCE(failed_at, created_at) DESC
            LIMIT :limit
            """,
            {"limit": safe_limit},
        )
        return _success(
            {
                "filters": {
                    "statuses": ["FAILED", "CANCELLED"] if include_cancelled else ["FAILED"],
                    "limit": safe_limit,
                },
                "returned": len(rows),
                "jobs": rows,
            }
        )
    except Exception as exc:
        return _failure("get_failed_matching_jobs", exc)


@tool
def get_file_status(identifier: str) -> str:
    """Return the latest grading and matching status for an exact file ID or filename.

    Use this tool when the user asks about the status of one file, including any
    matching failure reason. The identifier must be an exact file_id or filename.
    """
    try:
        clean_identifier = _clean_identifier(identifier)
        connector = get_active_connector()

        grading_rows = _rows(
            connector,
            """
            SELECT job_id,
                   file_id,
                   filename,
                   institution_name,
                   status,
                   stage,
                   grading_phase,
                   row_count,
                   data_type,
                   error,
                   created_at,
                   started_at,
                   finished_at
            FROM syncrono_service_grading_jobs
            WHERE file_id = :identifier OR LOWER(filename) = LOWER(:identifier)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"identifier": clean_identifier},
        )
        grading_job = grading_rows[0] if grading_rows else None

        grading_result = None
        if grading_job:
            result_rows = _rows(
                connector,
                """
                SELECT job_id,
                       file_id,
                       phase,
                       grade_id,
                       grade_letter,
                       quality_score,
                       row_count,
                       rows_graded,
                       rows_excluded,
                       rows_modified,
                       created_at
                FROM syncrono_service_grading_results
                WHERE job_id = :job_id AND phase = :phase
                ORDER BY created_at DESC
                LIMIT 1
                """,
                {
                    "job_id": grading_job.get("job_id"),
                    "phase": grading_job.get("grading_phase"),
                },
            )
            grading_result = result_rows[0] if result_rows else None

        matching_rows = _rows(
            connector,
            """
            SELECT id,
                   file_id,
                   status,
                   current_stage,
                   total_incoming,
                   total_candidates,
                   auto_count,
                   review_count,
                   unmatch_count,
                   conflict_count,
                   last_error,
                   failed_at,
                   created_at,
                   completed_at
            FROM syncrono_portal_matching_jobs
            WHERE file_id = :file_id OR id = :identifier
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {
                "file_id": grading_job.get("file_id") if grading_job else "",
                "identifier": clean_identifier,
            },
        )
        matching_job = matching_rows[0] if matching_rows else None

        return _success(
            {
                "identifier": clean_identifier,
                "found": bool(grading_job or matching_job),
                "grading_job": grading_job,
                "grading_result": grading_result,
                "matching_job": matching_job,
            }
        )
    except Exception as exc:
        return _failure("get_file_status", exc)


@tool
def get_latest_grading_jobs(limit: int = 5) -> str:
    """Return the most recent grading jobs with their final grade.

    Use this tool for "job terbaru" or "grading terakhir" questions.
    """
    try:
        safe_limit = _clamp_limit(limit)
        connector = get_active_connector()
        rows = _rows(
            connector,
            """
            SELECT g.job_id,
                   g.file_id,
                   g.filename,
                   g.institution_name,
                   g.status,
                   g.grading_phase,
                   g.row_count,
                   g.created_at,
                   g.finished_at,
                   g.error,
                   gr.grade_letter,
                   gr.quality_score
            FROM syncrono_service_grading_jobs g
            LEFT JOIN syncrono_service_grading_results gr
                   ON gr.job_id = g.job_id
                  AND gr.phase = g.grading_phase
            ORDER BY g.created_at DESC
            LIMIT :limit
            """,
            {"limit": safe_limit},
        )
        return _success({"limit": safe_limit, "returned": len(rows), "jobs": rows})
    except Exception as exc:
        return _failure("get_latest_grading_jobs", exc)


@tool
def get_batch_status_summary() -> str:
    """Return batch and batch-part totals grouped by status.

    Use this tool for questions about batch, part, or row progress.
    """
    try:
        connector = get_active_connector()
        batches = _rows(
            connector,
            """
            SELECT status,
                   COUNT(*) AS batch_count,
                   COALESCE(SUM(parts), 0) AS part_count,
                   COALESCE(SUM(total_rows), 0) AS total_rows
            FROM syncrono_service_batches
            GROUP BY status
            ORDER BY batch_count DESC
            """,
        )
        parts = _rows(
            connector,
            """
            SELECT status,
                   COUNT(*) AS part_count,
                   COALESCE(SUM(row_end - row_start + 1), 0) AS row_span
            FROM syncrono_service_batch_parts
            GROUP BY status
            ORDER BY part_count DESC
            """,
        )
        return _success({"batches": batches, "parts": parts})
    except Exception as exc:
        return _failure("get_batch_status_summary", exc)


@tool
def get_anomaly_summary(file_id: Optional[str] = None) -> str:
    """Return current K/L anomaly totals and the most common anomaly types.

    Optionally filter by an exact file_id. Use this tool for anomaly counts and
    percentages instead of writing SQL.
    """
    try:
        clean_file_id = _clean_identifier(file_id, "file_id") if file_id else None
        cache_key = f"file:{clean_file_id}" if clean_file_id else "global"
        cached = _get_cached_anomaly(cache_key)
        if cached is not None:
            return cached
        connector = get_active_connector()
        where_clause = "WHERE file_id = :file_id" if clean_file_id else ""
        params = {"file_id": clean_file_id} if clean_file_id else {}

        source_table = "syncrono_kl_records"
        totals = _rows(
            connector,
            f"""
            SELECT COUNT(*) AS total_rows,
                   COALESCE(SUM(CASE WHEN is_anomaly = 1 THEN 1 ELSE 0 END), 0) AS anomaly_rows
            FROM {source_table}
            {where_clause}
            """,
            params,
        )
        total_row = totals[0] if totals else {"total_rows": 0, "anomaly_rows": 0}
        total_rows = int(total_row.get("total_rows") or 0)

        if clean_file_id and total_rows == 0:
            enriched_totals = _rows(
                connector,
                """
                SELECT COUNT(*) AS total_rows,
                       COALESCE(SUM(CASE WHEN is_anomaly = 1 THEN 1 ELSE 0 END), 0) AS anomaly_rows
                FROM syncrono_kl_enriched
                WHERE file_id = :file_id
                """,
                {"file_id": clean_file_id},
            )
            enriched_row = enriched_totals[0] if enriched_totals else {"total_rows": 0, "anomaly_rows": 0}
            if int(enriched_row.get("total_rows") or 0) > 0:
                source_table = "syncrono_kl_enriched"
                total_row = enriched_row
                total_rows = int(enriched_row.get("total_rows") or 0)

        anomaly_rows = int(total_row.get("anomaly_rows") or 0)
        anomaly_rate = round((anomaly_rows / total_rows) * 100, 2) if total_rows else 0.0

        type_where = "WHERE is_anomaly = 1"
        type_params = {}
        if clean_file_id:
            type_where += " AND file_id = :file_id"
            type_params["file_id"] = clean_file_id
        anomaly_types = _rows(
            connector,
            f"""
            SELECT anomaly_type,
                   COUNT(*) AS row_count
            FROM {source_table}
            {type_where}
            GROUP BY anomaly_type
            ORDER BY row_count DESC
            LIMIT 10
            """,
            type_params,
        )

        payload = _success(
            {
                "file_id": clean_file_id,
                "source_table": source_table,
                "total_rows": total_rows,
                "anomaly_rows": anomaly_rows,
                "anomaly_rate_percent": anomaly_rate,
                "top_anomaly_types": anomaly_types,
            }
        )
        _store_anomaly_cache(cache_key, payload)
        return payload
    except Exception as exc:
        return _failure("get_anomaly_summary", exc)

