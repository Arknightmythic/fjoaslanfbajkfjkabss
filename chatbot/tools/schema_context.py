import os
import json
import re
from typing import Dict, List, Optional, Set, Any
from dotenv import load_dotenv
from langchain.tools import tool
from sqlalchemy import text
from chatbot.database.query_engine import query_engine

load_dotenv()

# In-memory thread/process cache for schema context (0ms latency for subsequent lookups)
_SCHEMA_CACHE: Dict[str, str] = {}


def get_allowed_schema_config() -> Dict[str, Optional[Set[str]]]:
    """
    Parses table and column access permissions from the ALLOWED_DB_SCHEMA environment variable.
    
    Supported formats in .env:
      - table1:*,table2:* (allows all columns for table1 and table2)
      - table1:col1,col2|table2:*
      - * (allows all tables and all columns globally)
      - JSON format: {"uploaded_files": "*", "manual_matches": ["file_id", "nama_incoming"]}
      
    Returns:
      Dict[table_name, Set[column_names] or None if wildcard (*)]
    """
    raw_config = os.getenv("ALLOWED_DB_SCHEMA", "").strip()

    # Default fallback if not specified in .env
    if not raw_config:
        return {
            "uploaded_files": None,
            "manual_matches": None,
            "institution": {"file_id", "id_incoming", "match_score", "match_result", "upload_date"},
            "ref_grades": None,
            "ref_sync_statuses": None,
            "ref_match_results": None,
            "grade_bands": None,
        }

    # Global wildcard
    if raw_config == "*":
        return {"*": None}

    # Attempt JSON parsing
    if raw_config.startswith("{") and raw_config.endswith("}"):
        try:
            parsed = json.loads(raw_config)
            result = {}
            for tbl, cols in parsed.items():
                if cols == "*" or cols is None:
                    result[tbl.strip()] = None
                elif isinstance(cols, list):
                    result[tbl.strip()] = {str(c).strip() for c in cols}
                elif isinstance(cols, str):
                    result[tbl.strip()] = {c.strip() for c in cols.split(",") if c.strip()}
            return result
        except Exception as e:
            print(f"[Schema Config Warning] Failed to parse JSON ALLOWED_DB_SCHEMA: {e}")

    # Parse text format: table1:col1,col2,table2:*,table3:colA,colB
    config: Dict[str, Optional[Set[str]]] = {}
    items = re.split(r"[|\n]", raw_config)
    if len(items) == 1:
        tokens = re.split(r",(?=[a-zA-Z0-9_]+:)", raw_config)
    else:
        tokens = items

    for token in tokens:
        clean_token = token.strip()
        if not clean_token:
            continue
        if ":" in clean_token:
            tbl_name, cols_part = clean_token.split(":", 1)
            tbl_name = tbl_name.strip()
            cols_part = cols_part.strip()
            if cols_part == "*" or not cols_part:
                config[tbl_name] = None
            else:
                config[tbl_name] = {c.strip() for c in cols_part.split(",") if c.strip()}
        else:
            config[clean_token] = None

    return config


def fetch_table_metadata_from_db(table_name: str) -> Dict[str, Any]:
    """
    Fetches table descriptions, column definitions, and native database constraints
    (PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK) with semantic comments directly from PostgreSQL catalogs.
    """
    metadata: Dict[str, Any] = {
        "table_name": table_name,
        "table_description": None,
        "columns": [],
        "constraints": []
    }
    try:
        with query_engine.engine.connect() as conn:
            dialect = query_engine.engine.dialect.name.lower()
            if "postgres" in dialect:
                # 1. Fetch column metadata and column comments from information_schema and pg_description
                col_res = conn.execute(text("""
                    SELECT 
                        c.column_name,
                        c.data_type,
                        c.is_nullable,
                        col_description(c.table_name::regclass, c.ordinal_position) AS col_description,
                        obj_description(c.table_name::regclass, 'pg_class') AS table_description
                    FROM information_schema.columns c
                    WHERE c.table_schema = 'public' AND c.table_name = :table_name
                    ORDER BY c.ordinal_position;
                """), {"table_name": table_name}).fetchall()

                for r in col_res:
                    col_name = r[0]
                    data_type = r[1]
                    nullable = r[2]
                    col_desc = r[3]
                    tbl_desc = r[4]

                    if tbl_desc and not metadata["table_description"]:
                        metadata["table_description"] = tbl_desc

                    metadata["columns"].append({
                        "name": col_name,
                        "type": data_type,
                        "nullable": nullable,
                        "description": col_desc or ""
                    })

                # 2. Fetch native database constraints (PK, FK, UNIQUE, CHECK) from pg_constraint catalog
                con_res = conn.execute(text("""
                    SELECT 
                        con.conname AS constraint_name,
                        CASE con.contype
                            WHEN 'p' THEN 'PRIMARY KEY'
                            WHEN 'f' THEN 'FOREIGN KEY'
                            WHEN 'u' THEN 'UNIQUE'
                            WHEN 'c' THEN 'CHECK'
                            ELSE con.contype::text
                        END AS constraint_type,
                        pg_get_constraintdef(con.oid, true) AS definition,
                        obj_description(con.oid, 'pg_constraint') AS business_context
                    FROM pg_constraint con
                    JOIN pg_class rel ON rel.oid = con.conrelid
                    JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                    WHERE nsp.nspname = 'public' AND rel.relname = :table_name
                      AND con.conname NOT LIKE '2200_%'
                    ORDER BY con.contype, con.conname;
                """), {"table_name": table_name}).fetchall()

                for r in con_res:
                    metadata["constraints"].append({
                        "name": r[0],
                        "type": r[1],
                        "definition": r[2],
                        "business_context": r[3] or ""
                    })
            else:
                # SQLite fallback for offline unit tests
                res = conn.execute(text(f"PRAGMA table_info('{table_name}');")).fetchall()
                for r in res:
                    metadata["columns"].append({
                        "name": r[1],
                        "type": r[2] or "TEXT",
                        "nullable": "YES" if not r[3] else "NO",
                        "description": ""
                    })
    except Exception as e:
        print(f"[Schema DB Fetch Notice] Could not fetch schema metadata for table '{table_name}': {e}")

    return metadata


