import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import MagicMock
import pytest
from sqlalchemy import create_engine, text


@pytest.fixture
def isolated_connector_modules(monkeypatch):
    """Safely load base and mysql connectors without triggering stale database package imports."""
    connectors_dir = Path(__file__).resolve().parent.parent / "databases" / "connectors"
    pkg_db = types.ModuleType("src.databases")
    pkg_db.__path__ = [str(connectors_dir.parent)]
    monkeypatch.setitem(sys.modules, "src.databases", pkg_db)

    pkg_conn = types.ModuleType("src.databases.connectors")
    pkg_conn.__path__ = [str(connectors_dir)]
    monkeypatch.setitem(sys.modules, "src.databases.connectors", pkg_conn)

    spec_base = importlib.util.spec_from_file_location(
        "src.databases.connectors.base",
        connectors_dir / "base.py",
    )
    mod_base = importlib.util.module_from_spec(spec_base)
    monkeypatch.setitem(sys.modules, "src.databases.connectors.base", mod_base)
    spec_base.loader.exec_module(mod_base)

    spec_mysql = importlib.util.spec_from_file_location(
        "src.databases.connectors.mysql",
        connectors_dir / "mysql.py",
    )
    mod_mysql = importlib.util.module_from_spec(spec_mysql)
    monkeypatch.setitem(sys.modules, "src.databases.connectors.mysql", mod_mysql)
    spec_mysql.loader.exec_module(mod_mysql)

    # Ensure clean state of FORBIDDEN_TABLES
    original_forbidden = list(mod_base.FORBIDDEN_TABLES)
    yield mod_base, mod_mysql
    mod_base.FORBIDDEN_TABLES[:] = original_forbidden


@pytest.fixture
def offline_mysql_connector(isolated_connector_modules):
    """Instantiate MySQLConnector with an engine that raises if connect() is called."""
    mod_base, mod_mysql = isolated_connector_modules
    connector = mod_mysql.MySQLConnector.__new__(mod_mysql.MySQLConnector)
    connector._db = "mock_db"

    fake_engine = MagicMock()

    def _no_connect(*args, **kwargs):
        raise AssertionError("Database connect() was unexpectedly invoked on invalid/forbidden query!")

    fake_engine.connect.side_effect = _no_connect
    connector._engine = fake_engine
    return connector, mod_base, mod_mysql


@pytest.mark.parametrize(
    "invalid_query, expected_prefix",
    [
        ("", "[WARNING] Empty query provided."),
        ("   ", "[WARNING] Empty query provided."),
        (";", "[WARNING] Empty query provided."),
        (";;", "[WARNING] Empty query provided."),
        ("-- just a comment", "[WARNING] Empty query provided."),
        ("/* just a comment */", "[WARNING] Empty query provided."),
        ("SELECT FROM", "[WARNING] Invalid SQL query:"),
        ("SELECT * FROM", "[WARNING] Invalid SQL query:"),
        ("BROKEN SQL %%%", "[WARNING] Invalid SQL query:"),
    ],
)
def test_empty_and_broken_sql_fails_closed(offline_mysql_connector, invalid_query, expected_prefix):
    connector, _, _ = offline_mysql_connector
    res = connector.execute_query(invalid_query)
    assert res.startswith(expected_prefix)
    connector._engine.connect.assert_not_called()


@pytest.mark.parametrize(
    "multi_query",
    [
        "SELECT 1; SELECT 2",
        "SELECT 1; SELECT 2;",
        "SELECT 1;;",
        "SELECT 1; ;",
        "; SELECT 1",
        "SELECT 1; ; SELECT 2",
    ],
)
def test_multiple_statements_and_extra_semicolons_fail_closed(offline_mysql_connector, multi_query):
    connector, _, _ = offline_mysql_connector
    res = connector.execute_query(multi_query)
    assert res == "[WARNING] Multiple statements are not allowed."
    connector._engine.connect.assert_not_called()


@pytest.mark.parametrize(
    "valid_single_query",
    [
        "SELECT 1",
        "SELECT 1;",
        "SELECT 1; -- trailing line comment",
        "SELECT 1; /* trailing block comment */",
    ],
)
def test_single_statement_with_optional_semicolon_accepted(offline_mysql_connector, valid_single_query):
    connector, _, _ = offline_mysql_connector
    err = connector._check_forbidden(valid_single_query)
    assert err is None


