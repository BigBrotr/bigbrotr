"""
Async PostgreSQL connection pool built on asyncpg.

Manages a pool of database connections with configurable size limits, automatic
retry with exponential backoff on connection failures, health-checked connection
acquisition, and transactional context managers. Compatible with PGBouncer for
connection multiplexing in containerized deployments.

All query methods ([fetch()][bigbrotr.core.pool.Pool.fetch],
[fetchrow()][bigbrotr.core.pool.Pool.fetchrow],
[fetchval()][bigbrotr.core.pool.Pool.fetchval],
[execute()][bigbrotr.core.pool.Pool.execute]) retry automatically on
transient connection errors (``InterfaceError``,
``ConnectionDoesNotExistError``) but do not retry on query-level errors such as
syntax errors or constraint violations.

Examples:
    ```python
    pool = Pool.from_yaml("config.yaml")

    async with pool:
        rows = await pool.fetch("SELECT * FROM relay LIMIT 10")

        async with pool.transaction() as conn:
            await conn.execute("INSERT INTO relay ...")
    ```

See Also:
    [Brotr][bigbrotr.core.brotr.Brotr]: High-level database facade that wraps
        this pool and exposes domain-specific insert/query methods.
    [PoolConfig][bigbrotr.core.pool.PoolConfig]: Aggregate configuration grouping
        all pool-related settings.
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

from .logger import Logger
from .yaml import load_yaml


def _json_encode(value: Any) -> str:
    """Encode a Python value to JSON for PostgreSQL.

    Handles both pre-serialized JSON strings (from model ``to_db_params()``)
    and Python objects (dicts, lists) transparently. This allows the same
    codec to work correctly for both:

    * Direct dict/list values (e.g., ``service_state.state_value``)
    * Pre-serialized JSON strings (e.g., ``event.tags``, ``metadata.data``)

    Without this, ``json.dumps(string)`` double-encodes pre-serialized JSON.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value)


