"""Query-planning helpers for the shared read-only catalog."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

from .catalog import (
    _BYTEA_TYPES,
    _CAST_TYPES,
    _DATE_TYPES,
    _FILTER_OPERATORS,
    _NUMERIC_TYPES,
    _TEXT_TYPES,
    CatalogError,
    ColumnSchema,
    TableSchema,
)


@dataclass(frozen=True, slots=True)
class OrderTerm:
    """One validated ORDER BY term used for public list pagination."""

    column: str
    direction: str


@dataclass(frozen=True, slots=True)
class QueryContext:
    """Precomputed query state shared by count and data queries."""

    columns_by_name: dict[str, ColumnSchema]
    col_types: dict[str, str]
    select_cols: str
    where_clauses: list[str]
    params: list[Any]
    next_param_idx: int
    base_where_sql: str
    base_params: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class PaginationPlan:
    """Concrete SQL plan for one catalog list query."""

    data_query: str
    data_params: list[Any]
    count_query: str | None
    count_params: tuple[Any, ...]
    order_terms: tuple[OrderTerm, ...]
    use_keyset: bool


def build_query_context(
    schema: TableSchema,
    filters: dict[str, str] | None,
) -> QueryContext:
    """Build validated filter state shared by count and data queries."""
    col_names = {column.name for column in schema.columns}
    columns_by_name = {column.name: column for column in schema.columns}
    col_types = {column.name: column.pg_type for column in schema.columns}
    select_cols = build_select_columns(schema.columns)

    where_clauses: list[str] = []
    params: list[Any] = []
    param_idx = 1
    if filters:
        for column, raw_value in filters.items():
            if column not in col_names:
                raise CatalogError(f"Unknown column: {column}")
            operator, value = parse_filter(raw_value)
            if operator == "ILIKE" and col_types[column] not in _TEXT_TYPES:
                raise CatalogError(
                    f"ILIKE operator requires a text column, got {col_types[column]} for {column}"
                )
            cast = param_cast(col_types[column])
            where_clauses.append(f"{column} {operator} ${param_idx}{cast}")
            params.append(
                coerce_parameter_value(
                    column,
                    col_types[column],
                    value,
                    source="filter",
                )
            )
            param_idx += 1

    return QueryContext(
        columns_by_name=columns_by_name,
        col_types=col_types,
        select_cols=select_cols,
        where_clauses=where_clauses,
        params=params,
        next_param_idx=param_idx,
        base_where_sql=(" WHERE " + " AND ".join(where_clauses)) if where_clauses else "",
        base_params=tuple(params),
    )


def build_pagination_plan(  # noqa: PLR0913
    table: str,
    *,
    schema: TableSchema,
    context: QueryContext,
    sort: str | None,
    cursor: str | None,
    limit: int,
    offset: int,
    include_total: bool,
    prefer_keyset: bool,
) -> PaginationPlan:
    """Build the concrete SQL and parameter plan for one list query."""
    where_clauses = list(context.where_clauses)
    params = list(context.params)
    next_param_idx = context.next_param_idx

    order_terms = build_order_terms(
        schema,
        columns_by_name=context.columns_by_name,
        sort=sort,
        prefer_keyset=prefer_keyset,
    )
    if cursor is not None:
        if not order_terms:
            raise CatalogError("Cursor pagination requires a stable primary key")
        where_clauses.append(
            build_cursor_clause(
                cursor,
                sort=sort,
                order_terms=order_terms,
                col_types=context.col_types,
                params=params,
                next_param_idx=next_param_idx,
            )
        )
        next_param_idx = len(params) + 1

    data_where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    order_sql = build_order_sql(
        order_terms,
        sort=sort,
        schema=schema,
        prefer_keyset=prefer_keyset,
    )
    use_keyset = bool(order_terms) and offset == 0

    data_params = list(params)
    if use_keyset:
        data_query = (
            f"SELECT {context.select_cols} FROM {table}{data_where_sql}{order_sql}"  # noqa: S608
            f" LIMIT ${next_param_idx}"
        )
        data_params.append(limit + 1)
    else:
        data_query = (
            f"SELECT {context.select_cols} FROM {table}{data_where_sql}{order_sql}"  # noqa: S608
            f" LIMIT ${next_param_idx} OFFSET ${next_param_idx + 1}"
        )
        data_params.extend([limit, offset])

    count_query = None
    if include_total:
        count_query = f"SELECT COUNT(*)::int FROM {table}{context.base_where_sql}"  # noqa: S608

    return PaginationPlan(
        data_query=data_query,
        data_params=data_params,
        count_query=count_query,
        count_params=context.base_params,
        order_terms=order_terms,
        use_keyset=use_keyset,
    )


def build_select_columns(columns: tuple[ColumnSchema, ...]) -> str:
    """Build a SELECT column list with type-appropriate transforms."""
    parts: list[str] = []
    for column in columns:
        if column.pg_type in _BYTEA_TYPES:
            parts.append(f"ENCODE({column.name}, 'hex') AS {column.name}")
        elif column.pg_type in _DATE_TYPES:
            parts.append(f"{column.name}::text AS {column.name}")
        elif column.pg_type in _NUMERIC_TYPES:
            parts.append(f"{column.name}::float AS {column.name}")
        else:
            parts.append(column.name)
    return ", ".join(parts)


def parse_filter(raw: str) -> tuple[str, str]:
    """Parse a filter value like ``\">=:100\"`` into ``(\">=\", \"100\")``."""
    for operator in sorted(_FILTER_OPERATORS, key=len, reverse=True):
        prefix = operator + ":"
        if raw.upper().startswith(prefix):
            return operator, raw[len(prefix) :]
    return "=", raw


