import json
import os
import time as clock
from threading import Lock
from typing import Any, Mapping, Optional

from langchain_core.tools import tool
from loguru import logger

from src.databases import get_active_connector
from src.semantic.compiler import compile_semantic_query
from src.semantic.registry import DOMAINS, find_domain_for_query
from src.semantic.time_parser import parse_time_range
from src.time_utils import now_wib, to_wib_iso

_SEMANTIC_CACHE_TTL_SECONDS = max(0.0, float(os.getenv("SEMANTIC_TOOL_CACHE_TTL_SECONDS", "30")))
_semantic_cache: dict[str, tuple[float, str]] = {}
_semantic_cache_lock = Lock()


def _clear_semantic_cache() -> None:
    with _semantic_cache_lock:
        _semantic_cache.clear()


def _get_cached_payload(key: str) -> Optional[str]:
    if _SEMANTIC_CACHE_TTL_SECONDS <= 0:
        return None
    with _semantic_cache_lock:
        cached = _semantic_cache.get(key)
        if not cached:
            return None
        expires_at, payload = cached
        if clock.monotonic() >= expires_at:
            _semantic_cache.pop(key, None)
            return None
        return payload


def _store_cached_payload(key: str, payload: str) -> None:
    if _SEMANTIC_CACHE_TTL_SECONDS <= 0:
        return
    with _semantic_cache_lock:
        _semantic_cache[key] = (
            clock.monotonic() + _SEMANTIC_CACHE_TTL_SECONDS,
            payload,
        )


def _json_safe(value: Any) -> Any:
    from decimal import Decimal
    from datetime import date, datetime, time

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
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(x) for x in value]
    return value


@tool
def query_metrics(
    metrics: list[str],
    dimensions: Optional[list[str]] = None,
    time_range: Optional[Any] = None,
    filters: Optional[dict[str, Any]] = None,
    order_by: Optional[list[str]] = None,
    limit: int = 50,
    domain: Optional[str] = None,
) -> str:
    """Execute dynamic analytical queries across business domains using controlled metrics and dimensions.

    Use this tool for dynamic time-based questions ("hari ini", "minggu ini", "7 hari terakhir",
    "bulan ini"), multidimensional aggregations (e.g. grading per status, file unik per status,
    tren waktu, per institusi), and cross-status metrics.

    Available domains and key metrics:
    - Domain 'grading':
        metrics: grading_jobs, completed_jobs, failed_jobs, cancelled_jobs, running_jobs,
                 row_count, unique_file_ids, unique_filenames
        dimensions: day, week, month, status, institution, grade, phase, filename, file_id
    - Domain 'matching':
        metrics: matching_jobs, matching_completed_jobs, matching_failed_jobs, matching_running_jobs,
                 total_incoming, total_candidates, auto_count, review_count, unmatch_count, conflict_count
        dimensions: day, week, month, status, file_id
    - Domain 'batch':
        metrics: batch_count, batch_done, batch_running, batch_cancelled, batch_part_count, batch_row_count
        dimensions: day, status
    - Domain 'anomaly':
        metrics: total_kl_rows, anomaly_rows, clean_rows, anomaly_rate
        dimensions: day, anomaly_type, institution, file_id

    Time presets (WIB timezone):
        'today' / 'hari_ini'
        'yesterday' / 'kemarin'
        'this_week' / 'minggu_ini'
        'last_week' / 'minggu_lalu'
        'last_7_days' / '7_hari_terakhir'
        'this_month' / 'bulan_ini'
        'last_month' / 'bulan_lalu'
        'last_30_days' / '30_hari_terakhir'
        'all_time' (tanpa filter tanggal)
        Or custom range: {"preset": "custom", "date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"}

    Args:
        metrics: List of metric names to compute (e.g. ['grading_jobs', 'failed_jobs'])
        dimensions: Optional list of dimensions to group by (e.g. ['day'], ['institution'], ['status'])
        time_range: Preset string or dict for time filtering in WIB (e.g. 'today', 'this_week', 'last_7_days')
        filters: Optional dict of dimension filters (e.g. {'institution': 'Kemenkes'}, {'status': 'COMPLETED'})
        order_by: Optional order specification (e.g. ['day ASC'], ['failed_jobs DESC'])
        limit: Max rows to return (default 50, max 200)
        domain: Optional explicit domain ('grading', 'matching', 'batch', 'anomaly'). Auto-detected if omitted.
    """
    try:
        if not metrics or not isinstance(metrics, list):
            return json.dumps(
                {
                    "ok": False,
                    "error": "Parameter 'metrics' wajib diisi berupa list nama metrik.",
                },
                ensure_ascii=False,
            )

        resolved_domain = find_domain_for_query(metrics, dimensions or [], domain)
        parsed_time = parse_time_range(time_range)

        # Cache key based on normalized query arguments
        cache_key = json.dumps(
            {
                "domain": resolved_domain,
                "metrics": sorted(metrics),
                "dimensions": sorted(dimensions or []),
                "time_range": parsed_time,
                "filters": filters or {},
                "order_by": order_by or [],
                "limit": limit,
            },
            sort_keys=True,
            ensure_ascii=False,
        )

        cached_payload = _get_cached_payload(cache_key)
        if cached_payload is not None:
            return cached_payload

        sql, params, clean_metrics, clean_dims = compile_semantic_query(
            domain_name=resolved_domain,
            metrics=metrics,
            dimensions=dimensions,
            time_range=parsed_time,
            filters=filters,
            order_by=order_by,
            limit=limit,
        )

        connector = get_active_connector()
        rows = connector.fetch_all(sql, params)
        safe_rows = [_json_safe(r) for r in rows]

        domain_def = DOMAINS[resolved_domain]
        definitions = {}
        if "unique_file_ids" in clean_metrics or "unique_filenames" in clean_metrics:
            definitions["file_distinction"] = {
                "unique_file_ids": "Jumlah file_id unik (identifikasi unggahan data)",
                "unique_filenames": "Jumlah nama berkas fisik unik (filename)",
            }

        response = {
            "ok": True,
            "as_of": now_wib().isoformat(timespec="seconds"),
            "domain": resolved_domain,
            "primary_table": domain_def.primary_table,
            "period": parsed_time,
            "metrics": clean_metrics,
            "dimensions": clean_dims,
            "row_count": len(safe_rows),
            "definitions": definitions,
            "data": safe_rows,
        }
        payload = json.dumps(response, ensure_ascii=False)
        _store_cached_payload(cache_key, payload)
        return payload

    except Exception as exc:
        logger.exception(f"query_metrics error: {exc}")
        return json.dumps(
            {
                "ok": False,
                "error": f"Gagal mengeksekusi semantic query: {exc}",
            },
            ensure_ascii=False,
        )
