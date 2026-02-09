"""Integration test fixtures providing ephemeral PostgreSQL via testcontainers.

The PostgresContainer is session-scoped to avoid the ~3s Docker startup per test.
Schema is re-initialized per test (function-scoped ``brotr`` fixture) for isolation.
"""

from __future__ import annotations

from pathlib import Path

import asyncpg
import pytest
from pydantic import SecretStr
from testcontainers.postgres import PostgresContainer

from bigbrotr.core.brotr import Brotr, BrotrConfig
from bigbrotr.core.pool import DatabaseConfig, Pool, PoolConfig


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL block comments and line comments, return remaining content."""
    import re

    # Remove block comments (/* ... */)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    # Remove line comments (-- ...)
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql.strip()


# ---------------------------------------------------------------------------
# Session-scoped container
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
# Function-scoped Brotr with fresh schema
# ---------------------------------------------------------------------------


@pytest.fixture
async def brotr(pg_dsn: dict[str, str | int]):
    """Provide a Brotr instance backed by a real database with fresh schema.

    Drops and recreates all objects for full isolation between tests.
    """
    host = str(pg_dsn["host"])
    port = int(pg_dsn["port"])
    database = str(pg_dsn["database"])
    user = str(pg_dsn["user"])
    password = str(pg_dsn["password"])

    # Connect with raw asyncpg for schema setup (bypass Pool)
    conn = await asyncpg.connect(
        host=host, port=port, database=database, user=user, password=password
    )

    try:
        # Drop everything for clean state
        await conn.execute("DROP SCHEMA public CASCADE")
        await conn.execute("CREATE SCHEMA public")

        # Apply SQL files in order (skip comment-only files that cause asyncpg protocol errors)
        sql_dir = Path(__file__).parent.parent.parent / "deployments/bigbrotr/postgres/init"
        for sql_file in sorted(sql_dir.glob("*.sql")):
            sql = sql_file.read_text()
            # asyncpg fails on files with no executable SQL (only comments)
            stripped = _strip_sql_comments(sql)
            if not stripped:
                continue
            await conn.execute(sql)
    finally:
        await conn.close()

    # Build Pool + Brotr for the test
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
