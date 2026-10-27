import json

import pytest

from src.prompts import SYNCHRONO_AGENT_SYSTEM_PROMPT
from src.tools import status


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


def _result(raw):
    return json.loads(raw)


@pytest.fixture
def fake_connector(monkeypatch):
    def install(responses):
        connector = FakeConnector(responses)
        monkeypatch.setattr(status, "get_active_connector", lambda: connector)
        return connector

    status._clear_anomaly_cache()
    yield install
    status._clear_anomaly_cache()


def test_grading_status_summary_returns_totals(fake_connector):
    connector = fake_connector(
        [
            (
                "FROM syncrono_service_grading_jobs",
                [
                    {"status": "COMPLETED", "job_count": 61, "total_rows": 63369},
                    {"status": "FAILED", "job_count": 4, "total_rows": 39644},
                ],
            )
        ]
    )

    payload = _result(status.get_grading_status_summary.invoke({}))

    assert payload["ok"] is True
    assert payload["data"]["total_jobs"] == 65
    assert payload["data"]["total_rows"] == 103013
    assert connector.calls[0]["params"] == {}


def test_matching_status_summary_returns_counts(fake_connector):
    fake_connector(
        [
            (
                "FROM syncrono_portal_matching_jobs",
                [
                    {"status": "MATCHING", "job_count": 27},
                    {"status": "FAILED", "job_count": 9},
                ],
            )
        ]
    )

    payload = _result(status.get_matching_status_summary.invoke({}))

    assert payload["ok"] is True
    assert payload["data"]["total_jobs"] == 36
    assert len(payload["data"]["status_counts"]) == 2


def test_failed_matching_jobs_always_selects_recorded_reason(fake_connector):
    connector = fake_connector(
        [
            (
                "FROM syncrono_portal_matching_jobs",
                [
                    {
                        "id": "job-1",
                        "status": "FAILED",
                        "last_error": "S3 Seaweed connection timeout during download.",
                        "failed_at": "2026-10-26T10:00:00+07:00",
                    }
                ],
            )
        ]
    )

    payload = _result(status.get_failed_matching_jobs.invoke({"limit": 20}))

    query = connector.calls[0]["query"]
    assert "last_error" in query
    assert "failed_at" in query
    assert payload["ok"] is True
    assert payload["data"]["jobs"][0]["last_error"] == "S3 Seaweed connection timeout during download."
    assert payload["data"]["filters"]["statuses"] == ["FAILED"]


def test_failed_matching_jobs_can_include_cancelled_and_clamps_limit(fake_connector):
    connector = fake_connector([("FROM syncrono_portal_matching_jobs", [])])

    payload = _result(
        status.get_failed_matching_jobs.invoke(
            {"limit": 999, "include_cancelled": True}
        )
    )

    assert payload["ok"] is True
    assert connector.calls[0]["params"]["limit"] == 50
    assert "status IN ('FAILED', 'CANCELLED')" in connector.calls[0]["query"]


def test_file_status_includes_matching_error(fake_connector):
    connector = fake_connector(
        [
            (
                "FROM syncrono_service_grading_jobs",
                [
                    {
                        "job_id": "grade-1",
                        "file_id": "file-1",
                        "filename": "uji_master_D.csv",
                        "grading_phase": "AFTER",
                        "status": "COMPLETED",
                    }
                ],
            ),
            (
                "FROM syncrono_service_grading_results",
                [
                    {
                        "job_id": "grade-1",
                        "phase": "AFTER",
                        "grade_letter": "D",
                        "quality_score": 48,
                    }
                ],
            ),
            (
                "FROM syncrono_portal_matching_jobs",
                [
                    {
                        "id": "match-1",
                        "status": "FAILED",
                        "last_error": "ValueError: Berkas belum pernah digrading.",
                        "failed_at": "2026-10-26T10:00:00+07:00",
                    }
                ],
            ),
        ]
    )

    payload = _result(
        status.get_file_status.invoke({"identifier": "uji_master_D.csv"})
    )

    assert payload["ok"] is True
    assert payload["data"]["found"] is True
    assert payload["data"]["grading_result"]["grade_letter"] == "D"
    assert payload["data"]["matching_job"]["last_error"].startswith("ValueError")
    assert connector.calls[2]["params"]["file_id"] == "file-1"


