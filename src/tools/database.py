from langchain_core.tools import tool
from loguru import logger

from src.databases import get_active_connector

@tool
def run_query(query: str) -> str:
    """
    Executes a read-only SQL SELECT query against the currently active database connection.
    Supports both MySQL and PostgreSQL syntax depending on the active connection's dialect.
    Only SELECT statements are permitted; any DDL/DML operation will be blocked.
    
    Args:
        query (str): A fully-formed SQL SELECT query.
    Returns:
        str: Tab-separated result rows, or an error/warning message.
    """
    connector = get_active_connector()
    logger.info(f"run_query via {connector.dialect}: {query[:120]}")
    return connector.execute_query(query)

@tool
def get_table_detail(table_name: str) -> str:
    """
    Returns the DDL schema and sample rows for a table in the active database.
    Always call this before writing SQL to verify exact column names and types.
    Works with MySQL (SHOW CREATE TABLE) and PostgreSQL (information_schema).
    Args:
        table_name (str): Exact table name (from get_table_names).
    Returns:
        str: DDL + sample data string.
    """
    connector = get_active_connector()
    return connector.get_table_schema(table_name)

@tool
def get_table_names() -> list[str]:
    """
    Lists all available table names in the currently active database connection.
    Works with both MySQL and PostgreSQL connections.
    Returns:
        list[str]: Table names the AI agent may query.
    """
    connector = get_active_connector()
    return connector.get_table_names()