@pytest.mark.parametrize(
    "forbidden_sql, op_name",
    [
        ("INSERT INTO users VALUES (1)", "INSERT"),
        ("UPDATE users SET x=1", "UPDATE"),
        ("DELETE FROM users", "DELETE"),
        ("DROP TABLE users", "DROP"),
        ("ALTER TABLE users ADD COLUMN c INT", "ALTER"),
        ("CREATE TABLE foo (id INT)", "CREATE"),
        ("TRUNCATE TABLE users", "TRUNCATE"),
        ("CALL my_proc()", "CALL"),
        ("SET @x = 1", "SET"),
        ("GRANT ALL ON *.* TO 'u'@'%'", "GRANT"),
        ("REVOKE ALL ON *.* FROM 'u'@'%'", "REVOKE"),
        ("SHOW TABLES", "SHOW"),
        ("DESCRIBE users", "DESCRIBE"),
        ("WITH t AS (DELETE FROM users RETURNING *) SELECT * FROM t", "DELETE"),
        ("WITH t AS (INSERT INTO users VALUES (1) RETURNING *) SELECT * FROM t", "INSERT"),
        ("WITH t AS (UPDATE users SET x=1 RETURNING *) SELECT * FROM t", "UPDATE"),
    ],
)
def test_dml_ddl_and_commands_fail_closed(offline_mysql_connector, forbidden_sql, op_name):
    connector, _, _ = offline_mysql_connector
    res = connector.execute_query(forbidden_sql)
    assert res.startswith("[WARNING] Forbidden operation")
    assert op_name in res
    connector._engine.connect.assert_not_called()


def test_dml_subquery_fails_closed(offline_mysql_connector):
    connector, _, _ = offline_mysql_connector
    res = connector.execute_query("SELECT * FROM (DELETE FROM users RETURNING *)")
    assert res.startswith("[WARNING]")
    connector._engine.connect.assert_not_called()


@pytest.mark.parametrize(
    "into_or_lock_query, expected_warning",
    [
        ("SELECT 1 INTO @v", "[WARNING] SELECT INTO is forbidden. Only standard SELECT is allowed."),
        ("SELECT 1 INTO tbl", "[WARNING] SELECT INTO is forbidden. Only standard SELECT is allowed."),
        ("SELECT 1 FROM users FOR UPDATE", "[WARNING] Locking clauses (FOR UPDATE / FOR SHARE) are forbidden."),
        ("SELECT 1 FROM users FOR SHARE", "[WARNING] Locking clauses (FOR UPDATE / FOR SHARE) are forbidden."),
        ("SELECT 1 FROM users LOCK IN SHARE MODE", "[WARNING] Locking clauses (FOR UPDATE / FOR SHARE) are forbidden."),
        ("SELECT 1 INTO OUTFILE '/tmp/out'", "[WARNING] Invalid SQL query:"),
        ("SELECT 1 INTO DUMPFILE '/tmp/dump'", "[WARNING] Invalid SQL query:"),
    ],
)
def test_select_into_and_locks_fail_closed(offline_mysql_connector, into_or_lock_query, expected_warning):
    connector, _, _ = offline_mysql_connector
    res = connector.execute_query(into_or_lock_query)
    assert res.startswith(expected_warning)
    connector._engine.connect.assert_not_called()


@pytest.mark.parametrize(
    "exec_comment_query",
    [
        "SELECT 1 /*!50000 SELECT 2 */",
        "SELECT 1 /*M!50000 SELECT 2 */",
        "SELECT 1; /*!50000 trailing */",
        "/*!50000 leading */ SELECT 1",
        "SELECT /*! middle */ 1",
    ],
)
def test_executable_comments_fail_closed(offline_mysql_connector, exec_comment_query):
    connector, _, _ = offline_mysql_connector
    res = connector.execute_query(exec_comment_query)
    assert res == "[WARNING] Executable comments are not allowed."
    connector._engine.connect.assert_not_called()


