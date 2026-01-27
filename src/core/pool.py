"""
PostgreSQL Connection Pool using asyncpg.

Manages database connections with:
- Async pooling with configurable sizes
- Automatic retry with exponential backoff
- PGBouncer compatibility
- Structured logging
- Context manager support
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, ClassVar

import asyncpg
from pydantic import BaseModel, Field, SecretStr, ValidationInfo, field_validator, model_validator

from utils.yaml import load_yaml

from .logger import Logger


async def _init_connection(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    """
    Initialize connection with JSON codecs for JSONB support.

    Registers custom type codecs that enable transparent serialization and
    deserialization of Python dicts to PostgreSQL JSON/JSONB types. Without
    these codecs, asyncpg would require manual JSON encoding/decoding for
    every query involving JSON columns.

    This allows passing Python dicts directly as query parameters and
    receiving them back as dicts from query results, eliminating the need
    for explicit json.dumps()/json.loads() calls throughout the codebase.

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


# ============================================================================
# Configuration Models
# ============================================================================


class DatabaseConfig(BaseModel):
    """Database connection configuration."""

    host: str = Field(default="localhost", min_length=1, description="Database hostname")
    port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    database: str = Field(default="bigbrotr", min_length=1, description="Database name")
    user: str = Field(default="admin", min_length=1, description="Database user")
    password: SecretStr = Field(
        default=None,  # type: ignore[assignment]
        description="Database password (from DB_PASSWORD env if not provided)",
    )

    @model_validator(mode="after")
    def resolve_password(self) -> DatabaseConfig:
        """Load password from DB_PASSWORD environment variable if not provided."""
        if self.password is not None:
            return self
        value = os.getenv("DB_PASSWORD")  # pragma: allowlist secret
        if not value:
            raise ValueError("DB_PASSWORD environment variable not set")
        # Use object.__setattr__ to bypass Pydantic's frozen model protection
        object.__setattr__(self, "password", SecretStr(value))
        return self


class LimitsConfig(BaseModel):
    """Pool size and resource limits."""

    min_size: int = Field(default=5, ge=1, le=100, description="Minimum connections")
    max_size: int = Field(default=20, ge=1, le=200, description="Maximum connections")
    max_queries: int = Field(default=50000, ge=100, description="Queries before recycling")
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
    """Pool timeout configuration."""

    acquisition: float = Field(default=10.0, ge=0.1, description="Connection acquisition timeout")
    health_check: float = Field(default=5.0, ge=0.1, description="Health check timeout")


class RetryConfig(BaseModel):
    """Retry configuration for connection failures."""

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
    """PostgreSQL server settings."""

    application_name: str = Field(default="bigbrotr", description="Application name")
    timezone: str = Field(default="UTC", description="Timezone")
    statement_timeout: int = Field(
        default=300000, ge=0, description="Max query execution time in milliseconds (0=unlimited)"
    )


class PoolConfig(BaseModel):
    """Complete pool configuration."""

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    server_settings: ServerSettingsConfig = Field(default_factory=ServerSettingsConfig)


# ============================================================================
# Pool Class
# ============================================================================


