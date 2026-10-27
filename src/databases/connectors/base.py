import re
import difflib
from abc import ABC, abstractmethod
from typing import Any, Mapping, Optional
import sqlglot
from sqlglot import exp, ErrorLevel
from sqlglot.optimizer.scope import traverse_scope

FORBIDDEN_TABLES: list[str] = []

FORBIDDEN_AST_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create,
    exp.TruncateTable, exp.Merge, exp.Command, exp.Into, exp.Lock,
    exp.LoadData, exp.Set, exp.Pragma, exp.Grant, exp.Revoke, exp.PropertyEQ,
)


class DatabaseConnector(ABC):
    @property
    @abstractmethod
    def dialect(self) -> str:
        ...

    @abstractmethod
    def get_table_names(self) -> list[str]:
        ...

    @abstractmethod
    def get_table_schema(self, table_name: str) -> str:
        ...

    @abstractmethod
    def get_table_columns(self, table_name: str) -> list[str]:
        ...

    @abstractmethod
    def execute_query(self, query: str) -> str:
        ...

    @abstractmethod
    def fetch_all(
        self,
        query: str,
        params: Optional[Mapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        ...

    def _traverse_physical_tables(self, stmt: exp.Expression) -> list[exp.Table]:
        tables: list[exp.Table] = []
        for scope in traverse_scope(stmt):
            for _, source in scope.selected_sources.values():
                if isinstance(source, exp.Table):
                    tables.append(source)
        return tables

    def _check_forbidden(self, query: str) -> Optional[str]:
        if not query or not query.strip():
            return "[WARNING] Empty query provided."

        try:
            tokens = sqlglot.tokenize(query, read=self.dialect)
        except Exception as e:
            return f"[WARNING] Invalid SQL query: {e}"

        for token in tokens:
            for comment in (token.comments or []):
                c = comment.lstrip()
                if c.startswith("!") or c.startswith("M!"):
                    return "[WARNING] Executable comments are not allowed."

        try:
            statements = sqlglot.parse(query, read=self.dialect, error_level=ErrorLevel.RAISE)
        except Exception as e:
            return f"[WARNING] Invalid SQL query: {e}"

        if not statements or all(s is None for s in statements):
            return "[WARNING] Empty query provided."

        if statements[0] is None:
            return "[WARNING] Multiple statements are not allowed."

        if len(statements) == 1:
            stmt = statements[0]
        elif len(statements) == 2 and isinstance(statements[1], exp.Semicolon):
            stmt = statements[0]
        else:
            return "[WARNING] Multiple statements are not allowed."

        unnested = stmt.unnest() if hasattr(stmt, "unnest") else stmt
        if not isinstance(unnested, (exp.Select, exp.SetOperation)):
            if isinstance(unnested, exp.Command) and unnested.this:
                op_name = str(unnested.this).split()[0].upper()
                return f"[WARNING] Forbidden operation '{op_name}'. Only SELECT is allowed."
            elif hasattr(unnested, "key") and unnested.key:
                op_name = unnested.key.upper()
                if op_name == "TRUNCATETABLE":
                    op_name = "TRUNCATE"
                return f"[WARNING] Forbidden operation '{op_name}'. Only SELECT is allowed."
            return "[WARNING] Only SELECT queries are allowed."

        forbidden_node = stmt.find(*FORBIDDEN_AST_NODES)
        if forbidden_node is not None:
            if isinstance(forbidden_node, exp.Into):
                return "[WARNING] SELECT INTO is forbidden. Only standard SELECT is allowed."
            if isinstance(forbidden_node, exp.Lock):
                return "[WARNING] Locking clauses (FOR UPDATE / FOR SHARE) are forbidden."
            if isinstance(forbidden_node, exp.PropertyEQ):
                return "[WARNING] Variable assignment in queries is forbidden."
            op_name = forbidden_node.key.upper()
            if isinstance(forbidden_node, exp.Command) and forbidden_node.this:
                op_name = str(forbidden_node.this).split()[0].upper()
            elif op_name == "TRUNCATETABLE":
                op_name = "TRUNCATE"
            return f"[WARNING] Forbidden operation '{op_name}'. Only SELECT is allowed."

        try:
            tables = self._traverse_physical_tables(stmt)
        except Exception as e:
            return f"[WARNING] Query structure error: {e}"

        for table in tables:
            if self._is_table_forbidden(table):
                return "[WARNING] Query references forbidden internal tables."

        return None

    def _is_table_forbidden(self, table: exp.Table, forbidden_list: Optional[list[str]] = None) -> bool:
        if forbidden_list is None:
            forbidden_list = FORBIDDEN_TABLES
        tbl_name = table.name.lower()
        current_db = getattr(self, "_db", None)
        tbl_db = table.db.lower() if table.db else (current_db.lower() if current_db else None)

        for deny in forbidden_list:
            deny_clean = deny.strip()
            if not deny_clean:
                continue
            parts = [p.strip("`\"' ") for p in deny_clean.split(".")]
            if len(parts) == 1:
                if tbl_name == parts[0].lower():
                    return True
            elif len(parts) == 2:
                if tbl_db and tbl_db == parts[0].lower() and tbl_name == parts[1].lower():
                    return True
        return False

    def _is_table_name_forbidden(self, table_name: str, forbidden_list: Optional[list[str]] = None) -> bool:
        try:
            tbl = sqlglot.parse_one(table_name, into=exp.Table, read=self.dialect)
            if isinstance(tbl, exp.Table) and tbl.name:
                return self._is_table_forbidden(tbl, forbidden_list)
        except Exception:
            pass
        return True

    def _has_forbidden_tables(self, query: str) -> bool:
        try:
            statements = sqlglot.parse(query, read=self.dialect)
            if not statements or not statements[0]:
                return False
            for table in self._traverse_physical_tables(statements[0]):
                if self._is_table_forbidden(table):
                    return True
            return False
        except Exception:
            return True

    def _extract_tables_from_query(self, query: str) -> list[str]:
        try:
            statements = sqlglot.parse(query, read=self.dialect)
            if not statements or not statements[0]:
                return []
            stmt = statements[0]
            tables: list[str] = []
            seen: set[tuple[str, str, str]] = set()
            for source in self._traverse_physical_tables(stmt):
                if not self._is_table_forbidden(source):
                    key = (
                        source.catalog.lower() if source.catalog else "",
                        source.db.lower() if source.db else "",
                        source.name.lower(),
                    )
                    if key not in seen:
                        seen.add(key)
                        clean = exp.Table(
                            this=source.this,
                            db=source.args.get("db"),
                            catalog=source.args.get("catalog"),
                        )
                        tables.append(clean.sql(dialect=self.dialect))
            return tables
        except Exception:
            return []

    def diagnose_query_error(self, query: str, error: Exception) -> str:
        err_str = str(error)
        lines = [f"[QUERY ERROR] {err_str}"]

        col_match = (
            re.search(r"Unknown column '([^']+)'", err_str, re.IGNORECASE) or
            re.search(r'column "([^\"]+)" does not exist', err_str, re.IGNORECASE)
        )

        if col_match:
            raw_col = col_match.group(1)
            wrong_col = raw_col.split(".")[-1].strip("`\"'")
            tables = self._extract_tables_from_query(query)

            lines.append("\n[DIAGNOSTIC - COLUMN NOT FOUND]")
            for tbl in tables:
                cols = self.get_table_columns(tbl)
                if cols:
                    lines.append(f"Available columns in '{tbl}': {', '.join(cols)}")
                    matches = difflib.get_close_matches(wrong_col, cols, n=3, cutoff=0.4)
                    if matches:
                        lines.append(f"  --> Did you mean: {', '.join(matches)}?")

            lines.append("Action: Revise the query using the available columns above and re-execute.")
            return "\n".join(lines)

        tbl_match = (
            re.search(r"Table '([^']+)' doesn't exist", err_str, re.IGNORECASE) or
            re.search(r'relation "([^\"]+)" does not exist', err_str, re.IGNORECASE)
        )

        if tbl_match:
            raw_tbl = tbl_match.group(1)
            wrong_tbl = raw_tbl.split(".")[-1].strip("`\"'")
            all_tables = self.get_table_names()

            lines.append("\n[DIAGNOSTIC - TABLE NOT FOUND]")
            lines.append(f"Available tables in database: {', '.join(all_tables)}")
            matches = difflib.get_close_matches(wrong_tbl, all_tables, n=3, cutoff=0.4)
            if matches:
                lines.append(f"  --> Did you mean: {', '.join(matches)}?")
            lines.append("Action: Choose a valid table name from the list above and re-execute.")
            return "\n".join(lines)

        if "syntax" in err_str.lower():
            lines.append("\n[DIAGNOSTIC - SYNTAX ERROR]")
            lines.append(f"Target Dialect: {self.dialect.upper()}")
            if self.dialect == "mysql":
                lines.append("Hint: Ensure you are using MySQL syntax (backticks ``, IFNULL, DATE_FORMAT, etc.).")
            elif self.dialect == "postgresql":
                lines.append('Hint: Ensure you are using PostgreSQL syntax (double quotes "", COALESCE, TO_CHAR, etc.).')
            lines.append("Action: Fix the SQL syntax according to the dialect and re-execute.")
            return "\n".join(lines)

        return "\n".join(lines)