def test_file_status_rejects_empty_identifier(fake_connector):
    connector = fake_connector([])

    payload = _result(status.get_file_status.invoke({"identifier": "   "}))

    assert payload["ok"] is False
    assert connector.calls == []


def test_batch_status_summary_returns_batches_and_parts(fake_connector):
    fake_connector(
        [
            (
                "FROM syncrono_service_batches",
                [{"status": "DONE", "batch_count": 18, "part_count": 188, "total_rows": 45506}],
            ),
            (
                "FROM syncrono_service_batch_parts",
                [{"status": "DONE", "part_count": 188, "row_span": 45506}],
            ),
        ]
    )

    payload = _result(status.get_batch_status_summary.invoke({}))

    assert payload["ok"] is True
    assert payload["data"]["batches"][0]["batch_count"] == 18
    assert payload["data"]["parts"][0]["part_count"] == 188


def test_anomaly_summary_computes_rate_and_top_types(fake_connector):
    fake_connector(
        [
            (
                "COUNT(*) AS total_rows",
                [{"total_rows": 7543, "anomaly_rows": 6803}],
            ),
            (
                "GROUP BY anomaly_type",
                [{"anomaly_type": "NIK_KECAMATAN_INVALID", "row_count": 3996}],
            ),
        ]
    )

    payload = _result(status.get_anomaly_summary.invoke({}))

    assert payload["ok"] is True
    assert payload["data"]["anomaly_rate_percent"] == 90.19
    assert payload["data"]["top_anomaly_types"][0]["row_count"] == 3996


def test_anomaly_summary_falls_back_to_enriched_for_file(fake_connector):
    fake_connector(
        [
            (
                "FROM syncrono_kl_records",
                [{"total_rows": 0, "anomaly_rows": 0}],
            ),
            (
                "FROM syncrono_kl_enriched\n                WHERE file_id",
                [{"total_rows": 9911, "anomaly_rows": 9911}],
            ),
            (
                "GROUP BY anomaly_type",
                [{"anomaly_type": "NIK_KECAMATAN_INVALID", "row_count": 9911}],
            ),
        ]
    )

    payload = _result(
        status.get_anomaly_summary.invoke({"file_id": "pop_1792990111913_lnk7o"})
    )

    assert payload["ok"] is True
    assert payload["data"]["source_table"] == "syncrono_kl_enriched"
    assert payload["data"]["total_rows"] == 9911
    assert payload["data"]["anomaly_rows"] == 9911
    assert payload["data"]["anomaly_rate_percent"] == 100.0


def test_anomaly_summary_reuses_ttl_cache(fake_connector):
    connector = fake_connector(
        [
            (
                "COUNT(*) AS total_rows",
                [{"total_rows": 7545, "anomaly_rows": 6805}],
            ),
            (
                "GROUP BY anomaly_type",
                [{"anomaly_type": "NIK_KECAMATAN_INVALID", "row_count": 3996}],
            ),
        ]
    )

    first = _result(status.get_anomaly_summary.invoke({}))
    second = _result(status.get_anomaly_summary.invoke({}))

    assert first["data"]["total_rows"] == 7545
    assert second["data"]["total_rows"] == 7545
    assert len(connector.calls) == 2


def test_prompt_requires_typed_status_tools_and_failure_reason_columns():
    assert "get_failed_matching_jobs" in SYNCHRONO_AGENT_SYSTEM_PROMPT
    assert "get_file_status" in SYNCHRONO_AGENT_SYSTEM_PROMPT
    assert "`last_error`" in SYNCHRONO_AGENT_SYSTEM_PROMPT
    assert "`failed_at`" in SYNCHRONO_AGENT_SYSTEM_PROMPT
    assert "Never claim that a column, reason, or record is absent" in SYNCHRONO_AGENT_SYSTEM_PROMPT


def test_latest_grading_jobs_returns_grade(fake_connector):
    fake_connector(
        [
            (
                "FROM syncrono_service_grading_jobs g",
                [
                    {
                        "job_id": "job-1",
                        "filename": "uji_master_D.csv",
                        "grade_letter": "D",
                        "quality_score": 48,
                    }
                ],
            )
        ]
    )

    payload = _result(status.get_latest_grading_jobs.invoke({"limit": 5}))

    assert payload["ok"] is True
    assert payload["data"]["jobs"][0]["grade_letter"] == "D"
