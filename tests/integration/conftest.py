"""Integration test fixtures providing ephemeral PostgreSQL via testcontainers.

The PostgresContainer is session-scoped to avoid the ~3s Docker startup per test.
Each deployment subdirectory defines its own ``brotr`` fixture that calls
``make_brotr()`` with the appropriate deployment name.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import asyncpg
import pytest
from pydantic import SecretStr
from testcontainers.postgres import PostgresContainer

from bigbrotr.core.brotr import Brotr, BrotrConfig
from bigbrotr.core.pool import DatabaseConfig, Pool, PoolConfig


# ---------------------------------------------------------------------------
# Session-scoped container (shared across all integration tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_container():
    """Spawn an ephemeral PostgreSQL 16 container for the test session."""
    with PostgresContainer("postgres:16-alpine") as pg:
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


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL block comments and line comments, return remaining content."""
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql.strip()


async def make_brotr(
    pg_dsn: dict[str, str | int],
    deployment: str,
) -> AsyncIterator[Brotr]:
    """Create a Brotr instance with fresh schema from the specified deployment.

    Drops and recreates all objects for full isolation between tests.
    The caller yields the result in an async fixture::

        @pytest.fixture
        async def brotr(pg_dsn):
            async for b in make_brotr(pg_dsn, "bigbrotr"):
                yield b
    """
    host = str(pg_dsn["host"])
    port = int(pg_dsn["port"])
    database = str(pg_dsn["database"])
    user = str(pg_dsn["user"])
    password = str(pg_dsn["password"])

    conn = await asyncpg.connect(
        host=host, port=port, database=database, user=user, password=password
    )

    try:
        await conn.execute("DROP SCHEMA public CASCADE")
        await conn.execute("CREATE SCHEMA public")

        sql_dir = Path(__file__).parent.parent.parent / f"deployments/{deployment}/postgres/init"
        for sql_file in sorted(sql_dir.glob("*.sql")):
            sql = sql_file.read_text()
            stripped = _strip_sql_comments(sql)
            if not stripped:
                continue
            await conn.execute(sql)
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
