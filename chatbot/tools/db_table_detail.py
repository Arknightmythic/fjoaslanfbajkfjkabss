from langchain.tools import tool
from chatbot.database.query_engine import query_engine

@tool
def get_table_detail(table_name: str) -> str:
    """
    Returns the DDL structure (CREATE TABLE) and sample data preview for a specific table.

    Args:
        table_name (str): The exact name of the table to inspect (e.g. 'uploaded_files', 'manual_matches').

    Returns:
        str: Formatted string containing table DDL and sample rows for column name inspection.
    """
    return query_engine.get_table_schema(table_name)
