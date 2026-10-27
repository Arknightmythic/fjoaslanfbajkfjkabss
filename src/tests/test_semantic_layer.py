import json
from unittest.mock import MagicMock

import pytest

from src.semantic.compiler import SemanticCompilationError, compile_semantic_query
from src.semantic.registry import (
    find_domain_for_query,
    resolve_dimension_name,
    resolve_metric_name,
)
from src.semantic.time_parser import parse_time_range
from src.semantic.tool import _clear_semantic_cache, query_metrics


class FakeConnector:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def fetch_all(self, query, params=None):
        self.calls.append({"query": query, "params": params or {}})
        for marker, rows in self.responses:
            if marker in query:
                return rows
        raise AssertionError(f"Unexpected query: {query}")


@pytest.fixture(autouse=True)
def clean_cache():
    _clear_semantic_cache()
    yield
    _clear_semantic_cache()


def test_time_parser_presets():
    today = parse_time_range("today")
    assert today["preset"] == "today"
    assert today["start_at"].endswith("00:00:00")
    assert today["end_at"].endswith("00:00:00")
    assert today["timezone"] == "Asia/Jakarta"

    this_week = parse_time_range("this_week")
    assert this_week["preset"] == "this_week"
    assert "Senin" in this_week["description"]

    last_7 = parse_time_range("last_7_days")
    assert last_7["preset"] == "last_7_days"

    all_time = parse_time_range("all_time")
    assert all_time["preset"] == "all_time"
    assert all_time["start_at"] is None
    assert all_time["end_at"] is None

    custom = parse_time_range({"preset": "custom", "date_from": "2026-10-01", "date_to": "2026-10-15"})
    assert custom["preset"] == "custom"
    assert custom["start_at"] == "2026-10-01 00:00:00"
    assert custom["end_at"] == "2026-10-16 00:00:00"


def test_registry_resolves_indonesian_aliases():
    assert resolve_metric_name("jobs") == "grading_jobs"
    assert resolve_metric_name("total_jobs") == "grading_jobs"
    assert resolve_metric_name("file_unik") == "unique_file_ids"
    assert resolve_metric_name("nama_file_unik") == "unique_filenames"
    assert resolve_metric_name("anomali") == "anomaly_rows"
    assert resolve_metric_name("baris") == "row_count"

    assert resolve_dimension_name("hari") == "day"
    assert resolve_dimension_name("tanggal") == "day"
    assert resolve_dimension_name("institusi") == "institution"
    assert resolve_dimension_name("kementerian") == "institution"


def test_registry_detects_appropriate_domain():
    assert find_domain_for_query(["grading_jobs"], ["day"]) == "grading"
    assert find_domain_for_query(["auto_count", "matching_jobs"], ["status"]) == "matching"
    assert find_domain_for_query(["batch_part_count"], ["status"]) == "batch"
    assert find_domain_for_query(["anomaly_rows", "anomaly_rate"], ["institution"]) == "anomaly"


def test_compiler_builds_grading_query_with_join_for_grade():
    sql, params, metrics, dims = compile_semantic_query(
        domain_name="grading",
        metrics=["grading_jobs", "unique_file_ids"],
        dimensions=["day", "grade"],
        time_range={"start_at": "2026-10-20 00:00:00", "end_at": "2026-10-27 00:00:00"},
        filters={"grade": "A"},
        order_by=["day ASC"],
        limit=25,
    )

    assert "SELECT DATE(g.created_at) AS day, gr.grade_letter AS grade" in sql
    assert "LEFT JOIN syncrono_service_grading_results gr ON" in sql
    assert "WHERE g.created_at >= :p_time_start AND g.created_at < :p_time_end" in sql
    assert "gr.grade_letter = :p_filter_grade_0" in sql
    assert "GROUP BY day, grade" in sql
    assert "ORDER BY day ASC" in sql
    assert "LIMIT 25;" in sql
    assert params["p_time_start"] == "2026-10-20 00:00:00"
    assert params["p_filter_grade_0"] == "A"


def test_compiler_builds_anomaly_query_with_join_for_institution():
    sql, params, metrics, dims = compile_semantic_query(
        domain_name="anomaly",
        metrics=["total_kl_rows", "anomaly_rows", "anomaly_rate"],
        dimensions=["institution"],
        filters={"institution": "Kemenkes"},
        order_by=["anomaly_rows DESC"],
    )

    assert "JOIN syncrono_service_grading_jobs g ON" in sql
    assert "LOWER(g.institution_name) LIKE :p_filter_institution_0" in sql
    assert "GROUP BY institution" in sql
    assert "ORDER BY anomaly_rows DESC" in sql
    assert params["p_filter_institution_0"] == "%kemenkes%"


def test_compiler_clamps_limit_and_rejects_invalid_metric():
    sql, _, _, _ = compile_semantic_query(
        domain_name="grading",
        metrics=["grading_jobs"],
        limit=999,
    )
    assert "LIMIT 200;" in sql

    with pytest.raises(SemanticCompilationError, match="Metrik 'hacked_column' tidak tersedia"):
        compile_semantic_query(domain_name="grading", metrics=["hacked_column"])


def test_query_metrics_tool_returns_structured_payload(monkeypatch):
    fake = FakeConnector(
        [
            (
                "COUNT(*) AS grading_jobs",
                [{"day": "2026-10-26", "grading_jobs": 80, "unique_file_ids": 65, "unique_filenames": 6}],
            )
        ]
    )
    monkeypatch.setattr("src.semantic.tool.get_active_connector", lambda: fake)

    raw = query_metrics.invoke(
        {
            "metrics": ["grading_jobs", "unique_file_ids", "unique_filenames"],
            "dimensions": ["day"],
            "time_range": "today",
        }
    )
    result = json.loads(raw)

    assert result["ok"] is True
    assert result["domain"] == "grading"
    assert result["period"]["preset"] == "today"
    assert result["row_count"] == 1
    assert result["data"][0]["grading_jobs"] == 80
    assert "file_distinction" in result["definitions"]
    assert result["definitions"]["file_distinction"]["unique_file_ids"].startswith("Jumlah file_id unik")


def test_query_metrics_tool_uses_cache(monkeypatch):
    fake = FakeConnector(
        [
            (
                "SELECT COUNT(*) AS grading_jobs",
                [{"grading_jobs": 80}],
            )
        ]
    )
    monkeypatch.setattr("src.semantic.tool.get_active_connector", lambda: fake)

    first = json.loads(query_metrics.invoke({"metrics": ["grading_jobs"]}))
    second = json.loads(query_metrics.invoke({"metrics": ["grading_jobs"]}))

    assert first["data"] == second["data"]
    assert len(fake.calls) == 1
