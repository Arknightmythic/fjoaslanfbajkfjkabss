import re
from typing import Dict, Any, TypedDict
from langchain.tools import tool
from langgraph.graph import StateGraph, START, END
from chatbot.database.query_engine import query_engine

class ExecutionState(TypedDict):
    query: str
    error_message: str
    is_dangerous: bool
    query_result: str

class SafeQueryValidator:
    def __init__(self):
        builder = StateGraph(ExecutionState)
        builder.add_node("validator", self._validate)
        builder.add_node("executor", self._execute)
        builder.add_edge(START, "validator")
        builder.add_conditional_edges("validator", self._check_safety, {
            "dangerous": END,
            "safe": "executor"
        })
        builder.add_edge("executor", END)
        self.app = builder.compile()

    def _validate(self, state: ExecutionState) -> Dict[str, Any]:
        raw_query = state.get("query", "").strip()
        cleaned = re.sub(r"```(?:sql)?\s*|\s*```", "", raw_query, flags=re.IGNORECASE).strip()
        
        dangerous_keywords = ["drop", "delete", "update", "insert", "alter", "create", "truncate", "grant", "revoke"]
        if any(re.search(rf"\b{kw}\b", cleaned, re.IGNORECASE) for kw in dangerous_keywords):
            return {
                "query_result": "[WARNING] Operasi pengubahan data (DML/DDL) ditolak. Hanya query SELECT read-only yang diizinkan.",
                "is_dangerous": True
            }
        
        if not cleaned.lower().startswith("select"):
            return {
                "query_result": "[WARNING] Query harus berupa pernyataan SELECT.",
                "is_dangerous": True
            }
        
        # Check mandatory LIMIT unless aggregate functions are used
        is_aggregate = bool(re.search(r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(", cleaned, re.IGNORECASE))
        has_limit = bool(re.search(r"\bLIMIT\s+\d+", cleaned, re.IGNORECASE))
        
        if not is_aggregate and not has_limit:
            # Auto-append a default LIMIT 50 to prevent crash while preserving user intent
            cleaned = f"{cleaned} LIMIT 50"

        return {"query": cleaned, "is_dangerous": False}

    def _execute(self, state: ExecutionState) -> Dict[str, Any]:
        query = state.get("query", "")
        try:
            result = query_engine.execute_query(query)
            return {"query_result": str(result), "is_dangerous": False}
        except Exception as e:
            return {
                "error_message": str(e),
                "query_result": f"Gagal mengeksekusi query: {e}. Silakan periksa kembali nama kolom atau tabel.",
                "is_dangerous": False
            }

    def _check_safety(self, state: ExecutionState) -> str:
        return "dangerous" if state.get("is_dangerous") else "safe"

_validator_app = SafeQueryValidator().app

@tool
def run_query(query: str) -> dict:
    """
    Executes a read-only SELECT SQL query against the Synchrono database and returns the result.

    Args:
        query (str): The strictly READ-ONLY SELECT SQL query to execute.
                     MANDATORY: MUST include an explicit LIMIT clause (e.g. LIMIT 20 or LIMIT 50) 
                     unless performing an aggregate function like COUNT(*). 
                     Do NOT wrap the query in markdown code blocks.

    Returns:
        dict: A dictionary containing the query execution state:
            - query_result: Tab-separated table records or error message.
            - is_dangerous: True if dangerous write operation was attempted.
    """
    result = _validator_app.invoke({"query": query})
    return result