async def _init_connection(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    """Register JSON/JSONB codecs on a new connection.

    Called automatically by asyncpg for each new connection in the pool.
    Enables transparent serialization of Python dicts to PostgreSQL JSON/JSONB
    columns and deserialization back to dicts, so callers never need to call
    ``json.dumps()``/``json.loads()`` manually.

    Uses ``_json_encode`` instead of raw ``json.dumps`` to handle
    pre-serialized JSON strings without double-encoding.

    Args:
        conn: The asyncpg connection to configure.
    """
    await conn.set_type_codec(
        "jsonb",
        encoder=_json_encode,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=_json_encode,
        decoder=json.loads,
        schema="pg_catalog",
    )


# ---------------------------------------------------------------------------
# Configuration Models
# ---------------------------------------------------------------------------


class DatabaseConfig(BaseModel):
    """PostgreSQL connection parameters.

    The password is loaded from the environment variable named by
    ``password_env`` (default: ``DB_ADMIN_PASSWORD``). It is never read from
    configuration files directly.

    Warning:
        The ``password`` field is a ``SecretStr`` and will never appear in
        string representations or serialized output. Ensure the environment
        variable named by ``password_env`` is set before constructing this
        model.

    See Also:
        [PoolConfig][bigbrotr.core.pool.PoolConfig]: Parent configuration that
            embeds this model.
    """

    host: str = Field(default="localhost", min_length=1, description="Database hostname")
    port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    database: str = Field(default="bigbrotr", min_length=1, description="Database name")
    user: str = Field(default="admin", min_length=1, description="Database user")
    password_env: str = Field(
        default="DB_ADMIN_PASSWORD",  # pragma: allowlist secret
        min_length=1,
        description="Environment variable name for database password",
    )
    password: SecretStr = Field(description="Database password (loaded from password_env)")

    @model_validator(mode="before")
    @classmethod
    def resolve_password(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Resolve the database password from the environment variable."""
        if isinstance(data, dict) and "password" not in data:
            env_var = data.get("password_env", "DB_ADMIN_PASSWORD")  # pragma: allowlist secret
            value = os.getenv(env_var)
            if not value:
                raise ValueError(f"{env_var} environment variable not set")
            data["password"] = SecretStr(value)
        return data


class PoolLimitsConfig(BaseModel):
    """Connection pool size and resource limits.

    Controls the minimum and maximum number of connections maintained by
    the pool, the query count before a connection is recycled, and the
    idle timeout before an unused connection is closed.

    Note:
        ``max_queries`` triggers connection recycling to prevent memory leaks in
        long-lived connections. The default of 50,000 queries balances connection
        reuse against the overhead of establishing new connections.

    See Also:
        [PoolConfig][bigbrotr.core.pool.PoolConfig]: Parent configuration that
            embeds this model.
    """

    min_size: int = Field(default=2, ge=1, le=100, description="Minimum connections")
    max_size: int = Field(default=20, ge=1, le=200, description="Maximum connections")
    max_queries: int = Field(default=50_000, ge=100, description="Queries before recycling")
    max_inactive_connection_lifetime: float = Field(
        default=300.0, ge=0.0, description="Idle timeout (seconds)"
    )

    @field_validator("max_size")
    @classmethod
    def validate_max_size(cls, v: int, info: ValidationInfo) -> int:
        """Ensure max_size >= min_size."""
        min_size = info.data.get("min_size", 2)
        if v < min_size:
            raise ValueError(f"max_size ({v}) must be >= min_size ({min_size})")
        return v


class PoolTimeoutsConfig(BaseModel):
    """Timeout settings for pool operations (in seconds).

    See Also:
        [BrotrTimeoutsConfig][bigbrotr.core.brotr.BrotrTimeoutsConfig]: Higher-level
            timeouts for query, batch, cleanup, and refresh operations.
        [PoolConfig][bigbrotr.core.pool.PoolConfig]: Parent configuration that
            embeds this model.
    """

    acquisition: float = Field(default=10.0, ge=0.1, description="Connection acquisition timeout")


class PoolRetryConfig(BaseModel):
    """Retry strategy for failed connection attempts.

    Supports both exponential and linear backoff between retries.

    Note:
        Exponential backoff (the default) doubles the delay each attempt:
        ``initial_delay * 2^attempt``, capped at ``max_delay``. Linear backoff
        increases linearly: ``initial_delay * (attempt + 1)``. Exponential
        backoff is preferred for production to reduce thundering-herd effects
        during database recovery.

    See Also:
        [PoolConfig][bigbrotr.core.pool.PoolConfig]: Parent configuration that
            embeds this model.
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

    Note:
        ``statement_timeout`` is specified in milliseconds (PostgreSQL convention)
        and acts as a safety net against runaway queries. Set to ``0`` to disable.
        This is distinct from the per-query ``timeout`` parameter on
        [Pool][bigbrotr.core.pool.Pool] methods, which is enforced client-side
        by asyncpg.

    See Also:
        [PoolConfig][bigbrotr.core.pool.PoolConfig]: Parent configuration that
            embeds this model.
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

    See Also:
        [DatabaseConfig][bigbrotr.core.pool.DatabaseConfig]: PostgreSQL
            connection credentials.
        [PoolLimitsConfig][bigbrotr.core.pool.PoolLimitsConfig]: Min/max connections and
            recycling thresholds.
        [PoolTimeoutsConfig][bigbrotr.core.pool.PoolTimeoutsConfig]: Acquisition
            and health-check timeouts.
        [PoolRetryConfig][bigbrotr.core.pool.PoolRetryConfig]: Backoff strategy
            for connection failures.
        [ServerSettingsConfig][bigbrotr.core.pool.ServerSettingsConfig]: PostgreSQL
            session-level settings.
        [Pool][bigbrotr.core.pool.Pool]: The pool class that consumes this
            configuration.
    """

    database: DatabaseConfig = Field(default_factory=lambda: DatabaseConfig.model_validate({}))
    limits: PoolLimitsConfig = Field(default_factory=PoolLimitsConfig)
    timeouts: PoolTimeoutsConfig = Field(default_factory=PoolTimeoutsConfig)
    retry: PoolRetryConfig = Field(default_factory=PoolRetryConfig)
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
    [PoolConfig][bigbrotr.core.pool.PoolConfig] object, or factory methods
    [from_yaml()][bigbrotr.core.pool.Pool.from_yaml] /
    [from_dict()][bigbrotr.core.pool.Pool.from_dict] for configuration-driven
    setup.

    Examples:
        ```python
        pool = Pool.from_yaml("config.yaml")

        async with pool:
            rows = await pool.fetch("SELECT * FROM event LIMIT 10")

            async with pool.transaction() as conn:
                await conn.execute("INSERT INTO ...")
        ```

    Note:
        Services should never use ``Pool`` directly for domain operations.
        Instead, use [Brotr][bigbrotr.core.brotr.Brotr] which wraps a private
        ``Pool`` instance and provides typed insert/query methods. ``Pool`` is
        exposed for advanced use cases such as custom health checks or direct
        SQL access outside the stored-procedure layer.

    See Also:
        [Brotr][bigbrotr.core.brotr.Brotr]: High-level database facade that
            wraps this pool.
        [PoolConfig][bigbrotr.core.pool.PoolConfig]: Full configuration model
            for this class.
        [DatabaseConfig][bigbrotr.core.pool.DatabaseConfig]: Connection
            credential subset of the configuration.
    """

    def __init__(self, config: PoolConfig | None = None) -> None:
        """Initialize pool with optional configuration.

        The pool is created in a disconnected state. Call
        [connect()][bigbrotr.core.pool.Pool.connect] or use the async
        context manager to establish the connection.

        Args:
            config: Pool configuration. If not provided, uses defaults
                which read ``DB_ADMIN_PASSWORD`` from the environment.

        See Also:
            [from_yaml()][bigbrotr.core.pool.Pool.from_yaml]: Construct from
                a YAML file.
            [from_dict()][bigbrotr.core.pool.Pool.from_dict]: Construct from
                a dictionary.
        """
        self._config = config or PoolConfig()
        self._pool: asyncpg.Pool[asyncpg.Record] | None = None
        self._is_connected: bool = False
        self._connection_lock = asyncio.Lock()
        self._logger = Logger("pool")

    @classmethod
    def from_yaml(cls, config_path: str) -> Pool:
        """Create a Pool from a YAML configuration file.

        Delegates to [load_yaml()][bigbrotr.core.yaml.load_yaml] for safe
        YAML parsing, then to
        [from_dict()][bigbrotr.core.pool.Pool.from_dict] for construction.

        Args:
            config_path: Path to the YAML configuration file.

        Returns:
            A configured Pool instance (not yet connected).

        Raises:
            FileNotFoundError: If the configuration file does not exist.

        See Also:
            [from_dict()][bigbrotr.core.pool.Pool.from_dict]: Construct from
                a pre-parsed dictionary.
        """
        return cls.from_dict(load_yaml(config_path))

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> Pool:
        """Create a Pool from a configuration dictionary.

        Args:
            config_dict: Dictionary with pool settings matching
                [PoolConfig][bigbrotr.core.pool.PoolConfig] field names.

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

        Uses exponential or linear backoff (per
        [PoolRetryConfig][bigbrotr.core.pool.PoolRetryConfig]) between
        attempts. Thread-safe: guarded by an internal asyncio lock to prevent
        concurrent pool creation.

        Raises:
            ConnectionError: If all retry attempts are exhausted.

        Note:
            The retry strategy uses exponential backoff by default
            (``initial_delay * 2^attempt``, capped at ``max_delay``) to
            avoid overwhelming a recovering database. Each new connection
            is initialized with JSON/JSONB codecs via ``_init_connection``
            for transparent dict serialization.
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

        Returns an async context manager that yields a connection. The
        connection is automatically returned to the pool when the context
        exits.

        Yields:
            An asyncpg connection from the pool.

        Raises:
            RuntimeError: If the pool has not been connected yet.

        Examples:
            ```python
            async with pool.acquire() as conn:
                result = await conn.fetch("SELECT * FROM event")
            ```

        See Also:
            [transaction()][bigbrotr.core.pool.Pool.transaction]: Acquire
                with an active database transaction.
        """
        if not self._is_connected or self._pool is None:
            raise RuntimeError("Pool not connected. Call connect() first.")
        # asyncpg's PoolAcquireContext is duck-type compatible with AbstractAsyncContextManager
        return cast(
            "AbstractAsyncContextManager[asyncpg.Connection[asyncpg.Record]]",
            self._pool.acquire(),
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
        """Acquire a connection with an active database transaction.

        The transaction commits automatically on normal exit and rolls back
        if an exception propagates out of the context manager.

        Yields:
            An asyncpg connection with an active transaction. The
            transaction commits on normal exit and rolls back on exception.

        Raises:
            RuntimeError: If the pool has not been connected yet.
            asyncpg.PostgresError: On database errors (triggers rollback).

        Examples:
            ```python
            async with pool.transaction() as conn:
                await conn.execute("INSERT INTO event ...")
                await conn.execute("INSERT INTO relay ...")
                # Both succeed together or roll back on error.
            ```

        See Also:
            [acquire()][bigbrotr.core.pool.Pool.acquire]: Acquire without
                a transaction (auto-commit mode).
            [Brotr.transaction()][bigbrotr.core.brotr.Brotr.transaction]:
                Higher-level facade that delegates to this method.
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
        max_attempts: int | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute a named asyncpg operation with retry on transient errors.

        Retries only on connection-level errors (``InterfaceError``,
        ``ConnectionDoesNotExistError``) with exponential backoff. Query-level
        errors (syntax, constraint violations) propagate immediately.

        Args:
            operation: Name of the asyncpg connection method (e.g. ``"fetch"``).
            query: SQL query string with ``$1``, ``$2``, ... placeholders.
            args: Positional query parameters.
            timeout: Query timeout in seconds (``None`` = no timeout).
            max_attempts: Override the default retry count from
                [PoolRetryConfig][bigbrotr.core.pool.PoolRetryConfig].
            **kwargs: Additional keyword arguments passed to the operation.

        Returns:
            The result of the asyncpg operation.

        Note:
            This method acquires a fresh connection for each retry attempt.
            If the connection was broken mid-query, the new attempt uses a
            different connection from the pool, avoiding repeated failures
            on the same socket.
        """
        if max_attempts is None:
            max_attempts = self._config.retry.max_attempts
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                async with self.acquire() as conn:
                    method = getattr(conn, operation)
                    return await method(query, *args, timeout=timeout, **kwargs)
            except (
                asyncpg.InterfaceError,
                asyncpg.ConnectionDoesNotExistError,
            ) as e:
                last_error = e
                if attempt < max_attempts - 1:
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
                    attempts=max_attempts,
                    error=str(e),
                )
                raise ConnectionError(
                    f"{operation} failed after {max_attempts} attempts: {e}"
                ) from e

        # Unreachable in practice, but satisfies the type checker
        if last_error:
            raise ConnectionError(str(last_error)) from last_error
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
