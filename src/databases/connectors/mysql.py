import os
import time
from typing import Any, Mapping, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from loguru import logger
import sqlglot
from sqlglot import exp

from src.databases.connectors.base import DatabaseConnector

_TRANSIENT_DB_CODES = {2003, 2006, 2013, 2014, 2045, 2055}


class MySQLConnector(DatabaseConnector):

    def __init__(self, host: str, port: int, database: str, username: str, password: str):
        self._db = database
        connect_timeout = max(1, int(os.getenv("DB_CONNECT_TIMEOUT", "5")))
        read_timeout = max(1, int(os.getenv("DB_READ_TIMEOUT", "15")))
        self._max_retries = max(0, int(os.getenv("DB_MAX_RETRIES", "2")))
        # Rows run_query hands to the model; more would only fill its context.
        self._max_rows = max(1, int(os.getenv("DB_MAX_ROWS", "200")))
        url = URL.create(
            drivername="mysql+pymysql",
            username=username,
            password=password,
            host=host,
            port=port,
            database=database,
        )
        self._engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": connect_timeout,
                "read_timeout": read_timeout,
                "write_timeout": read_timeout,
            },
        )
        logger.info(f"MySQLConnector initialised: {username}@{host}:{port}/{database}")

    @property
    def dialect(self) -> str:
        return "mysql"

    def _quote_table_name(self, table_name: str) -> Optional[str]:
        try:
            tbl = sqlglot.parse_one(table_name, into=exp.Table, read=self.dialect)
            if not isinstance(tbl, exp.Table) or not tbl.name:
                return None
            parts = []
            if tbl.catalog:
                parts.append(f"`{tbl.catalog.replace('`', '``')}`")
            if tbl.db:
                parts.append(f"`{tbl.db.replace('`', '``')}`")
            parts.append(f"`{tbl.name.replace('`', '``')}`")
            return ".".join(parts)
        except Exception:
            return None

    def get_table_names(self) -> list[str]:
        with self._engine.connect() as conn:
            rows = conn.execute(text("SHOW TABLES;")).fetchall()
        return [r[0] for r in rows if not self._is_table_name_forbidden(r[0])]

    def get_table_columns(self, table_name: str) -> list[str]:
        if self._is_table_name_forbidden(table_name):
            return []
        quoted = self._quote_table_name(table_name)
        if not quoted:
            return []
        try:
            with self._engine.connect() as conn:
                cur = conn.execute(text(f"DESCRIBE {quoted}"))
                return [row[0] for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"MySQLConnector.get_table_columns error: {e}")
            return []

    def get_table_schema(self, table_name: str) -> str:
        if self._is_table_name_forbidden(table_name):
            return f"Access to '{table_name}' is forbidden."

        quoted = self._quote_table_name(table_name)
        if not quoted:
            return f"Invalid table name '{table_name}'."

        try:
            with self._engine.connect() as conn:
                ddl = conn.execute(text(f"SHOW CREATE TABLE {quoted}")).fetchone()[1]
                cur = conn.execute(text(f"SELECT * FROM {quoted} LIMIT 3"))
                cols = list(cur.keys())
                rows = cur.fetchall()
        except Exception as e:
            logger.error(f"MySQLConnector.get_table_schema error: {e}")
            return f"[ERROR] {e}"

        sample = "\t".join(cols)
        for row in rows:
            sample += "\n" + "\t".join(str(c) for c in row)
        return f"### TABLE {table_name} DDL\n{ddl}\n\n### SAMPLE DATA\n{sample}"

    @staticmethod
    def _is_transient_error(exc: Exception) -> bool:
        orig = getattr(exc, "orig", exc)
        args = getattr(orig, "args", ())
        code = args[0] if args and isinstance(args[0], int) else None
        if code in _TRANSIENT_DB_CODES:
            return True
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "timed out",
                "lost connection",
                "server has gone away",
                "deadlock",
            )
        )

    def _execute(
        self,
        query: str,
        params: Optional[Mapping[str, Any]] = None,
    ) -> tuple[list[str], list[Any]]:
        max_retries = getattr(self, "_max_retries", 0)
        for attempt in range(max_retries + 1):
            try:
                with self._engine.connect() as conn:
                    cur = conn.execute(text(query), dict(params or {}))
                    columns = list(cur.keys())
                    rows = cur.fetchall()
                return columns, rows
            except Exception as exc:
                if attempt >= max_retries or not self._is_transient_error(exc):
                    raise
                delay = 0.5 * (2**attempt)
                logger.warning(
                    f"MySQLConnector transient error on attempt {attempt + 1}; "
                    f"retrying in {delay}s: {exc}"
                )
                time.sleep(delay)
        raise RuntimeError("unreachable")

    def _limited(self, query: str, max_rows: int) -> str:
        """The query with LIMIT max_rows + 1 when it has no LIMIT of its own, so StarRocks
        stops early; the extra row tells whether the result was cut."""
        try:
            stmt = sqlglot.parse_one(query, read=self.dialect)
        except Exception:
            return query
        if stmt is None or stmt.args.get("limit"):
            return query
        # On a new line, so a trailing -- comment cannot swallow it.
        return f"{query.rstrip().rstrip(';').rstrip()}\nLIMIT {max_rows + 1}"

    def execute_query(self, query: str) -> str:
        err = self._check_forbidden(query)
        if err:
            return err
        if self._has_forbidden_tables(query):
            return "[WARNING] Query references forbidden internal tables."
        max_rows = getattr(self, "_max_rows", 200)
        try:
            cols, rows = self._execute(self._limited(query, max_rows))
            result = "\t".join(cols)
            for row in rows[:max_rows]:
                result += "\n" + "\t".join(str(c) for c in row)
            if len(rows) > max_rows:
                result += (f"\n[TRUNCATED] Only the first {max_rows} rows are shown. Aggregate "
                           f"(COUNT/SUM/GROUP BY) or filter further for complete figures.")
            return result
        except Exception as e:
            logger.error(f"MySQLConnector.execute_query error: {e}")
            return self.diagnose_query_error(query, e)

    def fetch_all(
        self,
        query: str,
        params: Optional[Mapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        err = self._check_forbidden(query)
        if err:
            raise ValueError(err)
        if self._has_forbidden_tables(query):
            raise ValueError("[WARNING] Query references forbidden internal tables.")
        try:
            columns, rows = self._execute(query, params)
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"MySQLConnector.fetch_all error: {e}")
            raise
