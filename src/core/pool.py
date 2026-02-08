"""
Async PostgreSQL connection pool built on asyncpg.

Manages a pool of database connections with configurable size limits, automatic
retry with exponential backoff on connection failures, health-checked connection
acquisition, and transactional context managers. Compatible with PGBouncer for
connection multiplexing in containerized deployments.

All query methods (fetch, fetchrow, fetchval, execute, executemany) retry
automatically on transient connection errors (InterfaceError,
ConnectionDoesNotExistError) but do not retry on query-level errors such as
syntax errors or constraint violations.

Example:
    pool = Pool.from_yaml("config.yaml")

    async with pool:
        rows = await pool.fetch("SELECT * FROM relays LIMIT 10")

        async with pool.transaction() as conn:
            await conn.execute("INSERT INTO relays ...")
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator  # noqa: TC003
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Literal, cast

import asyncpg
from pydantic import BaseModel, Field, SecretStr, ValidationInfo, field_validator, model_validator

from utils.yaml import load_yaml

from .logger import Logger


async def _init_connection(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    """Register JSON/JSONB codecs on a new connection.

    Called automatically by asyncpg for each new connection in the pool.
    Enables transparent serialization of Python dicts to PostgreSQL JSON/JSONB
    columns and deserialization back to dicts, so callers never need to call
    ``json.dumps()``/``json.loads()`` manually.

    Args:
        conn: The asyncpg connection to configure.
    """
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


# ---------------------------------------------------------------------------
# Configuration Models
# ---------------------------------------------------------------------------


class DatabaseConfig(BaseModel):
    """PostgreSQL connection parameters.

    The password is loaded from the environment variable named by
    ``password_env`` (default: ``DB_PASSWORD``). It is never read from
    configuration files directly.
    """

    host: str = Field(default="localhost", min_length=1, description="Database hostname")
    port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    database: str = Field(default="bigbrotr", min_length=1, description="Database name")
    user: str = Field(default="admin", min_length=1, description="Database user")
    password_env: str = Field(
        default="DB_PASSWORD",  # pragma: allowlist secret
        min_length=1,
        description="Environment variable name for database password",
    )
    password: SecretStr = Field(description="Database password (loaded from password_env)")

    @model_validator(mode="before")
    @classmethod
    def resolve_password(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Resolve the database password from the environment variable."""
        if isinstance(data, dict) and "password" not in data:
            env_var = data.get("password_env", "DB_PASSWORD")  # pragma: allowlist secret
            value = os.getenv(env_var)
            if not value:
                raise ValueError(f"{env_var} environment variable not set")
            data["password"] = SecretStr(value)
        return data


class LimitsConfig(BaseModel):
    """Connection pool size and resource limits.

    Controls the minimum and maximum number of connections maintained by
    the pool, the query count before a connection is recycled, and the
    idle timeout before an unused connection is closed.
    """

    min_size: int = Field(default=5, ge=1, le=100, description="Minimum connections")
    max_size: int = Field(default=20, ge=1, le=200, description="Maximum connections")
    max_queries: int = Field(default=50_000, ge=100, description="Queries before recycling")
    max_inactive_connection_lifetime: float = Field(
        default=300.0, ge=0.0, description="Idle timeout (seconds)"
    )

    @field_validator("max_size")
    @classmethod
    def validate_max_size(cls, v: int, info: ValidationInfo) -> int:
        """Ensure max_size >= min_size."""
        min_size = info.data.get("min_size", 5)
        if v < min_size:
            raise ValueError(f"max_size ({v}) must be >= min_size ({min_size})")
        return v


class TimeoutsConfig(BaseModel):
    """Timeout settings for pool operations (in seconds)."""

    acquisition: float = Field(default=10.0, ge=0.1, description="Connection acquisition timeout")
    health_check: float = Field(default=5.0, ge=0.1, description="Health check timeout")