@pytest.mark.parametrize(
    "scope_error_query",
    [
        "SELECT * FROM users AS x JOIN public_data AS x ON 1=1",
        "SELECT * FROM users JOIN users ON 1=1",
    ],
)
def test_scope_analysis_fails_closed_without_connecting(offline_mysql_connector, scope_error_query):
    connector, _, _ = offline_mysql_connector
    res = connector.execute_query(scope_error_query)
    assert res.startswith("[WARNING] Query structure error:")
    connector._engine.connect.assert_not_called()


def test_root_subquery_values_rejected(offline_mysql_connector):
    connector, _, _ = offline_mysql_connector
    res1 = connector.execute_query("(VALUES (1))")
    assert res1.startswith("[WARNING]")
    connector._engine.connect.assert_not_called()

    res2 = connector.execute_query("VALUES (1)")
    assert res2.startswith("[WARNING]")
    connector._engine.connect.assert_not_called()

    # Valid parenthesized and nested reads stay allowed
    assert connector._check_forbidden("(SELECT 1)") is None
    assert connector._check_forbidden("((SELECT 1))") is None
    assert connector._check_forbidden("(SELECT 1 UNION ALL SELECT 2)") is None


@pytest.mark.parametrize(
    "var_assign_query",
    [
        "SELECT @x := 1",
        "SELECT (@x := @x + 1) AS row_num FROM users",
        "SELECT * FROM users WHERE (@x := 1) = 1",
    ],
)
def test_session_variable_assignment_rejected(offline_mysql_connector, var_assign_query):
    connector, _, _ = offline_mysql_connector
    res = connector.execute_query(var_assign_query)
    assert res == "[WARNING] Variable assignment in queries is forbidden."
    connector._engine.connect.assert_not_called()

    # Reading session variables and string literals containing := remain permitted
    assert connector._check_forbidden("SELECT @x") is None
    assert connector._check_forbidden("SELECT ':=' AS marker") is None
    assert connector._check_forbidden("SELECT * FROM users WHERE note = ':= test'") is None


@pytest.mark.parametrize(
    "allowed_query",
    [
        "SELECT 1",
        "SELECT 'DELETE' AS action, 'UPDATE' AS status FROM users",
        'SELECT * FROM users WHERE status = "DROP"',
        'SELECT "/*!50000 in string literal */" AS val',
        "SELECT '/*!50000 in string literal */' AS val",
        "SELECT 1 -- normal comment with TRUNCATE",
        "SELECT 1 /* normal comment with DROP */",
        "SELECT 1 UNION ALL SELECT 2",
        "SELECT 1 INTERSECT SELECT 1",
        "WITH cte AS (SELECT 1 AS id) SELECT * FROM cte",
        "SELECT * FROM (SELECT 1 AS id) AS sub",
    ],
)
def test_allowed_read_queries_with_literals_and_comments(offline_mysql_connector, allowed_query):
    connector, _, _ = offline_mysql_connector
    err = connector._check_forbidden(allowed_query)
    assert err is None


