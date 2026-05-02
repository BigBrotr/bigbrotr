"""Deployment-aware Brotr factory helpers for integration tests."""

from __future__ import annotations

from typing import TypeAlias

import asyncpg
from pydantic import SecretStr

from bigbrotr.core.brotr import Brotr
from bigbrotr.core.brotr_config import BrotrConfig
from bigbrotr.core.pool import Pool
from bigbrotr.core.pool_config import DatabaseConfig, PoolConfig
from tests.integration.harness.schema import ensure_deployment_schema


PgDsn: TypeAlias = dict[str, str | int]


def build_pool_config(pg_dsn: PgDsn) -> PoolConfig:
    """Build a real pool configuration from integration DSN values."""
    return PoolConfig(
        database=DatabaseConfig(
            host=str(pg_dsn["host"]),
            port=int(pg_dsn["port"]),
            database=str(pg_dsn["database"]),
            user=str(pg_dsn["user"]),
            password=SecretStr(str(pg_dsn["password"])),
        ),
    )


async def make_deployment_brotr(pg_dsn: PgDsn, deployment: str):
    """Yield a live Brotr instance backed by a clean deployment schema."""
    conn = await asyncpg.connect(
        host=str(pg_dsn["host"]),
        port=int(pg_dsn["port"]),
        database=str(pg_dsn["database"]),
        user=str(pg_dsn["user"]),
        password=str(pg_dsn["password"]),
    )

    try:
        await ensure_deployment_schema(conn, deployment)
    finally:
        await conn.close()

    brotr_instance = Brotr(pool=Pool(config=build_pool_config(pg_dsn)), config=BrotrConfig())

    async with brotr_instance:
        yield brotr_instance
