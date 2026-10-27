from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from src.databases.connectors.base import FORBIDDEN_TABLES
from src.databases.connectors.factory import connector, get_active_connector
from src.databases.connectors.mysql import MySQLConnector
from src.tools.database import get_table_detail, get_table_names, run_query


@pytest.fixture
def offline_connector(monkeypatch):
    """MySQLConnector with a fake engine that fails if a connection is opened."""
    original_forbidden = list(FORBIDDEN_TABLES)
    instance = MySQLConnector.__new__(MySQLConnector)
    instance._db = "mock_db"
    fake_engine = MagicMock()
    fake_engine.connect.side_effect = AssertionError("Unexpected database connection")
    instance._engine = fake_engine
    yield instance
    FORBIDDEN_TABLES[:] = original_forbidden


def test_factory_exposes_a_single_mysql_connector():
    assert get_active_connector() is connector
    assert connector.dialect == "mysql"
    assert connector._engine.url.drivername == "mysql+pymysql"


def test_tools_delegate_to_the_active_connector(monkeypatch):
    fake_connector = MagicMock()
    fake_connector.dialect = "mysql"
    fake_connector.execute_query.return_value = "id\n1"
    fake_connector.get_table_schema.return_value = "### TABLE items DDL"
    fake_connector.get_table_names.return_value = ["items"]
    monkeypatch.setattr("src.tools.database.get_active_connector", lambda: fake_connector)

    assert run_query.invoke({"query": "SELECT 1 AS id"}) == "id\n1"
    assert get_table_detail.invoke({"table_name": "items"}) == "### TABLE items DDL"
    assert get_table_names.invoke({}) == ["items"]

    fake_connector.execute_query.assert_called_once_with("SELECT 1 AS id")
    fake_connector.get_table_schema.assert_called_once_with("items")


def test_run_query_blocks_destructive_sql_before_connecting(offline_connector, monkeypatch):
    monkeypatch.setattr("src.tools.database.get_active_connector", lambda: offline_connector)

    result = run_query.invoke({"query": "DROP TABLE uploaded_files"})

    assert result.startswith("[WARNING] Forbidden operation 'DROP'")
    offline_connector._engine.connect.assert_not_called()


def test_query_execution_returns_tab_separated_output(offline_connector):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE items (id INT, item_name TEXT)"))
            connection.execute(text("INSERT INTO items VALUES (1, 'keyboard'), (2, 'mouse')"))

        offline_connector._engine = engine
        result = offline_connector.execute_query("SELECT id, item_name FROM items ORDER BY id")

        assert result == "id\titem_name\n1\tkeyboard\n2\tmouse"
    finally:
        engine.dispose()


def test_fetch_all_returns_parameterized_rows(offline_connector):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE items (id INT, item_name TEXT)"))
            connection.execute(text("INSERT INTO items VALUES (1, 'keyboard'), (2, 'mouse')"))

        offline_connector._engine = engine
        rows = offline_connector.fetch_all(
            "SELECT id, item_name FROM items WHERE id = :id",
            {"id": 1},
        )

        assert rows == [{"id": 1, "item_name": "keyboard"}]
    finally:
        engine.dispose()


def test_fetch_all_retries_transient_error_once(offline_connector):
    offline_connector._max_retries = 1
    bad_connection = MagicMock()
    bad_connection.__enter__.side_effect = OperationalError(
        "SELECT 1",
        {},
        Exception(2003, "timed out"),
    )
    good_connection = MagicMock()
    good_connection.__enter__.return_value = good_connection
    result = MagicMock()
    result.keys.return_value = ["id"]
    result.fetchall.return_value = [(1,)]
    good_connection.execute.return_value = result

    engine = MagicMock()
    engine.connect.side_effect = [bad_connection, good_connection]
    offline_connector._engine = engine

    with patch("src.databases.connectors.mysql.time.sleep") as sleep:
        rows = offline_connector.fetch_all("SELECT 1 AS id")

    assert rows == [{"id": 1}]
    assert engine.connect.call_count == 2
    sleep.assert_called_once()


def test_fetch_all_does_not_retry_non_transient_error(offline_connector):
    offline_connector._max_retries = 1
    bad_connection = MagicMock()
    bad_connection.__enter__.side_effect = OperationalError(
        "SELECT nope",
        {},
        Exception(1064, "syntax error"),
    )
    engine = MagicMock()
    engine.connect.return_value = bad_connection
    offline_connector._engine = engine

    with pytest.raises(OperationalError):
        offline_connector.fetch_all("SELECT nope")

    assert engine.connect.call_count == 1


def test_fetch_all_blocks_destructive_sql_before_connecting(offline_connector):
    with pytest.raises(ValueError, match="Forbidden operation"):
        offline_connector.fetch_all("DELETE FROM items")
    offline_connector._engine.connect.assert_not_called()


def test_table_listing_filters_forbidden_tables(offline_connector):
    FORBIDDEN_TABLES[:] = ["internal_audit"]
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.fetchall.return_value = [
        ("uploaded_files",),
        ("internal_audit",),
    ]
    offline_connector._engine = engine

    assert offline_connector.get_table_names() == ["uploaded_files"]


def test_table_schema_includes_ddl_and_sample_rows(offline_connector):
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    ddl_result = MagicMock()
    ddl_result.fetchone.return_value = ("uploaded_files", "CREATE TABLE uploaded_files (file_id TEXT)")
    sample_result = MagicMock()
    sample_result.keys.return_value = ["file_id", "original_filename"]
    sample_result.fetchall.return_value = [("fav-001", "peserta.parquet")]
    connection.execute.side_effect = [ddl_result, sample_result]
    offline_connector._engine = engine

    schema = offline_connector.get_table_schema("uploaded_files")

    assert schema.startswith("### TABLE uploaded_files DDL")
    assert "CREATE TABLE uploaded_files" in schema
    assert "### SAMPLE DATA" in schema
    assert "fav-001\tpeserta.parquet" in schema


def test_forbidden_table_metadata_is_rejected_without_connecting(offline_connector):
    FORBIDDEN_TABLES[:] = ["conversations"]

    assert offline_connector.get_table_schema("conversations") == "Access to 'conversations' is forbidden."
    assert offline_connector.get_table_columns("conversations") == []
    offline_connector._engine.connect.assert_not_called()
