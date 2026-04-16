"""Schema introspection and safe query builder for read-only database access.

Discovers PostgreSQL tables, views, and materialized views at runtime,
then provides parameterized query building with whitelist-by-construction
column/table validation.  Shared by the API and DVM services.

The Catalog performs four discovery queries at startup:

1. ``information_schema.tables`` for base tables and regular views.
2. ``pg_catalog.pg_matviews`` for materialized views (not in information_schema).
3. ``pg_attribute`` for column metadata of all discovered objects (including
   materialized views, which are absent from ``information_schema.columns``).
4. ``pg_constraint`` + ``pg_attribute`` for primary keys, plus ``pg_index``
   for materialized-view unique indexes.

See Also:
    [Api][bigbrotr.services.api.service.Api]: REST API service that
        uses the Catalog for endpoint generation.
    [Dvm][bigbrotr.services.dvm.service.Dvm]: NIP-90 DVM service that
        uses the Catalog for query execution.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

import asyncpg

from .catalog_discovery import (
    discover_columns,
    discover_matview_names,
    discover_matview_unique_indexes,
    discover_primary_keys,
    discover_table_and_view_names,
)


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr

    from .catalog_planner import OrderTerm as _OrderTerm
    from .catalog_planner import PaginationPlan as _PaginationPlan
    from .catalog_planner import QueryContext as _QueryContext
else:
    _OrderTerm = Any
    _PaginationPlan = Any
    _QueryContext = Any

logger = logging.getLogger(__name__)


class _CatalogPlannerModule(Protocol):
    """Typed protocol for the lazily imported planner module."""

    def build_query_context(
        self,
        schema: TableSchema,
        filters: dict[str, str] | None,
    ) -> _QueryContext: ...

    def build_pagination_plan(  # noqa: PLR0913
        self,
        table: str,
        *,
        schema: TableSchema,
        context: _QueryContext,
        sort: str | None,
        cursor: str | None,
        limit: int,
        offset: int,
        include_total: bool,
        prefer_keyset: bool,
    ) -> _PaginationPlan: ...

    def build_select_columns(self, columns: tuple[ColumnSchema, ...]) -> str: ...

    def parse_filter(self, raw: str) -> tuple[str, str]: ...

    def parse_sort(self, sort: str) -> tuple[str, str]: ...

    def param_cast(self, pg_type: str) -> str: ...

    def build_order_terms(
        self,
        schema: TableSchema,
        *,
        columns_by_name: dict[str, ColumnSchema],
        sort: str | None,
        prefer_keyset: bool,
    ) -> tuple[_OrderTerm, ...]: ...

    def build_order_sql(
        self,
        order_terms: tuple[_OrderTerm, ...],
        *,
        sort: str | None,
        schema: TableSchema,
        prefer_keyset: bool,
    ) -> str: ...

    def build_cursor_clause(  # noqa: PLR0913
        self,
        cursor: str,
        *,
        sort: str | None,
        order_terms: tuple[_OrderTerm, ...],
        col_types: dict[str, str],
        params: list[Any],
        next_param_idx: int,
    ) -> str: ...

    def encode_cursor(
        self,
        row: dict[str, Any],
        *,
        sort: str | None,
        order_terms: tuple[_OrderTerm, ...],
    ) -> str: ...

    def decode_cursor(
        self,
        cursor: str,
        *,
        sort: str | None,
        order_terms: tuple[_OrderTerm, ...],
    ) -> dict[str, Any]: ...

    def coerce_parameter_value(
        self,
        column: str,
        pg_type: str,
        value: Any,
        *,
        source: str,
    ) -> Any: ...


def _planner_module() -> _CatalogPlannerModule:
    """Load the catalog planner lazily to avoid import cycles."""
    return cast("_CatalogPlannerModule", importlib.import_module(".catalog_planner", __package__))


class CatalogError(Exception):
    """Client-safe error raised by Catalog operations.

    Messages are always controlled literals or validated identifiers —
    never raw database error details.

    The :attr:`client_message` attribute provides the sanitised string
    intended for HTTP/Nostr responses, avoiding ``str(exception)`` which
    static analysers flag as potential stack-trace exposure.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.client_message: str = message


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

# PG type → parameter cast mapping for correct filter comparisons
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

