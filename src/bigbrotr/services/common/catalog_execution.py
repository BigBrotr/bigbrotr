"""Execution helpers for catalog list and primary-key queries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import asyncpg

from .catalog_types import _BYTEA_TYPES, QueryResult, TableSchema


if TYPE_CHECKING:
    from collections.abc import Callable

    from bigbrotr.core.brotr import Brotr

    from .catalog_planner import PaginationPlan
    from .catalog_types import ColumnSchema


async def execute_catalog_query(  # noqa: PLR0913
    brotr: Brotr,
    *,
    plan: PaginationPlan,
    limit: int,
    offset: int,
    sort: str | None,
    encode_cursor: Callable[..., str],
    error_factory: Callable[[str], Exception],
) -> QueryResult:
    """Execute one validated catalog pagination plan and normalize the result."""
    try:
        total: int | None = None
        if plan.count_query is not None:
            total = await brotr.fetchval(plan.count_query, *plan.count_params)
        rows = await brotr.fetch(plan.data_query, *plan.data_params)
    except asyncpg.DataError as e:
        raise error_factory("Invalid filter value") from e
    except asyncpg.PostgresError as e:
        raise error_factory("Query execution failed") from e

    result_rows = [dict(row) for row in rows]
    next_cursor: str | None = None
    if plan.use_keyset and len(result_rows) > limit:
        result_rows = result_rows[:limit]
        next_cursor = encode_cursor(
            result_rows[-1],
            sort=sort,
            order_terms=plan.order_terms,
        )

    return QueryResult(
        rows=result_rows,
        total=total,
        limit=limit,
        offset=offset,
        next_cursor=next_cursor,
    )


async def execute_catalog_get_by_pk(  # noqa: PLR0913
    brotr: Brotr,
    *,
    table: str,
    schema: TableSchema,
    pk_values: dict[str, str],
    build_select_columns: Callable[[tuple[ColumnSchema, ...]], str],
    param_cast: Callable[[str], str],
    error_factory: Callable[[str], Exception],
) -> dict[str, Any] | None:
    """Execute one validated primary-key lookup against a discovered table."""
    if not schema.primary_key:
        raise error_factory(f"Table {table} has no primary key")

    col_types = {column.name: column.pg_type for column in schema.columns}
    select_cols = build_select_columns(schema.columns)

    where_parts: list[str] = []
    params: list[Any] = []
    for i, pk_col in enumerate(schema.primary_key, 1):
        if pk_col not in pk_values:
            raise error_factory(f"Missing primary key column: {pk_col}")
        cast = param_cast(col_types[pk_col])
        where_parts.append(f"{pk_col} = ${i}{cast}")
        value = pk_values[pk_col]
        if col_types[pk_col] in _BYTEA_TYPES:
            try:
                params.append(bytes.fromhex(value))
            except ValueError as e:
                raise error_factory(f"Invalid hex value for column {pk_col}: {value}") from e
        else:
            params.append(value)

    where_sql = " AND ".join(where_parts)
    query = f"SELECT {select_cols} FROM {table} WHERE {where_sql}"  # noqa: S608

    try:
        row = await brotr.fetchrow(query, *params)
    except asyncpg.DataError as e:
        raise error_factory("Invalid parameter value") from e
    except asyncpg.PostgresError as e:
        raise error_factory("Query execution failed") from e

    return dict(row) if row else None