class RetryConfig(BaseModel):
    """Retry strategy for failed connection attempts.

    Supports both exponential and linear backoff between retries.
    """

    max_attempts: int = Field(default=3, ge=1, le=10, description="Max retry attempts")
    initial_delay: float = Field(default=1.0, ge=0.1, description="Initial retry delay")
    max_delay: float = Field(default=10.0, ge=0.1, description="Maximum retry delay")
    exponential_backoff: bool = Field(default=True, description="Use exponential backoff")

    @field_validator("max_delay")
    @classmethod
    def validate_max_delay(cls, v: float, info: ValidationInfo) -> float:
        """Ensure max_delay >= initial_delay."""
        initial_delay = info.data.get("initial_delay", 1.0)
        if v < initial_delay:
            raise ValueError(f"max_delay ({v}) must be >= initial_delay ({initial_delay})")
        return v


class ServerSettingsConfig(BaseModel):
    """PostgreSQL server-side session settings.

    These are sent as ``server_settings`` when creating the asyncpg pool
    and apply to every connection in the pool.
    """

    application_name: str = Field(default="bigbrotr", description="Application name")
    timezone: str = Field(default="UTC", description="Timezone")
    statement_timeout: int = Field(
        default=300_000, ge=0, description="Max query execution time in milliseconds (0=unlimited)"
    )


class PoolConfig(BaseModel):
    """Aggregate configuration for the connection pool.

    Groups all pool-related settings: database credentials, connection
    limits, timeouts, retry strategy, and PostgreSQL server settings.
    """

    database: DatabaseConfig = Field(default_factory=lambda: DatabaseConfig.model_validate({}))
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    server_settings: ServerSettingsConfig = Field(default_factory=ServerSettingsConfig)


# ---------------------------------------------------------------------------
# Pool Class
# ---------------------------------------------------------------------------


