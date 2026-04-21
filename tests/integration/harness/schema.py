"""Schema bootstrap helpers for deployment-aware integration fixtures."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import asyncpg


PUBLIC_TRUNCATE_TABLES_SQL = """
SELECT c.relname
FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n
    ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND (
      c.relkind = 'p'
      OR (
          c.relkind = 'r'
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_inherits AS i
              WHERE i.inhrelid = c.oid
          )
      )
  )
ORDER BY c.relname
"""


@dataclass(slots=True)
class DeploymentSchemaState:
    """Cache deployment-specific truncate targets across test fixtures."""

    current_deployment: str | None = None
    deployment_tables: dict[str, tuple[str, ...]] = field(default_factory=dict)


deployment_schema_state = DeploymentSchemaState()


def strip_sql_comments(sql: str) -> str:
    """Remove SQL block comments and line comments, return remaining content."""
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql.strip()


def quote_identifier(identifier: str) -> str:
    """Quote an SQL identifier returned by PostgreSQL catalog introspection."""
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def deployment_sql_dir(deployment: str) -> Path:
    """Return the built-in deployment SQL-init directory for a profile."""
    return Path(__file__).resolve().parents[3] / f"deployments/{deployment}/postgres/init"


async def load_public_truncate_tables(conn: asyncpg.Connection) -> tuple[str, ...]:
    """Return public-schema base tables and partitioned parents suitable for TRUNCATE."""
    rows = await conn.fetch(PUBLIC_TRUNCATE_TABLES_SQL)
    return tuple(str(row["relname"]) for row in rows)


async def truncate_public_tables(
    conn: asyncpg.Connection,
    table_names: tuple[str, ...],
) -> None:
    """Truncate all cached public tables for the active deployment."""
    if not table_names:
        return

    identifiers = ", ".join(quote_identifier(name) for name in table_names)
    await conn.execute(f"TRUNCATE {identifiers} CASCADE")


async def ensure_deployment_schema(
    conn: asyncpg.Connection,
    deployment: str,
    *,
    state: DeploymentSchemaState = deployment_schema_state,
) -> None:
    """Ensure a clean public schema for the requested deployment."""
    if state.current_deployment != deployment:
        await conn.execute("DROP SCHEMA public CASCADE")
        await conn.execute("CREATE SCHEMA public")

        for sql_file in sorted(deployment_sql_dir(deployment).glob("*.sql")):
            sql = sql_file.read_text()
            stripped = strip_sql_comments(sql)
            if not stripped:
                continue
            await conn.execute(sql)

        state.deployment_tables[deployment] = await load_public_truncate_tables(conn)
        state.current_deployment = deployment
        return

    table_names = state.deployment_tables.get(deployment)
    if table_names is None:
        table_names = await load_public_truncate_tables(conn)
        state.deployment_tables[deployment] = table_names

    await truncate_public_tables(conn, table_names)
