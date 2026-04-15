"""Integration test fixtures providing ephemeral PostgreSQL via testcontainers.

The PostgresContainer is session-scoped to avoid the ~3s Docker startup per test.
Each deployment subdirectory defines its own ``brotr`` fixture that calls
``make_brotr()`` with the appropriate deployment name.

Schema is created once per deployment; subsequent tests truncate all tables
for isolation (~200x faster than DROP/CREATE per test).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import asyncpg
import docker
import pytest
from docker.errors import DockerException
from pydantic import SecretStr
from testcontainers.postgres import PostgresContainer

from bigbrotr.core.brotr import Brotr
from bigbrotr.core.brotr_config import BrotrConfig
from bigbrotr.core.pool import Pool
from bigbrotr.core.pool_config import DatabaseConfig, PoolConfig


# ---------------------------------------------------------------------------
# Session-scoped container (shared across all integration tests)
# ---------------------------------------------------------------------------

_DOCKER_REQUIRED_MESSAGE = (
    "Docker is required to run integration tests. "
    "Start a Docker daemon or run the unit test suite instead."
)
_PUBLIC_TRUNCATE_TABLES_SQL = """
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


def _ensure_docker_available() -> None:
    """Fail fast with a clear message when Docker is unavailable."""
    try:
        client = docker.from_env()
        try:
            client.ping()
        finally:
            client.close()
    except (DockerException, OSError) as exc:
        pytest.fail(f"{_DOCKER_REQUIRED_MESSAGE} Original error: {exc}", pytrace=False)


@pytest.fixture(scope="session")
def pg_container():
    """Spawn an ephemeral PostgreSQL 18 container for the test session."""
    _ensure_docker_available()
    with PostgresContainer("postgres:18-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def pg_dsn(pg_container: PostgresContainer) -> dict[str, str | int]:
    """Extract connection parameters from the running container."""
    return {
        "host": pg_container.get_container_host_ip(),
        "port": int(pg_container.get_exposed_port(5432)),
        "database": pg_container.dbname,
        "user": pg_container.username,
        "password": pg_container.password,
    }


# ---------------------------------------------------------------------------
# Deployment-aware Brotr factory
# ---------------------------------------------------------------------------

_current_deployment: str | None = None
_deployment_tables: dict[str, tuple[str, ...]] = {}


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL block comments and line comments, return remaining content."""
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql.strip()


def _quote_identifier(identifier: str) -> str:
    """Quote an SQL identifier returned by PostgreSQL catalog introspection."""
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


async def _load_public_truncate_tables(conn: asyncpg.Connection) -> tuple[str, ...]:
    """Return public-schema base tables and partitioned parents suitable for TRUNCATE."""
    rows = await conn.fetch(_PUBLIC_TRUNCATE_TABLES_SQL)
    return tuple(str(row["relname"]) for row in rows)


async def _truncate_public_tables(
    conn: asyncpg.Connection,
    table_names: tuple[str, ...],
) -> None:
    """Truncate all cached public tables for the active deployment."""
    if not table_names:
        return

    identifiers = ", ".join(_quote_identifier(name) for name in table_names)
    await conn.execute(f"TRUNCATE {identifiers} CASCADE")


async def make_brotr(
    pg_dsn: dict[str, str | int],
    deployment: str,
) -> AsyncIterator[Brotr]:
    """Create a Brotr instance with a clean database for the specified deployment.

    On the first call for a deployment, drops and recreates the full schema from
    SQL init files. Subsequent calls for the same deployment truncate all tables
    instead, which is ~200x faster.

    The caller yields the result in an async fixture::

        @pytest.fixture
        async def brotr(pg_dsn):
            async for b in make_brotr(pg_dsn, "bigbrotr"):
                yield b
    """
    global _current_deployment  # noqa: PLW0603

    host = str(pg_dsn["host"])
    port = int(pg_dsn["port"])
    database = str(pg_dsn["database"])
    user = str(pg_dsn["user"])
    password = str(pg_dsn["password"])

    conn = await asyncpg.connect(
        host=host, port=port, database=database, user=user, password=password
    )

    try:
        if _current_deployment != deployment:
            await conn.execute("DROP SCHEMA public CASCADE")
            await conn.execute("CREATE SCHEMA public")

            sql_dir = (
                Path(__file__).parent.parent.parent / f"deployments/{deployment}/postgres/init"
            )
            for sql_file in sorted(sql_dir.glob("*.sql")):
                sql = sql_file.read_text()
                stripped = _strip_sql_comments(sql)
                if not stripped:
                    continue
                await conn.execute(sql)
            _deployment_tables[deployment] = await _load_public_truncate_tables(conn)
            _current_deployment = deployment
        else:
            table_names = _deployment_tables.get(deployment)
            if table_names is None:
                table_names = await _load_public_truncate_tables(conn)
                _deployment_tables[deployment] = table_names
            await _truncate_public_tables(conn, table_names)
    finally:
        await conn.close()

    config = PoolConfig(
        database=DatabaseConfig(
            host=host,
            port=port,
            database=database,
            user=user,
            password=SecretStr(password),
        ),
    )
    pool = Pool(config=config)
    brotr_instance = Brotr(pool=pool, config=BrotrConfig())

    async with brotr_instance:
        yield brotr_instance
