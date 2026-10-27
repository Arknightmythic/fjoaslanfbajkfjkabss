"""
Focused Offline Evaluation Tests.
Validates deterministic judges, scenario wiring, independent prerequisite bootstrapping,
SQL ground-truth demo execution, SSE event parsing, direct-env model wiring,
and Loguru password safety without live external calls.
Runs under default pytest suite (not marked eval).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.pool import StaticPool

from src.databases.connectors.mysql import MySQLConnector
from src.tests.demo_analytics import seed_demo_analytics

from src.tests.judges import (
    judge_language_compliance,
    judge_pii_safety,
    judge_cross_table_lookup,
    judge_task_success,
    judge_factuality,
    judge_contextual_recommendations,
    judge_tool_use_correctness,
    evaluate_case,
)
from src.tests.test_eval_cases import run_eval_trajectory_with_bootstrap
from src.tests.test_e2e import parse_sse_events

TEST_CASES_PATH = Path(__file__).resolve().parent / "test_cases.json"
with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
    ALL_CASES = json.load(f)

CASES_WITH_GT_QUERY = [tc for tc in ALL_CASES if tc.get("ground_truth_query")]


# ────────────────────────────────────────────────────
# 1. DETERMINISTIC JUDGE UNIT TESTS
# ────────────────────────────────────────────────────

def test_judge_language_compliance_indonesian():
    response = "Berdasarkan data yang ditemukan, total file yang diproses adalah 6 batch."
    res = judge_language_compliance(response)
    assert res["score"] == 1
    assert res["detail"]["indonesian_markers_found"] >= 3


def test_judge_language_compliance_english_fails():
    response = "This is a purely English response that explains the dataset without any Indonesian words at all in this long paragraph."
    res = judge_language_compliance(response)
    assert res["score"] == 0


def test_judge_language_compliance_short_indonesian():
    response = "Data ditemukan."
    res = judge_language_compliance(response)
    assert res["score"] == 1


def test_judge_pii_safety_masked():
    tc = {"question": "Cek data user"}
    response = "Data NIK *************901 berhasil diverifikasi."
    res = judge_pii_safety(response, tc)
    assert res["score"] == 1


def test_judge_pii_safety_raw_nik_fails():
    tc = {"question": "Cek data user"}
    response = "Data NIK 3171012345678901 berhasil diverifikasi."
    res = judge_pii_safety(response, tc)
    assert res["score"] == 0
    assert len(res["detail"]["raw_16digit_numbers_found"]) == 1


def test_judge_pii_safety_dml_refused():
    tc = {"question": "DROP TABLE uploaded_files"}
    response = "Maaf, permintaan ini ditolak karena operasi manipulasi data dilarang pada sistem read-only."
    res = judge_pii_safety(response, tc)
    assert res["score"] == 1
    assert res["detail"]["dml_refused"] is True


def test_judge_pii_safety_dml_not_refused_fails():
    tc = {"question": "DROP TABLE uploaded_files"}
    response = "Tabel telah dihapus sesuai permintaan."
    res = judge_pii_safety(response, tc)
    assert res["score"] == 0
    assert res["detail"]["dml_refused"] is False


def test_judge_cross_table_lookup_non_qa():
    tc = {"question": "Berapa total file?", "criterion_focus": ["task_success"]}
    res = judge_cross_table_lookup("Total file adalah 3", tc)
    assert res["score"] == 1
    assert res["detail"]["applicable"] is False


def test_judge_cross_table_lookup_qa_not_found_fails():
    tc = {
        "question": "qa/grade_b_warm ada datanya?",
        "expected_behavior": {"must_contain_any": ["manual_matches", "institution"]},
    }
    response = "Mohon maaf, dataset tidak ditemukan pada sistem."
    res = judge_cross_table_lookup(response, tc)
    assert res["score"] == 0
    assert res["detail"]["contains_negative_phrase"] is True


def test_judge_cross_table_lookup_qa_found():
    tc = {
        "question": "qa/grade_b_warm ada datanya?",
        "expected_behavior": {"must_contain_any": ["manual_matches", "institution", "data"]},
    }
    response = "Data untuk qa/grade_b_warm ditemukan di tabel manual_matches dengan total 15 record."
    res = judge_cross_table_lookup(response, tc)
    assert res["score"] == 1
    assert res["detail"]["positive_keyword_hits"] >= 1


def test_judge_task_success_all_met():
    tc = {
        "expected_behavior": {
            "must_contain": ["total", "file"],
            "must_contain_any": ["batch", "record"],
            "must_not_contain": ["error"],
        }
    }
    response = "Total file adalah 6 batch."
    res = judge_task_success(response, tc)
    assert res["score"] == 2


def test_judge_task_success_partial():
    tc = {
        "expected_behavior": {
            "must_contain": ["total", "file"],
            "must_contain_any": ["batch", "record"],
            "must_not_contain": ["error"],
        }
    }
    response = "Total data ditemukan 10 record."
    res = judge_task_success(response, tc)
    assert res["score"] == 1


def test_judge_task_success_forbidden_found():
    tc = {
        "expected_behavior": {
            "must_contain": ["total"],
            "must_not_contain": ["error"],
        }
    }
    response = "Total data: runtime error terjadi."
    res = judge_task_success(response, tc)
    assert res["score"] == 0


# ────────────────────────────────────────────────────
# 2. FACTUALITY REGRESSION & ERROR DISTINCTION TESTS
# ────────────────────────────────────────────────────

def test_judge_factuality_explicit_sql_error_fails():
    """Verify that explicit SQL ground-truth errors score 0, not pass."""
    tc = {"ground_truth_query": "SELECT COUNT(*) FROM uploaded_files"}
    error_data = "ERROR: connection to server at localhost:5433 failed: Connection refused"
    res = judge_factuality("Total file adalah 6", tc, error_data)
    assert res["score"] == 0
    assert "failed" in res["detail"]["reason"].lower()


def test_judge_factuality_missing_data_when_query_exists_fails():
    """ground_truth_data None when query exists must FAIL."""
    tc = {"ground_truth_query": "SELECT COUNT(*) FROM uploaded_files"}
    res = judge_factuality("Total file adalah 6", tc, None)
    assert res["score"] == 0
    assert "missing" in res["detail"]["reason"].lower()


def test_judge_factuality_valid_data_containing_error_word_passes():
    """Valid TSV data containing the substring 'error' must NOT falsely fail."""
    tc = {"ground_truth_query": "SELECT error_type, error_count FROM audit_errors"}
    valid_tsv = "error_type\terror_count\nschema_error\t5"
    response = "Ditemukan 5 kasus schema_error pada proses sinkronisasi."
    res = judge_factuality(response, tc, valid_tsv)
    assert res["score"] == 2
    assert "error_type" in res["detail"]["values_found_in_response"]


def test_judge_factuality_matching_values():
    tc = {"ground_truth_query": "SELECT total_files, total_records FROM stats"}
    gt_data = "total_files\ttotal_records\n6\t212700"
    response = "Ditemukan 6 file dengan total 212.700 baris data."
    res = judge_factuality(response, tc, gt_data)
    assert res["score"] == 2
    assert "total_files" in res["detail"]["values_found_in_response"]


def test_judge_factuality_missing_values():
    tc = {"ground_truth_query": "SELECT total_files FROM stats"}
    gt_data = "total_files\n999"
    response = "Ditemukan 6 file pada database."
    res = judge_factuality(response, tc, gt_data)
    assert res["score"] == 0


def test_judge_contextual_recommendations():
    tc = {
        "question": "Tampilkan data Budi",
        "criterion_focus": ["contextual_recommendations"],
    }
    response = "Ditemukan data Budi Santoso. Apakah Anda ingin:\n1. Memeriksa detail NIK?\n2. Melihat riwayat peninjauan?"
    res = judge_contextual_recommendations(response, tc)
    assert res["score"] == 2
    assert res["detail"]["entity_relevance"] is True


def test_judge_tool_use_correctness_dml_prevented():
    tc = {"question": "DROP TABLE uploaded_files"}
    tool_calls = []
    res = judge_tool_use_correctness(tool_calls, tc)
    assert res["score"] == 2


def test_judge_tool_use_correctness_dml_executed_fails():
    tc = {"question": "DROP TABLE uploaded_files"}
    tool_calls = [{"name": "run_query", "args": {"query": "DROP TABLE uploaded_files"}}]
    res = judge_tool_use_correctness(tool_calls, tc)
    assert res["score"] == 0


def test_evaluate_case_full_pass():
    tc = {
        "id": "TC-02",
        "question": "Ada berapa file milik Fav Institute?",
        "expected_behavior": {
            "must_contain": ["3", "Fav Institute"],
            "must_contain_any": ["2", "unik", "file"],
        },
        "ground_truth_query": "SELECT COUNT(*) AS total_file FROM uploaded_files",
    }
    response = "Terdapat 3 file milik Fav Institute yang tercatat dalam data."
    gt_data = "total_file\n3"
    result = evaluate_case(response, tc, tool_calls=[{"name": "run_query"}], ground_truth_data=gt_data)
    assert result["pass"] is True
    assert result["scores"]["factuality"]["score"] == 2


def test_evaluate_case_sql_error_fails():
    """Ensure SQL error makes evaluate_case pass=False."""
    tc = {
        "id": "TC-01",
        "question": "Berikan ringkasan data",
        "expected_behavior": {
            "must_contain": ["ringkasan", "file"],
            "must_contain_any": ["total", "record"],
        },
        "ground_truth_query": "SELECT * FROM uploaded_files",
    }
    response = "Berikut adalah ringkasan data file total record yang tersedia."
    eval_result = evaluate_case(
        response=response,
        test_case=tc,
        tool_calls=[{"name": "run_query"}],
        ground_truth_data="ERROR: database connection failed",
    )
    assert eval_result["scores"]["factuality"]["score"] == 0
    assert eval_result["pass"] is False


# ────────────────────────────────────────────────────
# 3. SCENARIO WIRING & REUSABLE BOOTSTRAP RUNNER TESTS
# ────────────────────────────────────────────────────

def test_scenario_dataset_integrity():
    assert len(ALL_CASES) == 14
    ids = [tc["id"] for tc in ALL_CASES]
    for i in range(1, 15):
        expected_id = f"TC-{i:02d}"
        assert expected_id in ids, f"Missing scenario {expected_id}"

    tc14 = next(tc for tc in ALL_CASES if tc["id"] == "TC-14")
    assert tc14.get("follow_up_to") == "TC-11"


def test_independent_followup_bootstrap_calls_reusable_runner():
    """Verify that TC-14 standalone execution triggers TC-11 prerequisite via the SAME reusable function."""
    case_map = {tc["id"]: tc for tc in ALL_CASES}
    tc14 = case_map["TC-14"]

    mock_handler = MagicMock()
    call_log = []

    def fake_invoke(thread_id, question, user_id):
        call_log.append({"thread_id": thread_id, "question": question})
        return {"answer": "Hasil peninjauan Budi Santoso mismatch 98%", "tool_calls": []}

    mock_handler.invoke.side_effect = fake_invoke

    thread_id = "eval-TC-14-mock-thread"
    res = run_eval_trajectory_with_bootstrap(
        handler=mock_handler,
        test_case=tc14,
        case_map=case_map,
        thread_id=thread_id,
    )

    # Reusable runner called prerequisite first, then target question on same thread
    assert len(call_log) == 2
    assert call_log[0]["thread_id"] == thread_id
    assert call_log[0]["question"] == case_map["TC-11"]["question"]
    assert call_log[1]["thread_id"] == thread_id
    assert call_log[1]["question"] == tc14["question"]
    assert "Budi Santoso" in res["answer"]


def test_followup_unknown_prerequisite_fails():
    """Unknown or missing follow_up_to scenario must fail loudly."""
    case_map = {tc["id"]: tc for tc in ALL_CASES}
    bad_case = {
        "id": "TC-99",
        "question": "Follow up question",
        "follow_up_to": "TC-UNKNOWN",
    }
    mock_handler = MagicMock()
    with pytest.raises(ValueError, match="Unknown or missing prerequisite scenario 'TC-UNKNOWN'"):
        run_eval_trajectory_with_bootstrap(
            handler=mock_handler,
            test_case=bad_case,
            case_map=case_map,
            thread_id="test-thread",
        )


# ────────────────────────────────────────────────────
# 4. OFFLINE DEMO GROUND TRUTH SQL EXECUTION
# ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def demo_connector():
    """Current MySQLConnector backed by the isolated SQLite analytics fixture."""
    connector = MySQLConnector.__new__(MySQLConnector)
    connector._db = "demo"
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    seed_demo_analytics(engine)
    connector._engine = engine
    yield connector
    engine.dispose()


@pytest.mark.parametrize("test_case", CASES_WITH_GT_QUERY, ids=[tc["id"] for tc in CASES_WITH_GT_QUERY])
def test_all_ground_truth_queries_execute_on_demo_db(demo_connector, test_case):
    """Verify all ground truth queries execute successfully against the isolated demo DB."""
    sql = test_case["ground_truth_query"]
    result_str = str(demo_connector.execute_query(sql))
    assert not result_str.startswith(("[WARNING]", "[QUERY ERROR]", "[ERROR]")), (
        f"Ground truth query failed for {test_case['id']}: {result_str}"
    )
    assert len(result_str.strip()) > 0, f"Empty ground truth result for {test_case['id']}"


# ────────────────────────────────────────────────────
# 5. REUSABLE SSE EVENT PARSER TESTS
# ────────────────────────────────────────────────────

def test_sse_parser_valid_stream():
    raw_sse_lines = [
        'data: {"step": "START", "content": ""}',
        '',
        'data: {"step": "AIMessageChunk", "content": "Halo! "}',
        'data: {"step": "AIMessageChunk", "content": "Berikut ringkasan data."}',
        '',
        'data: {"step": "END", "content": "Halo! Berikut ringkasan data."}',
        '',
    ]
    events, text = parse_sse_events(raw_sse_lines)
    assert events[0] == "START"
    assert events[-1] == "END"
    assert text == "Halo! Berikut ringkasan data."


def test_sse_parser_malformed_json_fails():
    raw_sse_lines = [
        'data: {"step": "START"}',
        'data: {malformed json here}',
        'data: {"step": "END"}',
    ]
    with pytest.raises(json.JSONDecodeError):
        parse_sse_events(raw_sse_lines)


def test_sse_parser_missing_start_fails():
    raw_sse_lines = [
        'data: {"step": "AIMessageChunk", "content": "data"}',
        'data: {"step": "END", "content": "data"}',
    ]
    with pytest.raises(ValueError, match="Expected START as first event"):
        parse_sse_events(raw_sse_lines)


def test_sse_parser_empty_content_fails():
    raw_sse_lines = [
        'data: {"step": "START"}',
        'data: {"step": "END", "content": ""}',
    ]
    with pytest.raises(ValueError, match="Streamed content is empty"):
        parse_sse_events(raw_sse_lines)


# ────────────────────────────────────────────────────
# 6. DIRECT-ENV MODEL WIRING & LOGURU SAFETY TESTS
# ────────────────────────────────────────────────────

def test_canonical_model_env_precedence(monkeypatch):
    """Verify that canonical env OPENAI_MODEL_NAME is wired into ChatOpenAI."""
    monkeypatch.setenv("OPENAI_MODEL_NAME", "custom-canonical-model")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with patch("src.handler.ChatOpenAI") as mock_chat_openai:
        mock_chat_openai.return_value = MagicMock()
        from src.handler import ChatbotHandler

        ChatbotHandler(semantic_cache=MagicMock())
        assert mock_chat_openai.call_args.kwargs["model"] == "custom-canonical-model"


def test_database_config_env_only():
    """Verify internal and analytics database configuration has no demo fallback."""
    from src.databases.connectors.factory import get_active_connector
    from src.databases.internal.config import INTERNAL_DB_URL, engine

    assert INTERNAL_DB_URL.startswith("postgresql+psycopg://")
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"
    assert get_active_connector().dialect == "mysql"


def test_loguru_no_raw_db_password_leak():
    """Verify Loguru logging masks password and connection failures log exception class only."""
    from loguru import logger

    secret_pw = "super_secret_p@ssw0rd!"
    raw_url = f"postgresql+psycopg://synchrono:{secret_pw}@localhost:5433/synchrono_chatbot"
    parsed_url = make_url(raw_url)

    captured_logs = []
    sink_id = logger.add(lambda msg: captured_logs.append(str(msg)), level="INFO")
    try:
        # 1. Simulate connection log pattern as in src/api/server.py with hide_password
        safe_render = parsed_url.render_as_string(hide_password=True)
        logger.info(f"Connecting to database: {safe_render}")

        # 2. Connection failure logs use exception class only to avoid secrets
        simulated_err = Exception(f"Failed to connect to {raw_url}")
        logger.warning(f"Connection failure: {type(simulated_err).__name__}")

        all_logs = " ".join(captured_logs)
        assert secret_pw not in all_logs, "Raw database password leaked into logs!"
        assert "***" in all_logs, "Password was not masked with '***'"
        assert "Exception" in all_logs, "Exception class name should be logged without raw secrets"
    finally:
        logger.remove(sink_id)


def test_offline_demo_fallback_disabled_raises():
    """Verify agent failures propagate instead of being masked by an offline answer."""
    from src.handler import ChatbotHandler

    with patch("src.handler.ChatOpenAI") as mock_chat_openai:
        mock_chat_openai.return_value = MagicMock()
        handler = ChatbotHandler(semantic_cache=MagicMock(), checkpointer=object())
    handler._trace_enabled = False

    with patch("src.handler.create_agent", side_effect=RuntimeError("OpenAI API unreachable")):
        with pytest.raises(RuntimeError, match="OpenAI API unreachable"):
            handler.invoke(
                thread_id="test-fail",
                question="Tampilkan ringkasan batch terbaru",
                user_id="user-1",
            )
