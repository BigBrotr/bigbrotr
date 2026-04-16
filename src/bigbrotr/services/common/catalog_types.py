"""Shared schema types and constants for the catalog read layer."""

from __future__ import annotations

from dataclasses import dataclass


# Allowed filter operators (whitelist)
_FILTER_OPERATORS: frozenset[str] = frozenset({"=", ">", "<", ">=", "<=", "ILIKE"})

# PG types compatible with the ILIKE operator (text-like types only)
_TEXT_TYPES: frozenset[str] = frozenset({"text", "character varying", "character", "name"})

# PG types that need SQL transforms in SELECT
_BYTEA_TYPES: frozenset[str] = frozenset({"bytea"})
_DATE_TYPES: frozenset[str] = frozenset(
    {
        "date",
        "timestamp without time zone",
        "timestamp with time zone",
    }
)
_NUMERIC_TYPES: frozenset[str] = frozenset({"numeric", "decimal"})

# PG type -> parameter cast mapping for correct filter comparisons
_CAST_TYPES: dict[str, str] = {
    "bytea": "::bytea",
    "bigint": "::bigint",
    "integer": "::integer",
    "smallint": "::smallint",
    "boolean": "::boolean",
    "date": "::date",
    "timestamp without time zone": "::timestamp without time zone",
    "timestamp with time zone": "::timestamp with time zone",
    "numeric": "::numeric",
    "decimal": "::numeric",
    "jsonb": "::jsonb",
}

# Max offset to prevent deep pagination abuse
_MAX_OFFSET = 100_000


@dataclass(frozen=True, slots=True)
class ColumnSchema:
    """Schema information for a single column."""

    name: str
    pg_type: str
    nullable: bool


@dataclass(frozen=True, slots=True)
class TableSchema:
    """Schema information for a table, view, or materialized view."""

    name: str
    columns: tuple[ColumnSchema, ...]
    primary_key: tuple[str, ...]
    is_view: bool


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Result of a paginated query."""

    rows: list[dict[str, object]]
    total: int | None
    limit: int
    offset: int
    next_cursor: str | None = None