def parse_sort(sort: str) -> tuple[str, str]:
    """Parse a sort spec like ``\"name:desc\"`` into ``(\"name\", \"DESC\")``."""
    if ":" in sort:
        column, direction = sort.rsplit(":", 1)
        direction = direction.upper()
        if direction not in ("ASC", "DESC"):
            raise CatalogError(f"Invalid sort direction: {direction}")
        return column, direction
    return sort, "ASC"


def param_cast(pg_type: str) -> str:
    """Return a ``::type`` cast suffix for a parameter placeholder."""
    if pg_type in _CAST_TYPES:
        return _CAST_TYPES[pg_type]
    return ""


def build_order_terms(
    schema: TableSchema,
    *,
    columns_by_name: dict[str, ColumnSchema],
    sort: str | None,
    prefer_keyset: bool,
) -> tuple[OrderTerm, ...]:
    """Build a stable ORDER BY plan for one query."""
    if sort:
        order_col, order_dir = parse_sort(sort)
        column = columns_by_name.get(order_col)
        if column is None:
            raise CatalogError(f"Unknown sort column: {order_col}")
        if not prefer_keyset or not schema.primary_key or column.nullable:
            return ()
        pk_terms = tuple(
            OrderTerm(column=pk_col, direction=order_dir)
            for pk_col in schema.primary_key
            if pk_col != order_col
        )
        return (OrderTerm(column=order_col, direction=order_dir), *pk_terms)

    if prefer_keyset and schema.primary_key:
        return tuple(OrderTerm(column=pk_col, direction="ASC") for pk_col in schema.primary_key)

    return ()


def build_order_sql(
    order_terms: tuple[OrderTerm, ...],
    *,
    sort: str | None,
    schema: TableSchema,
    prefer_keyset: bool,
) -> str:
    """Build the ORDER BY clause for the current query mode."""
    if order_terms:
        order_parts = [f"{term.column} {term.direction}" for term in order_terms]
        return " ORDER BY " + ", ".join(order_parts)
    if sort:
        order_col, order_dir = parse_sort(sort)
        return f" ORDER BY {order_col} {order_dir}"
    if prefer_keyset and schema.primary_key:
        pk_parts = [f"{column} ASC" for column in schema.primary_key]
        return " ORDER BY " + ", ".join(pk_parts)
    return ""


def build_cursor_clause(  # noqa: PLR0913
    cursor: str,
    *,
    sort: str | None,
    order_terms: tuple[OrderTerm, ...],
    col_types: dict[str, str],
    params: list[Any],
    next_param_idx: int,
) -> str:
    """Build a tuple-comparison keyset clause from one opaque cursor."""
    values = decode_cursor(cursor, sort=sort, order_terms=order_terms)
    operator = "<" if order_terms[0].direction == "DESC" else ">"
    lhs = ", ".join(term.column for term in order_terms)
    rhs_parts: list[str] = []
    for index, term in enumerate(order_terms, start=next_param_idx):
        value = values.get(term.column)
        if term.column not in values:
            raise CatalogError("Cursor does not match requested page order")
        params.append(
            coerce_parameter_value(
                term.column,
                col_types[term.column],
                value,
                source="cursor",
            )
        )
        rhs_parts.append(f"${index}{param_cast(col_types[term.column])}")
    return f"({lhs}) {operator} ({', '.join(rhs_parts)})"


def encode_cursor(
    row: dict[str, Any],
    *,
    sort: str | None,
    order_terms: tuple[OrderTerm, ...],
) -> str:
    """Encode one opaque cursor from the last row in a keyset page."""
    payload = {
        "v": 1,
        "sort": sort or "",
        "values": {term.column: row[term.column] for term in order_terms},
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(
    cursor: str,
    *,
    sort: str | None,
    order_terms: tuple[OrderTerm, ...],
) -> dict[str, Any]:
    """Decode and validate one opaque keyset cursor."""
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding)
        payload = json.loads(raw.decode())
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogError("Invalid cursor") from error

    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise CatalogError("Invalid cursor")

    payload_sort = payload.get("sort", "")
    if payload_sort != (sort or ""):
        raise CatalogError("Cursor does not match requested sort")

    values = payload.get("values")
    if not isinstance(values, dict):
        raise CatalogError("Invalid cursor")

    expected_columns = {term.column for term in order_terms}
    if not expected_columns <= set(values):
        raise CatalogError("Cursor does not match requested page order")

    return values


def coerce_parameter_value(
    column: str,
    pg_type: str,
    value: Any,
    *,
    source: str,
) -> Any:
    """Coerce one cursor/filter value back into a DB-comparable Python value."""
    if value is None:
        raise CatalogError(f"Invalid {source} value for column {column}")
    if pg_type in _BYTEA_TYPES:
        if not isinstance(value, str):
            raise CatalogError(f"Invalid {source} value for column {column}")
        try:
            return bytes.fromhex(value)
        except ValueError as error:
            if source == "filter":
                raise CatalogError(f"Invalid hex value for column {column}: {value}") from error
            raise CatalogError(f"Invalid {source} value for column {column}") from error
    return value