def test_physical_table_extraction(isolated_connector_modules):
    mod_base, mod_mysql = isolated_connector_modules
    connector = mod_mysql.MySQLConnector.__new__(mod_mysql.MySQLConnector)
    connector._db = "mock_db"

    # Nested joins
    t1 = connector._extract_tables_from_query("SELECT * FROM users JOIN orders ON 1=1")
    assert t1 == ["users", "orders"]

    # CTE table + outer table (CTE alias ignored)
    t2 = connector._extract_tables_from_query(
        "WITH cte AS (SELECT * FROM raw_data) SELECT * FROM cte JOIN extra ON 1=1"
    )
    assert t2 == ["raw_data", "extra"]

    # Subquery
    t3 = connector._extract_tables_from_query("SELECT * FROM (SELECT * FROM inner_tbl) AS sub JOIN outer_tbl ON 1=1")
    assert t3 == ["inner_tbl", "outer_tbl"]

    # Shadowed CTE aliases
    t4 = connector._extract_tables_from_query(
        "WITH cte AS (SELECT * FROM shadowed) SELECT * FROM (WITH cte AS (SELECT * FROM nested_cte) SELECT * FROM cte) AS sub JOIN cte"
    )
    assert t4 == ["shadowed", "nested_cte"]

    # Aliased physical tables (aliases stripped, clean names preserved)
    t5 = connector._extract_tables_from_query("SELECT * FROM users AS u JOIN orders AS o ON u.id = o.id")
    assert t5 == ["users", "orders"]

    # Aliased self-joins dedup by physical name
    t6 = connector._extract_tables_from_query("SELECT * FROM users u JOIN users v ON u.id = v.id")
    assert t6 == ["users"]

    # Mixed quoted/unquoted same name dedup once
    t7 = connector._extract_tables_from_query("SELECT * FROM users u JOIN `users` v ON 1=1")
    assert t7 == ["users"]

    # Case deduplication preserving first occurrence
    t8 = connector._extract_tables_from_query("SELECT * FROM USERS JOIN users ON 1=1")
    assert t8 == ["USERS"]

    # Schema qualified and quoted table names preserved without aliases
    t9 = connector._extract_tables_from_query("SELECT * FROM mydb.users AS u JOIN `otherdb`.`audit_log` AS a ON 1=1")
    assert t9 == ["mydb.users", "`otherdb`.`audit_log`"]

    # Invalid SQL returns empty list without error
    t10 = connector._extract_tables_from_query("BROKEN SQL %%%")
    assert t10 == []


def test_forbidden_table_policy(isolated_connector_modules):
    mod_base, mod_mysql = isolated_connector_modules
    connector = mod_mysql.MySQLConnector.__new__(mod_mysql.MySQLConnector)
    connector._db = "mock_db"

    fake_engine = MagicMock()
    fake_engine.connect.side_effect = AssertionError("Connection attempted on forbidden table!")
    connector._engine = fake_engine

    mod_base.FORBIDDEN_TABLES[:] = ["users", "secret_db.accounts"]

    # Exact, uppercase, backticked, and qualified in other schemas match unqualified deny
    assert connector.execute_query("SELECT * FROM users") == "[WARNING] Query references forbidden internal tables."
    connector._engine.connect.assert_not_called()
    assert connector.execute_query("SELECT * FROM USERS") == "[WARNING] Query references forbidden internal tables."
    connector._engine.connect.assert_not_called()
    assert connector.execute_query("SELECT * FROM `users`") == "[WARNING] Query references forbidden internal tables."
    connector._engine.connect.assert_not_called()
    assert connector.execute_query("SELECT * FROM otherdb.users") == "[WARNING] Query references forbidden internal tables."
    connector._engine.connect.assert_not_called()

    # Nested and CTE source access match deny
    assert connector.execute_query("SELECT * FROM (SELECT * FROM users) AS s") == "[WARNING] Query references forbidden internal tables."
    connector._engine.connect.assert_not_called()
    assert connector.execute_query("WITH cte AS (SELECT * FROM users) SELECT * FROM cte") == "[WARNING] Query references forbidden internal tables."
    connector._engine.connect.assert_not_called()

    # Qualified deny matches qualified reference only
    assert connector.execute_query("SELECT * FROM secret_db.accounts") == "[WARNING] Query references forbidden internal tables."
    connector._engine.connect.assert_not_called()
    assert connector.execute_query("SELECT * FROM `secret_db`.`accounts`") == "[WARNING] Query references forbidden internal tables."
    connector._engine.connect.assert_not_called()
    assert connector._check_forbidden("SELECT * FROM otherdb.accounts") is None
    assert not connector._has_forbidden_tables("SELECT * FROM otherdb.accounts")

    # Lookalikes, string literals, and CTE shadow aliases are allowed
    assert not connector._has_forbidden_tables("SELECT * FROM users_archive")
    assert not connector._has_forbidden_tables("SELECT 'users' AS name")
    assert not connector._has_forbidden_tables("WITH users AS (SELECT 1 AS id) SELECT * FROM users")

    # Diagnostics do not disclose forbidden table
    diag_tables = connector._extract_tables_from_query("SELECT * FROM users JOIN public_data ON 1=1")
    assert "users" not in diag_tables
    assert diag_tables == ["public_data"]


