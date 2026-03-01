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

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import asyncpg


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr

logger = logging.getLogger(__name__)


class CatalogError(Exception):
    """Client-safe error raised by Catalog operations.

    Messages are always controlled literals or validated identifiers —
    never raw database error details.
    """


# Allowed filter operators (whitelist)
_FILTER_OPERATORS: frozenset[str] = frozenset({"=", ">", "<", ">=", "<=", "ILIKE"})

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
    total: int
    limit: int
    offset: int


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
        base_table_names, view_names = await self._discover_table_and_view_names(brotr)
        matview_names = await self._discover_matview_names(brotr)
        all_names = base_table_names | view_names | matview_names

        if not all_names:
            logger.warning("no tables or views discovered in public schema")
            return

        columns_by_table = await self._discover_columns(brotr, all_names)
        pk_by_table = await self._discover_primary_keys(brotr, base_table_names)
        unique_by_matview = await self._discover_matview_unique_indexes(brotr, matview_names)

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

        Returns:
            Paginated query result.

        Raises:
            CatalogError: If the table, column, or operator is invalid.
        """
        schema = self._get_schema(table)
        limit = min(max(limit, 1), max_page_size)
        offset = min(max(offset, 0), _MAX_OFFSET)

        col_names = {c.name for c in schema.columns}
        col_types = {c.name: c.pg_type for c in schema.columns}

        # Build SELECT columns with type transforms
        select_cols = self._build_select_columns(schema.columns)

        # Build WHERE clause
        where_clauses: list[str] = []
        params: list[Any] = []
        param_idx = 1

        if filters:
            for col, raw_value in filters.items():
                if col not in col_names:
                    raise CatalogError(f"Unknown column: {col}")
                op, value = self._parse_filter(raw_value)
                cast = self._param_cast(col_types[col])
                where_clauses.append(f"{col} {op} ${param_idx}{cast}")
                if col_types[col] in _BYTEA_TYPES:
                    try:
                        params.append(bytes.fromhex(value))
                    except ValueError as e:
                        raise CatalogError(f"Invalid hex value for column {col}: {value}") from e
                else:
                    params.append(value)
                param_idx += 1

        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # Build ORDER BY
        order_sql = ""
        if sort:
            order_col, order_dir = self._parse_sort(sort)
            if order_col not in col_names:
                raise CatalogError(f"Unknown sort column: {order_col}")
            order_sql = f" ORDER BY {order_col} {order_dir}"

        # Count query + data query (wrapped to convert DB type errors to ValueError)
        count_query = f"SELECT COUNT(*)::int FROM {table}{where_sql}"  # noqa: S608
        data_query = (
            f"SELECT {select_cols} FROM {table}{where_sql}{order_sql}"  # noqa: S608
            f" LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        )

        try:
            total: int = await brotr.fetchval(count_query, *params)
            params.extend([limit, offset])
            rows = await brotr.fetch(data_query, *params)
        except asyncpg.DataError as e:
            raise CatalogError("Invalid filter value") from e

        return QueryResult(
            rows=[dict(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
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
        schema = self._get_schema(table)
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

        return dict(row) if row else None

    # -------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------

    def _get_schema(self, table: str) -> TableSchema:
        """Look up and validate a table name against discovered schema."""
        if table not in self._tables:
            raise CatalogError(f"Unknown table: {table}")
        return self._tables[table]

    @staticmethod
    def _build_select_columns(columns: tuple[ColumnSchema, ...]) -> str:
        """Build a SELECT column list with type-appropriate transforms."""
        parts: list[str] = []
        for col in columns:
            if col.pg_type in _BYTEA_TYPES:
                parts.append(f"ENCODE({col.name}, 'hex') AS {col.name}")
            elif col.pg_type in _DATE_TYPES:
                parts.append(f"{col.name}::text AS {col.name}")
            elif col.pg_type in _NUMERIC_TYPES:
                parts.append(f"{col.name}::float AS {col.name}")
            else:
                parts.append(col.name)
        return ", ".join(parts)

    @staticmethod
    def _parse_filter(raw: str) -> tuple[str, str]:
        """Parse a filter value like ``">=:100"`` into ``(">=", "100")``.

        If no operator prefix is found, defaults to ``=``.
        """
        for op in sorted(_FILTER_OPERATORS, key=len, reverse=True):
            prefix = op + ":"
            if raw.upper().startswith(prefix):
                return op, raw[len(prefix) :]
        return "=", raw

    @staticmethod
    def _parse_sort(sort: str) -> tuple[str, str]:
        """Parse a sort spec like ``"name:desc"`` into ``("name", "DESC")``."""
        if ":" in sort:
            col, direction = sort.rsplit(":", 1)
            direction = direction.upper()
            if direction not in ("ASC", "DESC"):
                raise CatalogError(f"Invalid sort direction: {direction}")
            return col, direction
        return sort, "ASC"

    @staticmethod
    def _param_cast(pg_type: str) -> str:
        """Return a ``::type`` cast suffix for a parameter placeholder.

        Ensures correct type comparison by casting the parameter to its
        native PostgreSQL type.  Bytea parameters are passed as raw bytes.
        """
        if pg_type in _CAST_TYPES:
            return _CAST_TYPES[pg_type]
        return ""

    # -------------------------------------------------------------------
    # Discovery queries
    # -------------------------------------------------------------------

    @staticmethod
    async def _discover_table_and_view_names(brotr: Brotr) -> tuple[set[str], set[str]]:
        """Discover base tables and regular views from information_schema.

        Returns:
            Tuple of (base_table_names, view_names).
        """
        rows = await brotr.fetch(
            """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type IN ('BASE TABLE', 'VIEW')
            """,
        )
        base_tables: set[str] = set()
        views: set[str] = set()
        for row in rows:
            if row["table_type"] == "BASE TABLE":
                base_tables.add(row["table_name"])
            else:
                views.add(row["table_name"])
        return base_tables, views

    @staticmethod
    async def _discover_matview_names(brotr: Brotr) -> set[str]:
        """Discover materialized views from pg_catalog."""
        rows = await brotr.fetch(
            """
            SELECT matviewname AS table_name
            FROM pg_catalog.pg_matviews
            WHERE schemaname = 'public'
            """,
        )
        return {row["table_name"] for row in rows}

    @staticmethod
    async def _discover_columns(
        brotr: Brotr,
        table_names: set[str],
    ) -> dict[str, list[ColumnSchema]]:
        """Discover columns via pg_attribute (covers matviews unlike information_schema)."""
        if not table_names:
            return {}
        rows = await brotr.fetch(
            """
            SELECT
                c.relname AS table_name,
                a.attname AS column_name,
                pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                NOT a.attnotnull AS is_nullable
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relname = ANY($1)
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY c.relname, a.attnum
            """,
            sorted(table_names),
        )
        result: dict[str, list[ColumnSchema]] = {}
        for row in rows:
            result.setdefault(row["table_name"], []).append(
                ColumnSchema(
                    name=row["column_name"],
                    pg_type=row["data_type"],
                    nullable=row["is_nullable"],
                )
            )
        return result

    @staticmethod
    async def _discover_primary_keys(
        brotr: Brotr,
        table_names: set[str],
    ) -> dict[str, list[str]]:
        """Discover primary key columns for base tables."""
        if not table_names:
            return {}
        rows = await brotr.fetch(
            """
            SELECT
                c.relname AS table_name,
                a.attname AS column_name,
                array_position(con.conkey, a.attnum) AS pos
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(con.conkey)
            WHERE con.contype = 'p'
              AND n.nspname = 'public'
              AND c.relname = ANY($1)
            ORDER BY c.relname, pos
            """,
            sorted(table_names),
        )
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["table_name"], []).append(row["column_name"])
        return result

    @staticmethod
    async def _discover_matview_unique_indexes(
        brotr: Brotr,
        matview_names: set[str],
    ) -> dict[str, list[str]]:
        """Discover unique index columns for materialized views.

        Materialized views lack formal primary keys but may have unique
        indexes.  We pick the first unique index found for each view.
        """
        if not matview_names:
            return {}
        rows = await brotr.fetch(
            """
            SELECT
                ct.relname AS table_name,
                i.indexrelid AS index_oid,
                a.attname AS column_name,
                array_position(i.indkey, a.attnum) AS pos
            FROM pg_index i
            JOIN pg_class ct ON ct.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = ct.relnamespace
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indisunique
              AND i.indpred IS NULL
              AND n.nspname = 'public'
              AND ct.relname = ANY($1)
            ORDER BY ct.relname, i.indexrelid, pos
            """,
            sorted(matview_names),
        )
        result: dict[str, list[str]] = {}
        first_index_oid: dict[str, int] = {}
        for row in rows:
            name = row["table_name"]
            index_oid = row["index_oid"]
            if name in first_index_oid and first_index_oid[name] != index_oid:
                continue
            first_index_oid[name] = index_oid
            result.setdefault(name, []).append(row["column_name"])
        return result
