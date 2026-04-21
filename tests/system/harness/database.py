"""Runtime database helpers for higher-band system tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import asyncpg

from .addressing import RuntimeAddressPlan
from .compose import build_test_env_values


_ROLE_ENV_KEYS = {
    "admin": ("admin", "DB_ADMIN_PASSWORD"),
    "writer": ("writer", "DB_WRITER_PASSWORD"),
    "reader": ("reader", "DB_READER_PASSWORD"),
    "refresher": ("refresher", "DB_REFRESHER_PASSWORD"),
    "ranker": ("ranker", "DB_RANKER_PASSWORD"),
}


@dataclass(frozen=True, slots=True)
class RuntimeDatabaseTarget:
    """Connection settings for one runtime PostgreSQL instance."""

    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def for_plan(
        cls,
        plan: RuntimeAddressPlan,
        *,
        role: str = "admin",
    ) -> RuntimeDatabaseTarget:
        """Build a runtime DB target from the deterministic compose plan."""
        try:
            user, password_env = _ROLE_ENV_KEYS[role]
        except KeyError as exc:
            allowed = ", ".join(sorted(_ROLE_ENV_KEYS))
            raise ValueError(
                f"Unsupported runtime DB role: {role!r}; expected one of {allowed}"
            ) from exc

        env_values = build_test_env_values(plan.profile, plan.project_name)
        return cls(
            host="127.0.0.1",
            port=plan.ports.db,
            database=plan.profile,
            user=user,
            password=env_values[password_env],
        )


async def fetch_rows(
    target: RuntimeDatabaseTarget,
    query: str,
    *args: object,
) -> tuple[dict[str, object], ...]:
    """Execute one query and return normalized row dictionaries."""
    connection = await asyncpg.connect(
        host=target.host,
        port=target.port,
        database=target.database,
        user=target.user,
        password=target.password,
    )
    try:
        rows = await connection.fetch(query, *args)
    finally:
        await connection.close()
    return tuple(dict(row) for row in rows)


async def fetch_value(
    target: RuntimeDatabaseTarget,
    query: str,
    *args: object,
) -> object:
    """Execute one scalar query against the runtime database."""
    connection = await asyncpg.connect(
        host=target.host,
        port=target.port,
        database=target.database,
        user=target.user,
        password=target.password,
    )
    try:
        return await connection.fetchval(query, *args)
    finally:
        await connection.close()


def fetch_runtime_rows(
    plan: RuntimeAddressPlan,
    query: str,
    *args: object,
    role: str = "admin",
) -> tuple[dict[str, object], ...]:
    """Synchronously query row data from the runtime PostgreSQL instance."""
    return asyncio.run(fetch_rows(RuntimeDatabaseTarget.for_plan(plan, role=role), query, *args))


def fetch_runtime_value(
    plan: RuntimeAddressPlan,
    query: str,
    *args: object,
    role: str = "admin",
) -> object:
    """Synchronously query one scalar value from the runtime PostgreSQL instance."""
    return asyncio.run(fetch_value(RuntimeDatabaseTarget.for_plan(plan, role=role), query, *args))
