from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from loguru import logger
import sqlglot
from sqlglot import exp

from src.databases.connectors.base import DatabaseConnector


class MySQLConnector(DatabaseConnector):

    def __init__(self, host: str, port: int, database: str, username: str, password: str):
        self._db = database
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

    def execute_query(self, query: str) -> str:
        err = self._check_forbidden(query)
        if err:
            return err
        if self._has_forbidden_tables(query):
            return "[WARNING] Query references forbidden internal tables."
        try:
            with self._engine.connect() as conn:
                cur = conn.execute(text(query))
                cols = list(cur.keys())
                rows = cur.fetchall()
            result = "\t".join(cols)
            for row in rows:
                result += "\n" + "\t".join(str(c) for c in row)
            return result
        except Exception as e:
            logger.error(f"MySQLConnector.execute_query error: {e}")
            return self.diagnose_query_error(query, e)
