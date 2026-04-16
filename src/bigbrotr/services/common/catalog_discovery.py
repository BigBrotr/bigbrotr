"""Schema discovery helpers for the shared read-only catalog."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr

    from .catalog import ColumnSchema


async def discover_table_and_view_names(brotr: Brotr) -> tuple[set[str], set[str]]:
    """Discover base tables and regular views from ``information_schema``."""
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


async def discover_matview_names(brotr: Brotr) -> set[str]:
    """Discover materialized views from ``pg_catalog``."""
    rows = await brotr.fetch(
        """
        SELECT matviewname AS table_name
        FROM pg_catalog.pg_matviews
        WHERE schemaname = 'public'
        """,
    )
    return {row["table_name"] for row in rows}


async def discover_columns(
    brotr: Brotr,
    table_names: set[str],
) -> dict[str, list[ColumnSchema]]:
    """Discover columns via ``pg_attribute`` so matviews are included."""
    from .catalog import ColumnSchema  # noqa: PLC0415

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


async def discover_primary_keys(
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


async def discover_matview_unique_indexes(
    brotr: Brotr,
    matview_names: set[str],
) -> dict[str, list[str]]:
    """Discover usable unique-index columns for materialized views."""
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