class Pool:
    """Async PostgreSQL connection pool manager.

    Wraps ``asyncpg.Pool`` to provide retry logic, health-checked connection
    acquisition, and transactional context managers. Connections are initialized
    with JSON/JSONB codecs for transparent dict serialization.

    Supports two construction patterns: direct instantiation with a
    ``PoolConfig`` object, or factory methods ``from_yaml()``/``from_dict()``
    for configuration-driven setup.

    Example:
        pool = Pool.from_yaml("config.yaml")

        async with pool:
            rows = await pool.fetch("SELECT * FROM events LIMIT 10")

            async with pool.transaction() as conn:
                await conn.execute("INSERT INTO ...")
    """

    def __init__(self, config: PoolConfig | None = None) -> None:
        """Initialize pool with optional configuration.

        Args:
            config: Pool configuration. If not provided, uses defaults
                which read ``DB_PASSWORD`` from the environment.
        """
        self._config = config or PoolConfig()
        self._pool: asyncpg.Pool[asyncpg.Record] | None = None
        self._is_connected: bool = False
        self._connection_lock = asyncio.Lock()
        self._logger = Logger("pool")

    @classmethod
    def from_yaml(cls, config_path: str) -> Pool:
        """Create a Pool from a YAML configuration file.

        Args:
            config_path: Path to the YAML configuration file.

        Returns:
            A configured Pool instance (not yet connected).

        Raises:
            FileNotFoundError: If the configuration file does not exist.
        """
        return cls.from_dict(load_yaml(config_path))

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> Pool:
        """Create a Pool from a configuration dictionary.

        Args:
            config_dict: Dictionary with pool settings matching
                PoolConfig field names.

        Returns:
            A configured Pool instance (not yet connected).
        """
        config = PoolConfig(**config_dict)
        return cls(config=config)

    def _retry_delay(self, attempt: int) -> float:
        """Compute retry backoff delay for the given attempt number."""
        retry = self._config.retry
        if retry.exponential_backoff:
            delay = retry.initial_delay * (2**attempt)
        else:
            delay = retry.initial_delay * (attempt + 1)
        return float(min(delay, retry.max_delay))

    # -------------------------------------------------------------------------
    # Connection Lifecycle
    # -------------------------------------------------------------------------

    async def connect(self) -> None:
        """Create the asyncpg connection pool with retry on failure.

        Uses exponential or linear backoff (per RetryConfig) between attempts.
        Thread-safe: guarded by an internal asyncio lock to prevent concurrent
        pool creation.

        Raises:
            ConnectionError: If all retry attempts are exhausted.
        """
        async with self._connection_lock:
            if self._is_connected:
                return

            db = self._config.database

            self._logger.info(
                "connection_starting",
                host=db.host,
                port=db.port,
                database=db.database,
            )

            for attempt in range(self._config.retry.max_attempts):
                try:
                    self._pool = await asyncpg.create_pool(
                        host=db.host,
                        port=db.port,
                        database=db.database,
                        user=db.user,
                        password=db.password.get_secret_value(),
                        min_size=self._config.limits.min_size,
                        max_size=self._config.limits.max_size,
                        max_queries=self._config.limits.max_queries,
                        max_inactive_connection_lifetime=self._config.limits.max_inactive_connection_lifetime,
                        timeout=self._config.timeouts.acquisition,
                        init=_init_connection,
                        server_settings={
                            "application_name": self._config.server_settings.application_name,
                            "timezone": self._config.server_settings.timezone,
                            "statement_timeout": str(
                                self._config.server_settings.statement_timeout
                            ),
                        },
                    )
                    self._is_connected = True
                    self._logger.info("connection_established")
                    return

                except (asyncpg.PostgresError, OSError, ConnectionError) as e:
                    if attempt + 1 >= self._config.retry.max_attempts:
                        self._logger.error(
                            "connection_failed",
                            attempts=attempt + 1,
                            error=str(e),
                        )
                        raise ConnectionError(
                            f"Failed to connect after {attempt + 1} attempts: {e}"
                        ) from e

                    delay = self._retry_delay(attempt)
                    self._logger.warning(
                        "connection_retry",
                        attempt=attempt + 1,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)

    async def close(self) -> None:
        """Close the pool and release all connections.

        Idempotent: safe to call multiple times. Always resets internal
        state even if the underlying close raises an exception.
        """
        async with self._connection_lock:
            if self._pool is not None:
                try:
                    await self._pool.close()
                    self._logger.info("connection_closed")
                finally:
                    self._pool = None
                    self._is_connected = False

    # -------------------------------------------------------------------------
    # Connection Acquisition
    # -------------------------------------------------------------------------

    def acquire(self) -> AbstractAsyncContextManager[asyncpg.Connection[asyncpg.Record]]:
        """Acquire a connection from the pool.

        Returns an async context manager; the connection is automatically
        returned to the pool when the context exits.

        Raises:
            RuntimeError: If the pool has not been connected yet.

        Example:
            async with pool.acquire() as conn:
                result = await conn.fetch("SELECT * FROM events")
        """
        if not self._is_connected or self._pool is None:
            raise RuntimeError("Pool not connected. Call connect() first.")
        # asyncpg's PoolAcquireContext is duck-type compatible with AbstractAsyncContextManager
        return cast(
            "AbstractAsyncContextManager[asyncpg.Connection[asyncpg.Record]]",
            self._pool.acquire(),
        )

    @asynccontextmanager
    async def acquire_healthy(
        self,
        max_retries: int | None = None,
        health_check_timeout: float | None = None,
    ) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
        """Acquire a connection that has passed a ``SELECT 1`` health check.

        Validates each acquired connection before yielding it. On failure,
        retries with exponential backoff to avoid overwhelming the database.

        Args:
            max_retries: Maximum attempts to acquire a healthy connection.
                Defaults to ``_DEFAULT_MAX_RETRIES``.
            health_check_timeout: Timeout in seconds for the health check
                query. Defaults to the configured ``timeouts.health_check``.

        Raises:
            RuntimeError: If the pool has not been connected yet.
            ConnectionError: If no healthy connection can be acquired
                after all retry attempts.
        """
        if not self._is_connected or self._pool is None:
            raise RuntimeError("Pool not connected. Call connect() first.")

        if max_retries is None:
            max_retries = self._config.retry.max_attempts
        if health_check_timeout is None:
            health_check_timeout = self._config.timeouts.health_check
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                async with self._pool.acquire() as conn:
                    # Validate the connection is responsive
                    await conn.fetchval("SELECT 1", timeout=health_check_timeout)
                    # PoolConnectionProxy is duck-type compatible with Connection
                    yield cast("asyncpg.Connection[asyncpg.Record]", conn)
                    return
            except (asyncpg.PostgresError, OSError, TimeoutError) as e:
                last_error = e
                self._logger.debug(
                    "health_check_failed",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(e),
                )
                # Exponential backoff between retries to avoid thundering herd
                if attempt < max_retries - 1:
                    await asyncio.sleep(self._retry_delay(attempt))
                continue

        raise ConnectionError(
            f"Failed to acquire healthy connection after {max_retries} attempts: {last_error}"
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
        """Acquire a connection with an active database transaction.

        The transaction commits automatically on normal exit and rolls back
        if an exception propagates out of the context manager.

        Raises:
            RuntimeError: If the pool has not been connected yet.
            asyncpg.PostgresError: On database errors (triggers rollback).

        Example:
            async with pool.transaction() as conn:
                await conn.execute("INSERT INTO events ...")
                await conn.execute("INSERT INTO relays ...")
                # Both succeed together or roll back on error.
        """
        async with self.acquire() as conn, conn.transaction():
            yield conn

    # -------------------------------------------------------------------------
    # Query Methods (with retry for transient connection errors)
    # -------------------------------------------------------------------------

    async def _execute_with_retry(
        self,
        operation: Literal["fetch", "fetchrow", "fetchval", "execute"],
        query: str,
        args: tuple[Any, ...],
        timeout: float | None,  # noqa: ASYNC109
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute a named asyncpg operation with retry on transient errors.

        Retries only on connection-level errors (InterfaceError,
        ConnectionDoesNotExistError) with exponential backoff. Query-level
        errors (syntax, constraint violations) propagate immediately.

        Args:
            operation: Name of the asyncpg connection method (e.g. "fetch").
            query: SQL query string with $1, $2, ... placeholders.
            args: Positional query parameters.
            timeout: Query timeout in seconds (None = no timeout).
            max_retries: Override the default retry count.
            **kwargs: Additional keyword arguments passed to the operation.

        Returns:
            The result of the asyncpg operation.
        """
        if max_retries is None:
            max_retries = self._config.retry.max_attempts
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                async with self.acquire() as conn:
                    method = getattr(conn, operation)
                    return await method(query, *args, timeout=timeout, **kwargs)
            except (
                asyncpg.InterfaceError,
                asyncpg.ConnectionDoesNotExistError,
            ) as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = self._retry_delay(attempt)
                    self._logger.warning(
                        "query_retry",
                        operation=operation,
                        attempt=attempt + 1,
                        delay_s=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                    continue
                self._logger.error(
                    "query_failed",
                    operation=operation,
                    attempts=max_retries,
                    error=str(e),
                )
                raise

        # Unreachable in practice, but satisfies the type checker
        if last_error:
            raise last_error
        raise RuntimeError("Unexpected state in _execute_with_retry")

    async def fetch(
        self,
        query: str,
        *args: Any,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> list[asyncpg.Record]:
        """Execute a query and return all matching rows.

        Args:
            query: SQL query with $1, $2, ... placeholders.
            *args: Query parameters.
            timeout: Query timeout in seconds (None = no timeout).

        Returns:
            List of asyncpg Record objects. Empty list if no rows match.
        """
        result = await self._execute_with_retry("fetch", query, args, timeout)
        # Dynamic dispatch returns Any; narrow to the actual fetch() return type
        return cast("list[asyncpg.Record]", result)

    async def fetchrow(
        self,
        query: str,
        *args: Any,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> asyncpg.Record | None:
        """Execute a query and return the first row.

        Args:
            query: SQL query with $1, $2, ... placeholders.
            *args: Query parameters.
            timeout: Query timeout in seconds (None = no timeout).

        Returns:
            A single asyncpg Record, or None if the query returns no rows.
        """
        result = await self._execute_with_retry("fetchrow", query, args, timeout)
        # Dynamic dispatch returns Any; narrow to the actual fetchrow() return type
        return cast("asyncpg.Record | None", result)

    async def fetchval(
        self,
        query: str,
        *args: Any,
        column: int = 0,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> Any:
        """Execute a query and return a single scalar value.

        Args:
            query: SQL query with $1, $2, ... placeholders.
            *args: Query parameters.
            column: Zero-based column index to extract (default: 0).
            timeout: Query timeout in seconds (None = no timeout).

        Returns:
            The value from the specified column of the first row,
            or None if the query returns no rows.
        """
        return await self._execute_with_retry("fetchval", query, args, timeout, column=column)

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:  # noqa: ASYNC109
        """Execute a query and return the command status tag.

        Args:
            query: SQL query with $1, $2, ... placeholders.
            *args: Query parameters.
            timeout: Query timeout in seconds (None = no timeout).

        Returns:
            PostgreSQL command status string (e.g. "INSERT 0 1", "UPDATE 5").
        """
        result = await self._execute_with_retry("execute", query, args, timeout)
        # Dynamic dispatch returns Any; narrow to the actual execute() return type
        return cast("str", result)

    async def executemany(
        self,
        query: str,
        args_list: list[tuple[Any, ...]],
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> None:
        """Execute a query repeatedly with different parameter sets.

        Implemented separately from ``_execute_with_retry`` because asyncpg's
        ``executemany`` accepts an iterable of argument tuples rather than
        variadic positional args.

        Args:
            query: SQL query with $1, $2, ... placeholders.
            args_list: List of parameter tuples, one per execution.
            timeout: Query timeout in seconds (None = no timeout).
        """
        max_retries = self._config.retry.max_attempts
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                async with self.acquire() as conn:
                    await conn.executemany(query, args_list, timeout=timeout)
                    return
            except (
                asyncpg.InterfaceError,
                asyncpg.ConnectionDoesNotExistError,
            ) as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = self._retry_delay(attempt)
                    self._logger.warning(
                        "query_retry",
                        operation="executemany",
                        attempt=attempt + 1,
                        delay_s=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                    continue
                self._logger.error(
                    "query_failed",
                    operation="executemany",
                    attempts=max_retries,
                    error=str(e),
                )
                raise

        if last_error:
            raise last_error

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """Whether the pool has an active connection to the database."""
        return self._is_connected

    @property
    def config(self) -> PoolConfig:
        """The pool configuration (read-only)."""
        return self._config

    @property
    def metrics(self) -> dict[str, Any]:
        """Snapshot of pool statistics for monitoring dashboards.

        Returns:
            Dictionary with keys: ``size``, ``idle_size``, ``min_size``,
            ``max_size``, ``free_size``, ``utilization`` (0.0-1.0),
            and ``is_connected``. Returns zeroed metrics if the pool
            is not connected.
        """
        disconnected = {
            "size": 0,
            "idle_size": 0,
            "min_size": self._config.limits.min_size,
            "max_size": self._config.limits.max_size,
            "free_size": 0,
            "utilization": 0.0,
            "is_connected": False,
        }

        # Local reference prevents race with concurrent close() calls
        pool = self._pool
        if not self._is_connected or pool is None:
            return disconnected

        try:
            size = pool.get_size()
            idle_size = pool.get_idle_size()
            min_size = pool.get_min_size()
            max_size = pool.get_max_size()
            free_size = max_size - (size - idle_size)
            utilization = (size - idle_size) / max_size if max_size > 0 else 0.0

            return {
                "size": size,
                "idle_size": idle_size,
                "min_size": min_size,
                "max_size": max_size,
                "free_size": free_size,
                "utilization": round(utilization, 3),
                "is_connected": True,
            }
        except asyncpg.InterfaceError:
            # Pool was closed between the check and the method calls
            return disconnected
        except Exception as e:
            # Log unexpected errors but never crash the monitoring path
            self._logger.warning("metrics_error", error=str(e))
            return disconnected

    # -------------------------------------------------------------------------
    # Context Manager
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> Pool:
        """Connect the pool on context entry."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        """Close the pool on context exit."""
        await self.close()

    def __repr__(self) -> str:
        """Return a human-readable representation with host and connection status."""
        db = self._config.database
        return f"Pool(host={db.host}, database={db.database}, connected={self._is_connected})"
