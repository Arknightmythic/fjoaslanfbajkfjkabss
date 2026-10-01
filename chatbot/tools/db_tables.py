from typing import List
from langchain.tools import tool
from chatbot.database.query_engine import query_engine

@tool
def get_table_names() -> List[str]:
    """
    Returns a list of all accessible table names in the Synchrono database schema.
    Use this tool to explore what tables are available before drafting SQL queries.
    """
    return query_engine.get_table_names()