def generate_table_schema_doc(table_name: str, allowed_columns: Optional[Set[str]]) -> str:
    """Constructs the English markdown schema specification for a single table with constraints."""
    meta = fetch_table_metadata_from_db(table_name)
    tbl_desc = meta.get("table_description") or f"Table {table_name} in Synchrono database."

    lines = [f"### TABLE: {table_name}"]
    lines.append(f"Description: {tbl_desc}")
    lines.append("Columns:")

    columns = meta.get("columns", [])
    if columns:
        for col in columns:
            col_name = col["name"]
            # Filter column based on .env allowlist (None implies wildcard '*')
            if allowed_columns is not None and col_name not in allowed_columns:
                continue

            type_str = col["type"].upper()
            sem_desc = col.get("description", "").strip()
            if sem_desc:
                lines.append(f"  * {col_name} ({type_str}): {sem_desc}")
            else:
                lines.append(f"  * {col_name} ({type_str})")
    else:
        lines.append(f"  (Column metadata for table '{table_name}' could not be loaded from database)")

    # Append native database constraints
    constraints = meta.get("constraints", [])
    if constraints:
        lines.append("Database Constraints:")
        for con in constraints:
            b_ctx = f" -- Business Context: {con['business_context']}" if con["business_context"] else ""
            lines.append(f"  * [{con['type']}] {con['definition']}{b_ctx}")

    return "\n".join(lines)


@tool
def get_schemas(table_names: Optional[List[str]] = None) -> str:
    """
    Retrieves the authoritative database schema context (tables, columns, data types, business descriptions,
    and native database constraints like Primary Keys, Foreign Keys, Unique, and Check rules)
    directly from PostgreSQL native catalogs (information_schema and pg_constraint).
    
    CRITICAL USAGE GUIDELINES:
    - Call this tool ONCE at the start of a conversation thread if you need column definitions or constraint rules.
    - You can filter specific tables on-demand via the 'table_names' parameter, or leave empty for all allowed tables.
    - The returned schema context is automatically retained in conversation memory for the entire session.

    Args:
        table_names (list[str], optional): Specific table names to inspect.
            Example: ['uploaded_files', 'manual_matches'].

    Returns:
        str: Comprehensive English schema specification including table descriptions, column semantics,
             and native database constraints directly from PostgreSQL.
    """
    allowed_config = get_allowed_schema_config()
    is_global_wildcard = "*" in allowed_config

    # Resolve target tables
    if table_names:
        requested_tables = [t.strip().lower() for t in table_names if t.strip()]
    else:
        if is_global_wildcard:
            requested_tables = query_engine.get_table_names()
        else:
            requested_tables = list(allowed_config.keys())

    output_blocks: List[str] = [
        "=================================================================",
        "SYNCHRONO DATABASE SCHEMA & NATIVE CONSTRAINTS (POSTGRESQL CATALOG)",
        "[INTERNAL REASONING CONTEXT ONLY - DO NOT EXPOSE RAW CONSTRAINT NAMES",
        "(e.g. *_fkey, *_pkey, chk_*) OR RAW DDL SYNTAX TO THE USER.",
        "ALWAYS TRANSLATE CONSTRAINTS & ENTITIES INTO NATURAL BUSINESS CONCEPTS.]",
        "=================================================================\n"
    ]

    for tbl in requested_tables:
        # Enforce security allowlist from .env
        if not is_global_wildcard and tbl not in allowed_config:
            output_blocks.append(f"[WARNING] Access to table '{tbl}' is not permitted by system policy (.env).\n")
            continue

        allowed_cols = None if is_global_wildcard else allowed_config.get(tbl)
        
        # Check in-memory process cache
        cache_key = f"{tbl}:{sorted(list(allowed_cols)) if allowed_cols else '*'}"
        if cache_key in _SCHEMA_CACHE:
            output_blocks.append(_SCHEMA_CACHE[cache_key])
        else:
            doc = generate_table_schema_doc(tbl, allowed_cols)
            _SCHEMA_CACHE[cache_key] = doc
            output_blocks.append(doc)
        output_blocks.append("")

    output_blocks.append("### SPECIAL SEARCH & FALLBACK GUIDELINES:")
    output_blocks.append("1. uploaded_files tracks upload batches. Quality grades are numeric (1=A, 2=B, 3=C, 4=D, 5=E, 6=F).")
    output_blocks.append("2. When a dataset identifier (e.g. 'qa/grade_b_warm', 'qa/edge_cases_matrix', 'fav-001') is queried,")
    output_blocks.append("   first check 'uploaded_files.file_id' and 'uploaded_files.original_filename'.")
    output_blocks.append("3. If not found in 'uploaded_files', ALWAYS check 'manual_matches.file_id' and 'institution.file_id',")
    output_blocks.append("   as pipeline/QA datasets bypass uploaded_files and reside directly in matching tables.")

    return "\n".join(output_blocks)

# Backward-compatibility aliases
get_schema = get_schemas
get_database_schema = get_schemas