class Pool:
    """
    PostgreSQL connection pool manager.

    Features:
    - Async connection pooling with asyncpg
    - Automatic retry with exponential backoff
    - Structured logging
    - Context manager support

    Usage:
        pool = Pool.from_yaml("config.yaml")

        async with pool:
            result = await pool.fetch("SELECT * FROM events LIMIT 10")

            async with pool.transaction() as conn:
                await conn.execute("INSERT INTO ...")
    """

    _DEFAULT_RETRY_BASE_DELAY: ClassVar[float] = 0.1  # seconds, for exponential backoff
    _DEFAULT_MAX_RETRIES: ClassVar[int] = 3

    def __init__(self, config: PoolConfig | None = None) -> None:
        """
        Initialize pool.

        Args:
            config: Pool configuration (uses defaults if not provided)
        """
        self._config = config or PoolConfig()
        self._pool: asyncpg.Pool[asyncpg.Record] | None = None
        self._is_connected: bool = False
        self._connection_lock = asyncio.Lock()
        self._logger = Logger("pool")

    @classmethod
    def from_yaml(cls, config_path: str) -> Pool:
        """
        Create pool from YAML configuration file.

        Args:
            config_path: Path to YAML configuration file

        Returns:
            Pool instance configured from file

        Raises:
            FileNotFoundError: If config file does not exist
        """
        return cls.from_dict(load_yaml(config_path))

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> Pool:
        """
        Create pool from dictionary configuration.

        Args:
            config_dict: Configuration dictionary with pool settings

        Returns:
            Pool instance configured from dictionary
        """
        config = PoolConfig(**config_dict)
        return cls(config=config)

    # -------------------------------------------------------------------------
    # Connection Lifecycle
    # -------------------------------------------------------------------------

    async def connect(self) -> None:
        """
        Establish pool with retry logic.

        Raises:
            ConnectionError: If all retry attempts fail
        """
        async with self._connection_lock:
            if self._is_connected:
                return

            attempt = 0
            delay = self._config.retry.initial_delay
            db = self._config.database

            self._logger.info(
                "connection_starting",
                host=db.host,
                port=db.port,
                database=db.database,
            )

            while attempt < self._config.retry.max_attempts:
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
                    attempt += 1
                    if attempt >= self._config.retry.max_attempts:
                        self._logger.error(
                            "connection_failed",
                            attempts=attempt,
                            error=str(e),
                        )
                        raise ConnectionError(
                            f"Failed to connect after {attempt} attempts: {e}"
                        ) from e

                    self._logger.warning(
                        "connection_retry",
                        attempt=attempt,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)

                    if self._config.retry.exponential_backoff:
                        delay = min(delay * 2, self._config.retry.max_delay)
                    else:
                        delay = min(
                            delay + self._config.retry.initial_delay, self._config.retry.max_delay
                        )

    async def close(self) -> None:
        """
        Close pool and release all connections.

        Safe to call multiple times. Logs closure status.
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
        """
        Acquire a connection from the pool.

        Returns:
            An async context manager that yields an asyncpg Connection.
            The connection is automatically returned to the pool when
            the context manager exits.

        Raises:
            RuntimeError: If pool is not connected.

        Example:
            async with pool.acquire() as conn:
                result = await conn.fetch("SELECT * FROM events")
        """
        if not self._is_connected or self._pool is None:
            raise RuntimeError("Pool not connected. Call connect() first.")
        return self._pool.acquire()

    @asynccontextmanager
    async def acquire_healthy(
        self,
        max_retries: int | None = None,
        health_check_timeout: float | None = None,
    ) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
        """
        Acquire a health-checked connection.

        Validates connection health before returning. Retries on failure.

        Args:
            max_retries: Max attempts to acquire healthy connection
            health_check_timeout: Timeout for health check query

        Raises:
            RuntimeError: If pool is not connected
            ConnectionError: If all retry attempts fail
        """
        if not self._is_connected or self._pool is None:
            raise RuntimeError("Pool not connected. Call connect() first.")

        if max_retries is None:
            max_retries = self._DEFAULT_MAX_RETRIES
        if health_check_timeout is None:
            health_check_timeout = self._config.timeouts.health_check
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                async with self._pool.acquire() as conn:
                    # Health check - if fails, will raise and retry
                    await conn.fetchval("SELECT 1", timeout=health_check_timeout)
                    # Connection is healthy, yield it
                    yield conn
                    return
            except (asyncpg.PostgresError, OSError, TimeoutError) as e:
                last_error = e
                self._logger.debug(
                    "health_check_failed",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(e),
                )
                # Add backoff delay between retries to avoid thundering herd
                if attempt < max_retries - 1:
                    delay = self._DEFAULT_RETRY_BASE_DELAY * (2**attempt)
                    await asyncio.sleep(delay)
                continue

        raise ConnectionError(
            f"Failed to acquire healthy connection after {max_retries} attempts: {last_error}"
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
        """
        Acquire connection with transaction management.

        Provides a connection wrapped in a database transaction. The
        transaction is automatically committed when the context manager
        exits normally, or rolled back if an exception occurs.

        Returns:
            An async context manager that yields an asyncpg Connection
            with an active transaction.

        Raises:
            RuntimeError: If pool is not connected.
            asyncpg.PostgresError: On database errors (triggers rollback).

        Example:
            async with pool.transaction() as conn:
                await conn.execute("INSERT INTO events ...")
                await conn.execute("INSERT INTO relays ...")
                # Both inserts commit together, or rollback on error
        """
        async with self.acquire() as conn, conn.transaction():
            yield conn

    # -------------------------------------------------------------------------
    # Query Methods (with retry for transient connection errors)
    # -------------------------------------------------------------------------

    async def _execute_with_retry(
        self,
        operation: str,
        query: str,
        args: tuple[Any, ...],
        timeout: float | None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a query operation with retry logic for transient errors.

        Retries on connection errors (InterfaceError, ConnectionDoesNotExistError)
        with exponential backoff. Does NOT retry on query errors (syntax, constraint).
        """
        if max_retries is None:
            max_retries = self._DEFAULT_MAX_RETRIES
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
                    delay = self._DEFAULT_RETRY_BASE_DELAY * (2**attempt)
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

        # Should not reach here, but satisfy type checker
        if last_error:
            raise last_error
        raise RuntimeError("Unexpected state in _execute_with_retry")

    async def fetch(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> list[asyncpg.Record]:
        """
        Execute query and fetch all results.

        Retries on transient connection errors with exponential backoff.

        Args:
            query: SQL query string with $1, $2, ... placeholders
            *args: Query parameters
            timeout: Query timeout in seconds (None = no timeout)

        Returns:
            List of Record objects (may be empty)
        """
        return await self._execute_with_retry("fetch", query, args, timeout)

    async def fetchrow(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> asyncpg.Record | None:
        """
        Execute query and fetch single row.

        Retries on transient connection errors with exponential backoff.

        Args:
            query: SQL query string with $1, $2, ... placeholders
            *args: Query parameters
            timeout: Query timeout in seconds (None = no timeout)

        Returns:
            Single Record or None if no rows
        """
        return await self._execute_with_retry("fetchrow", query, args, timeout)

    async def fetchval(
        self, query: str, *args: Any, column: int = 0, timeout: float | None = None
    ) -> Any:
        """
        Execute query and fetch single value.

        Retries on transient connection errors with exponential backoff.

        Args:
            query: SQL query string with $1, $2, ... placeholders
            *args: Query parameters
            column: Column index to fetch (default: 0)
            timeout: Query timeout in seconds (None = no timeout)

        Returns:
            Single value from first row, or None if no rows
        """
        return await self._execute_with_retry("fetchval", query, args, timeout, column=column)

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:
        """
        Execute query without returning results.

        Retries on transient connection errors with exponential backoff.

        Args:
            query: SQL query string with $1, $2, ... placeholders
            *args: Query parameters
            timeout: Query timeout in seconds (None = no timeout)

        Returns:
            Status string (e.g., "INSERT 0 1", "UPDATE 5")
        """
        return await self._execute_with_retry("execute", query, args, timeout)

    async def executemany(
        self, query: str, args_list: list[tuple[Any, ...]], timeout: float | None = None
    ) -> None:
        """
        Execute query multiple times with different parameters.

        Retries on transient connection errors with exponential backoff.

        Args:
            query: SQL query string with $1, $2, ... placeholders
            args_list: List of parameter tuples for each execution
            timeout: Query timeout in seconds (None = no timeout)
        """
        max_retries = self._DEFAULT_MAX_RETRIES
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
                    delay = self._DEFAULT_RETRY_BASE_DELAY * (2**attempt)
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
        """Check if pool is connected."""
        return self._is_connected

    @property
    def config(self) -> PoolConfig:
        """Get configuration."""
        return self._config

    @property
    def metrics(self) -> dict[str, Any]:
        """
        Get pool metrics for monitoring.

        Returns:
            Dictionary with pool statistics:
            - size: Current number of connections in pool
            - idle_size: Number of idle (available) connections
            - min_size: Configured minimum pool size
            - max_size: Configured maximum pool size
            - free_size: Number of connections available for acquisition
            - utilization: Percentage of pool in use (0.0-1.0)
            - is_connected: Whether pool is connected

        Example:
            >>> pool.metrics
            {'size': 10, 'idle_size': 8, 'min_size': 5, 'max_size': 20,
             'free_size': 8, 'utilization': 0.2, 'is_connected': True}
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

        # Capture local reference to avoid race condition with close()
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
            # Expected: pool was closed between check and access
            return disconnected
        except Exception as e:
            # Unexpected error - log but don't crash monitoring
            self._logger.warning("metrics_error", error=str(e))
            return disconnected

    # -------------------------------------------------------------------------
    # Context Manager
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> Pool:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        """Async context manager exit."""
        await self.close()

    def __repr__(self) -> str:
        """String representation."""
        db = self._config.database
        return f"Pool(host={db.host}, database={db.database}, connected={self._is_connected})"
