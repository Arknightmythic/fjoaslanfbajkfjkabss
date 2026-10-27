import re
from typing import Any, Mapping, Optional

from src.semantic.registry import (
    DOMAINS,
    DomainDefinition,
    resolve_dimension_name,
    resolve_metric_name,
)

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


class SemanticCompilationError(ValueError):
    pass


def compile_semantic_query(
    domain_name: str,
    metrics: list[str],
    dimensions: Optional[list[str]] = None,
    time_range: Optional[dict[str, Any]] = None,
    filters: Optional[Mapping[str, Any]] = None,
    order_by: Optional[list[str]] = None,
    limit: int = 50,
) -> tuple[str, dict[str, Any], list[str], list[str]]:
    domain: Optional[DomainDefinition] = DOMAINS.get(domain_name)
    if not domain:
        raise SemanticCompilationError(f"Domain '{domain_name}' tidak dikenal. Pilih dari: {list(DOMAINS.keys())}")

    resolved_metrics: list[str] = []
    for m in metrics:
        clean_m = resolve_metric_name(m)
        if clean_m not in domain.metrics:
            valid_m = list(domain.metrics.keys())
            raise SemanticCompilationError(
                f"Metrik '{m}' tidak tersedia di domain '{domain_name}'. Pilihan yang valid: {valid_m}"
            )
        if clean_m not in resolved_metrics:
            resolved_metrics.append(clean_m)

    if not resolved_metrics:
        # Default to primary metric
        resolved_metrics = [list(domain.metrics.keys())[0]]

    resolved_dims: list[str] = []
    for d in dimensions or []:
        clean_d = resolve_dimension_name(d)
        if clean_d not in domain.dimensions:
            valid_d = list(domain.dimensions.keys())
            raise SemanticCompilationError(
                f"Dimensi '{d}' tidak tersedia di domain '{domain_name}'. Pilihan yang valid: {valid_d}"
            )
        if clean_d not in resolved_dims:
            resolved_dims.append(clean_d)

    active_joins: dict[str, Any] = {}
    select_items: list[str] = []

    # 1. Dimensions in SELECT
    for d_name in resolved_dims:
        dim_def = domain.dimensions[d_name]
        if dim_def.requires_join and dim_def.requires_join in domain.joins:
            active_joins[dim_def.requires_join] = domain.joins[dim_def.requires_join]
        select_items.append(f"{dim_def.expression} AS {d_name}")

    # 2. Metrics in SELECT
    for m_name in resolved_metrics:
        m_def = domain.metrics[m_name]
        select_items.append(f"{m_def.expression} AS {m_name}")

    # 3. FROM and JOINs
    from_clause = f"FROM {domain.primary_table} {domain.table_alias}"
    join_clauses: list[str] = []

    # Check filters for required joins
    where_clauses: list[str] = []
    params: dict[str, Any] = {}

    # Time range condition
    if time_range and time_range.get("start_at"):
        where_clauses.append(f"{domain.time_column} >= :p_time_start")
        params["p_time_start"] = time_range["start_at"]
    if time_range and time_range.get("end_at"):
        where_clauses.append(f"{domain.time_column} < :p_time_end")
        params["p_time_end"] = time_range["end_at"]

    # Process custom filters
    param_idx = 0
    for raw_f_name, f_val in (filters or {}).items():
        if f_val is None or f_val == "":
            continue
        clean_f_name = resolve_dimension_name(raw_f_name)
        if clean_f_name not in domain.dimensions:
            # Check if it matches a direct column or ignore if invalid
            continue

        dim_def = domain.dimensions[clean_f_name]
        if dim_def.requires_join and dim_def.requires_join in domain.joins:
            active_joins[dim_def.requires_join] = domain.joins[dim_def.requires_join]

        col_expr = dim_def.filter_column

        # Operator handling
        op = "eq"
        val = f_val
        if isinstance(f_val, Mapping):
            op = (f_val.get("op") or "eq").lower()
            val = f_val.get("value")

        p_name = f"p_filter_{clean_f_name}_{param_idx}"
        param_idx += 1

        if op in ("like", "contains", "ilike") or (isinstance(val, str) and clean_f_name in ("institution", "filename")):
            where_clauses.append(f"{col_expr} LIKE :{p_name}")
            params[p_name] = f"%{str(val).strip().lower()}%" if "lower(" in col_expr.lower() else f"%{str(val).strip()}%"
        elif op in ("in",) and isinstance(val, (list, tuple)):
            if not val:
                continue
            item_names = []
            for item_i, item_v in enumerate(val):
                sub_p = f"{p_name}_{item_i}"
                item_names.append(f":{sub_p}")
                params[sub_p] = item_v
            where_clauses.append(f"{col_expr} IN ({', '.join(item_names)})")
        elif op in ("neq", "!="):
            where_clauses.append(f"{col_expr} != :{p_name}")
            params[p_name] = val
        elif op in ("gt", ">"):
            where_clauses.append(f"{col_expr} > :{p_name}")
            params[p_name] = val
        elif op in ("gte", ">="):
            where_clauses.append(f"{col_expr} >= :{p_name}")
            params[p_name] = val
        elif op in ("lt", "<"):
            where_clauses.append(f"{col_expr} < :{p_name}")
            params[p_name] = val
        elif op in ("lte", "<="):
            where_clauses.append(f"{col_expr} <= :{p_name}")
            params[p_name] = val
        else:
            # Default equality
            if "lower(" in col_expr.lower() and isinstance(val, str):
                where_clauses.append(f"{col_expr} = :{p_name}")
                params[p_name] = val.strip().lower()
            else:
                where_clauses.append(f"{col_expr} = :{p_name}")
                params[p_name] = val

    for j_def in active_joins.values():
        join_clauses.append(f"{j_def.join_type} {j_def.table} {j_def.alias} ON {j_def.condition}")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    group_sql = f"GROUP BY {', '.join(resolved_dims)}" if resolved_dims else ""

    # ORDER BY handling
    order_items: list[str] = []
    if order_by:
        for ob in order_by:
            parts = ob.strip().split()
            ob_col = parts[0].lower()
            direction = parts[1].upper() if len(parts) > 1 and parts[1].upper() in ("ASC", "DESC") else "ASC"
            resolved_col = resolve_dimension_name(resolve_metric_name(ob_col))
            if resolved_col in resolved_dims or resolved_col in resolved_metrics:
                order_items.append(f"{resolved_col} {direction}")

    if not order_items:
        if "day" in resolved_dims:
            order_items.append("day ASC")
        elif resolved_dims:
            order_items.append(f"{resolved_dims[0]} ASC")
        elif resolved_metrics:
            order_items.append(f"{resolved_metrics[0]} DESC")

    order_sql = f"ORDER BY {', '.join(order_items)}" if order_items else ""

    clamped_limit = max(1, min(int(limit or 50), 200))
    limit_sql = f"LIMIT {clamped_limit}"

    sql_parts = [
        f"SELECT {', '.join(select_items)}",
        from_clause,
    ]
    if join_clauses:
        sql_parts.extend(join_clauses)
    if where_sql:
        sql_parts.append(where_sql)
    if group_sql:
        sql_parts.append(group_sql)
    if order_sql:
        sql_parts.append(order_sql)
    sql_parts.append(limit_sql)

    final_sql = "\n".join(sql_parts) + ";"
    return final_sql, params, resolved_metrics, resolved_dims