def test_qualified_denylist_blocks_unqualified_when_connector_db_matches(isolated_connector_modules):
    """Qualified denylist 'private.messages' blocks unqualified 'FROM messages' when connector._db == 'private'."""
    mod_base, mod_mysql = isolated_connector_modules
    connector = mod_mysql.MySQLConnector.__new__(mod_mysql.MySQLConnector)
    connector._db = "private"

    fake_engine = MagicMock()
    fake_engine.connect.side_effect = AssertionError("Connection attempted on forbidden table!")
    connector._engine = fake_engine

    mod_base.FORBIDDEN_TABLES[:] = ["private.messages"]

    # When connector._db == "private", unqualified messages resolves to private.messages -> blocked
    assert connector.execute_query("SELECT * FROM messages") == "[WARNING] Query references forbidden internal tables."
    connector._engine.connect.assert_not_called()
    assert connector.execute_query("SELECT * FROM `messages`") == "[WARNING] Query references forbidden internal tables."
    connector._engine.connect.assert_not_called()
    assert connector.execute_query("SELECT * FROM private.messages") == "[WARNING] Query references forbidden internal tables."
    connector._engine.connect.assert_not_called()

    # Consistent metadata listing
    assert connector.get_table_columns("messages") == []
    assert connector.get_table_columns("`messages`") == []
    assert connector.get_table_columns("private.messages") == []
    assert connector.get_table_schema("messages") == "Access to 'messages' is forbidden."

    # When connector._db is different, unqualified messages resolves to public.messages -> allowed
    connector._db = "public"
    assert not connector._has_forbidden_tables("SELECT * FROM messages")
    assert not connector._is_table_name_forbidden("messages")


def test_diagnostics_and_safe_qualified_metadata(isolated_connector_modules):
    mod_base, mod_mysql = isolated_connector_modules
    connector = mod_mysql.MySQLConnector.__new__(mod_mysql.MySQLConnector)
    connector._db = "mock_db"

    # _quote_table_name safely quotes components
    assert connector._quote_table_name("users") == "`users`"
    assert connector._quote_table_name("`users`") == "`users`"
    assert connector._quote_table_name("mydb.users") == "`mydb`.`users`"
    assert connector._quote_table_name("`mydb`.`users`") == "`mydb`.`users`"
    assert connector._quote_table_name("bad;table") is None
    assert connector._quote_table_name("select *") is None

    # Forbidden tables return empty list in get_table_columns without database query
    mod_base.FORBIDDEN_TABLES[:] = ["forbidden_tbl"]
    assert connector.get_table_columns("forbidden_tbl") == []
    assert connector.get_table_columns("`forbidden_tbl`") == []
    assert connector.get_table_columns("mydb.forbidden_tbl") == []

    # Diagnostic error formatting calls get_table_columns with clean table name and suggests close matches
    captured_calls = []

    def mock_get_columns(tbl):
        captured_calls.append(tbl)
        return ["id", "username", "email"] if "users" in tbl else []

    connector.get_table_columns = MagicMock(side_effect=mock_get_columns)
    err = Exception("Unknown column 'user_email' in 'field list'")
    diag = connector.diagnose_query_error("SELECT u.user_email FROM mydb.users AS u", err)

    assert captured_calls == ["mydb.users"]
    assert "[DIAGNOSTIC - COLUMN NOT FOUND]" in diag
    assert "Available columns in 'mydb.users': id, username, email" in diag
    assert "Did you mean: email" in diag


def test_valid_query_tsv_execution(isolated_connector_modules):
    mod_base, mod_mysql = isolated_connector_modules
    connector = mod_mysql.MySQLConnector.__new__(mod_mysql.MySQLConnector)
    connector._db = "mock_db"

    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE items (id INT, item_name TEXT)"))
            conn.execute(text("INSERT INTO items VALUES (1, 'keyboard'), (2, 'mouse')"))

        connector._engine = engine
        query = "SELECT id, item_name FROM items ORDER BY id"
        tsv = connector.execute_query(query)
        assert tsv == "id\titem_name\n1\tkeyboard\n2\tmouse"
    finally:
        engine.dispose()