# ---------------------------------------------------------------------------
# Schema dataclasses
# ---------------------------------------------------------------------------


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

    rows: list[dict[str, Any]]
    total: int | None
    limit: int
    offset: int
    next_cursor: str | None = None


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class Catalog:
    """Schema introspector and safe parameterized query builder.

    Usage::

        catalog = Catalog()
        await catalog.discover(brotr)
        result = await catalog.query(brotr, "relay_stats", limit=100, offset=0)
    """

    def __init__(self) -> None:
        self._tables: dict[str, TableSchema] = {}

    @property
    def tables(self) -> dict[str, TableSchema]:
        """Discovered table schemas, keyed by name."""
        return self._tables

    async def discover(self, brotr: Brotr) -> None:
        """Introspect the public schema and populate table metadata.

        Queries information_schema for tables/views, pg_matviews for
        materialized views, pg_attribute for column info, and
        pg_constraint/pg_index for primary keys and unique indexes.
        """
        base_table_names, view_names = await discover_table_and_view_names(brotr)
        matview_names = await discover_matview_names(brotr)
        all_names = base_table_names | view_names | matview_names

        if not all_names:
            logger.warning("no tables or views discovered in public schema")
            return

        columns_by_table = await discover_columns(brotr, all_names)
        pk_by_table = await discover_primary_keys(brotr, base_table_names)
        unique_by_matview = await discover_matview_unique_indexes(brotr, matview_names)

        tables: dict[str, TableSchema] = {}
        for name in sorted(all_names):
            cols = columns_by_table.get(name, ())
            if not cols:
                continue
            pk = pk_by_table.get(name, ()) or unique_by_matview.get(name, ())
            is_view = name in view_names or name in matview_names
            tables[name] = TableSchema(
                name=name,
                columns=tuple(cols),
                primary_key=tuple(pk),
                is_view=is_view,
            )

        self._tables = tables
        logger.info(
            "catalog_discovered tables=%d views=%d",
            sum(1 for t in tables.values() if not t.is_view),
            sum(1 for t in tables.values() if t.is_view),
        )

    async def query(  # noqa: PLR0913
        self,
        brotr: Brotr,
        table: str,
        *,
        limit: int,
        offset: int,
        max_page_size: int = 1000,
        filters: dict[str, str] | None = None,
        sort: str | None = None,
        include_total: bool = True,
        cursor: str | None = None,
        prefer_keyset: bool = False,
    ) -> QueryResult:
        """Execute a safe paginated query against a discovered table.

        Args:
            brotr: Database interface.
            table: Table or view name (must exist in discovered schema).
            limit: Maximum rows to return.
            offset: Number of rows to skip.
            max_page_size: Hard ceiling on limit.
            filters: Column filters as ``{column: "op:value"}`` or
                ``{column: "value"}`` (defaults to ``=``).
            sort: Sort specification as ``"column"`` or ``"column:desc"``.
            include_total: Whether to execute an additional ``COUNT(*)``
                query and include ``total`` in the result metadata.
            cursor: Opaque keyset-pagination cursor produced by a prior query.
            prefer_keyset: Whether to prefer cursor pagination when the
                schema provides a stable primary key.

        Returns:
            Paginated query result.

        Raises:
            CatalogError: If the table, column, or operator is invalid.
        """
        if table not in self._tables:
            raise CatalogError(f"Unknown table: {table}")
        schema = self._tables[table]
        limit = min(max(limit, 1), max_page_size)
        offset = min(max(offset, 0), _MAX_OFFSET)
        if cursor is not None and offset > 0:
            raise CatalogError("Cursor pagination cannot be combined with offset")

        context = self._build_query_context(schema, filters)
        plan = self._build_pagination_plan(
            table,
            schema=schema,
            context=context,
            sort=sort,
            cursor=cursor,
            limit=limit,
            offset=offset,
            include_total=include_total,
            prefer_keyset=prefer_keyset,
        )
        try:
            total: int | None = None
            if plan.count_query is not None:
                total = await brotr.fetchval(plan.count_query, *plan.count_params)
            rows = await brotr.fetch(plan.data_query, *plan.data_params)
        except asyncpg.DataError as e:
            raise CatalogError("Invalid filter value") from e
        except asyncpg.PostgresError as e:
            raise CatalogError("Query execution failed") from e

        result_rows = [dict(row) for row in rows]
        next_cursor: str | None = None
        if plan.use_keyset and len(result_rows) > limit:
            result_rows = result_rows[:limit]
            next_cursor = self._encode_cursor(
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

    async def get_by_pk(
        self,
        brotr: Brotr,
        table: str,
        pk_values: dict[str, str],
    ) -> dict[str, Any] | None:
        """Fetch a single row by primary key.

        Args:
            brotr: Database interface.
            table: Table name.
            pk_values: Primary key column-value pairs.

        Returns:
            Row as a dict, or None if not found.

        Raises:
            CatalogError: If the table has no primary key or values are missing.
        """
        if table not in self._tables:
            raise CatalogError(f"Unknown table: {table}")
        schema = self._tables[table]
        if not schema.primary_key:
            raise CatalogError(f"Table {table} has no primary key")

        col_types = {c.name: c.pg_type for c in schema.columns}
        select_cols = self._build_select_columns(schema.columns)

        where_parts: list[str] = []
        params: list[Any] = []
        for i, pk_col in enumerate(schema.primary_key, 1):
            if pk_col not in pk_values:
                raise CatalogError(f"Missing primary key column: {pk_col}")
            cast = self._param_cast(col_types[pk_col])
            where_parts.append(f"{pk_col} = ${i}{cast}")
            value = pk_values[pk_col]
            if col_types[pk_col] in _BYTEA_TYPES:
                try:
                    params.append(bytes.fromhex(value))
                except ValueError as e:
                    raise CatalogError(f"Invalid hex value for column {pk_col}: {value}") from e
            else:
                params.append(value)

        where_sql = " AND ".join(where_parts)
        query = f"SELECT {select_cols} FROM {table} WHERE {where_sql}"  # noqa: S608

        try:
            row = await brotr.fetchrow(query, *params)
        except asyncpg.DataError as e:
            raise CatalogError("Invalid parameter value") from e
        except asyncpg.PostgresError as e:
            raise CatalogError("Query execution failed") from e

        return dict(row) if row else None

    # -------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------

    def _build_query_context(
        self,
        schema: TableSchema,
        filters: dict[str, str] | None,
    ) -> _QueryContext:
        """Build validated filter state shared by count and data queries."""
        return _planner_module().build_query_context(schema, filters)

    def _build_pagination_plan(  # noqa: PLR0913
        self,
        table: str,
        *,
        schema: TableSchema,
        context: _QueryContext,
        sort: str | None,
        cursor: str | None,
        limit: int,
        offset: int,
        include_total: bool,
        prefer_keyset: bool,
    ) -> _PaginationPlan:
        """Build the concrete SQL and parameter plan for one list query."""
        return _planner_module().build_pagination_plan(
            table,
            schema=schema,
            context=context,
            sort=sort,
            cursor=cursor,
            limit=limit,
            offset=offset,
            include_total=include_total,
            prefer_keyset=prefer_keyset,
        )

    @staticmethod
    def _build_select_columns(columns: tuple[ColumnSchema, ...]) -> str:
        """Build a SELECT column list with type-appropriate transforms."""
        return _planner_module().build_select_columns(columns)

    @staticmethod
    def _parse_filter(raw: str) -> tuple[str, str]:
        """Parse a filter value like ``">=:100"`` into ``(">=", "100")``.

        If no operator prefix is found, defaults to ``=``.
        """
        return _planner_module().parse_filter(raw)

    @staticmethod
    def _parse_sort(sort: str) -> tuple[str, str]:
        """Parse a sort spec like ``"name:desc"`` into ``("name", "DESC")``."""
        return _planner_module().parse_sort(sort)

    @staticmethod
    def _param_cast(pg_type: str) -> str:
        """Return a ``::type`` cast suffix for a parameter placeholder.

        Ensures correct type comparison by casting the parameter to its
        native PostgreSQL type.  Bytea parameters are passed as raw bytes.
        """
        return _planner_module().param_cast(pg_type)

    def _build_order_terms(
        self,
        schema: TableSchema,
        *,
        columns_by_name: dict[str, ColumnSchema],
        sort: str | None,
        prefer_keyset: bool,
    ) -> tuple[_OrderTerm, ...]:
        """Build a stable ORDER BY plan for one query."""
        return _planner_module().build_order_terms(
            schema,
            columns_by_name=columns_by_name,
            sort=sort,
            prefer_keyset=prefer_keyset,
        )

    @staticmethod
    def _build_order_sql(
        order_terms: tuple[_OrderTerm, ...],
        *,
        sort: str | None,
        schema: TableSchema,
        prefer_keyset: bool,
    ) -> str:
        """Build the ORDER BY clause for the current query mode."""
        return _planner_module().build_order_sql(
            order_terms,
            sort=sort,
            schema=schema,
            prefer_keyset=prefer_keyset,
        )

    def _build_cursor_clause(  # noqa: PLR0913
        self,
        cursor: str,
        *,
        sort: str | None,
        order_terms: tuple[_OrderTerm, ...],
        col_types: dict[str, str],
        params: list[Any],
        next_param_idx: int,
    ) -> str:
        """Build a tuple-comparison keyset clause from one opaque cursor."""
        return _planner_module().build_cursor_clause(
            cursor,
            sort=sort,
            order_terms=order_terms,
            col_types=col_types,
            params=params,
            next_param_idx=next_param_idx,
        )

    @staticmethod
    def _encode_cursor(
        row: dict[str, Any],
        *,
        sort: str | None,
        order_terms: tuple[_OrderTerm, ...],
    ) -> str:
        """Encode one opaque cursor from the last row in a keyset page."""
        return _planner_module().encode_cursor(row, sort=sort, order_terms=order_terms)

    @staticmethod
    def _decode_cursor(
        cursor: str,
        *,
        sort: str | None,
        order_terms: tuple[_OrderTerm, ...],
    ) -> dict[str, Any]:
        """Decode and validate one opaque keyset cursor."""
        return _planner_module().decode_cursor(cursor, sort=sort, order_terms=order_terms)

    @staticmethod
    def _coerce_parameter_value(
        column: str,
        pg_type: str,
        value: Any,
        *,
        source: str,
    ) -> Any:
        """Coerce one cursor/filter value back into a DB-comparable Python value."""
        return _planner_module().coerce_parameter_value(column, pg_type, value, source=source)
