"""
Pool Manager for PostgreSQL using asyncpg.

This module provides a Pool class that manages PostgreSQL
connections using asyncpg with advanced features like automatic retries,
PGBouncer compatibility, and configuration validation via Pydantic.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import asyncpg
import yaml
from pydantic import BaseModel, Field, field_validator

# ============================================================================
# Pydantic Models for Configuration Validation
# ============================================================================


class DatabaseConfig(BaseModel):
    """Database connection configuration."""

    host: str = Field(default="localhost", min_length=1, description="Database server hostname")
    port: int = Field(default=5432, ge=1, le=65535, description="Database server port")
    database: str = Field(default="database", min_length=1, description="Database name")
    user: str = Field(default="admin", min_length=1, description="Database user")
    password: Optional[str] = Field(
        default=None, description="Database password (loaded from DB_PASSWORD env if not provided)"
    )

    @field_validator("password", mode="before")
    @classmethod
    def load_password_from_env(cls, v: Optional[str]) -> str:
        """Load password from environment if not provided or empty."""
        # Load from env if None or empty string
        if not v:
            password = os.getenv("DB_PASSWORD")
            if not password:
                raise ValueError("DB_PASSWORD environment variable not set or empty")
            return password
        return v


class PoolLimitsConfig(BaseModel):
    """
    Pool size and resource limits configuration.

    Controls how many connections are maintained and when they are recycled.
    Does NOT include timeout configuration - see PoolTimeoutsConfig for that.
    """

    min_size: int = Field(
        default=5, ge=1, le=100, description="Minimum number of connections in the pool"
    )
    max_size: int = Field(
        default=20, ge=1, le=200, description="Maximum number of connections in the pool"
    )
    max_queries: int = Field(
        default=50000, ge=100, description="Max queries per connection before recycling"
    )
    max_inactive_connection_lifetime: float = Field(
        default=300.0, ge=0.0, description="Time before idle connection is closed (seconds)"
    )

    @field_validator("max_size")
    @classmethod
    def validate_max_size(cls, v: int, info) -> int:
        """Ensure max_size >= min_size."""
        min_size = info.data.get("min_size", 5)
        if v < min_size:
            raise ValueError(f"max_size ({v}) must be >= min_size ({min_size})")
        return v


class PoolTimeoutsConfig(BaseModel):
    """
    Pool-level timeout configuration.

    Note: This only controls pool.acquire() timeout. Operation timeouts
    (for queries, procedures, etc.) are controlled by the caller via the
    timeout parameter in asyncpg methods.
    """

    acquisition: float = Field(
        default=10.0,
        ge=0.1,
        description="Timeout for acquiring a connection from the pool (seconds)",
    )
    health_check: float = Field(
        default=5.0, ge=0.1, description="Timeout for connection health check (seconds)"
    )


class RetryConfig(BaseModel):
    """Retry configuration for connection failures."""

    max_attempts: int = Field(
        default=3, ge=1, le=10, description="Maximum retry attempts for connection failures"
    )
    initial_delay: float = Field(
        default=1.0, ge=0.1, description="Initial delay between retries (seconds)"
    )
    max_delay: float = Field(
        default=10.0, ge=0.1, description="Maximum delay between retries (seconds)"
    )
    exponential_backoff: bool = Field(
        default=True, description="Use exponential backoff for retries"
    )

    @field_validator("max_delay")
    @classmethod
    def validate_max_delay(cls, v: float, info) -> float:
        """Ensure max_delay >= initial_delay."""
        initial_delay = info.data.get("initial_delay", 1.0)
        if v < initial_delay:
            raise ValueError(f"max_delay ({v}) must be >= initial_delay ({initial_delay})")
        return v


class ServerSettingsConfig(BaseModel):
    """Optional server settings for PostgreSQL connection."""

    application_name: str = Field(
        default="pool", description="Application name for PostgreSQL connection"
    )
    timezone: str = Field(default="UTC", description="Timezone for PostgreSQL connection")


class PoolConfig(BaseModel):
    """
    Complete pool configuration.

    Structured configuration with clear separation of concerns:
    - database: Connection parameters (host, port, user, etc.)
    - limits: Resource limits (pool size, connection lifecycle)
    - timeouts: Pool-level timeouts (acquisition only)
    - retry: Connection retry logic
    - server_settings: PostgreSQL server settings
    """

    database: DatabaseConfig = Field(
        default_factory=DatabaseConfig, description="Database connection parameters"
    )
    limits: PoolLimitsConfig = Field(
        default_factory=PoolLimitsConfig, description="Pool size and resource limits"
    )
    timeouts: PoolTimeoutsConfig = Field(
        default_factory=PoolTimeoutsConfig, description="Pool-level timeouts"
    )
    retry: RetryConfig = Field(
        default_factory=RetryConfig, description="Connection retry configuration"
    )
    server_settings: ServerSettingsConfig = Field(
        default_factory=ServerSettingsConfig, description="PostgreSQL server settings"
    )


# ============================================================================
# Pool Class
# ============================================================================


class Pool:
    """
    Manages PostgreSQL pooling with asyncpg.

    Features:
    - Async pooling with configurable pool sizes
    - Automatic connection retry with exponential backoff
    - PGBouncer compatibility
    - Configuration via YAML, dict, or config object
    - Comprehensive validation using Pydantic
    - Context manager support for clean resource management

    Example usage:
        # Option 1: Default configuration
        pool = Pool()

        # Option 2: With config object
        config = PoolConfig(
            database=DatabaseConfig(host="localhost", database="brotr"),
            limits=PoolLimitsConfig(min_size=10, max_size=50),
        )
        pool = Pool(config=config)

        # Option 3: From YAML
        pool = Pool.from_yaml("path/to/pool.yaml")

        # Option 4: From dict
        pool = Pool.from_dict({"database": {"host": "localhost"}})

        # Usage
        async with pool:
            async with pool.acquire() as conn:
                result = await conn.fetch("SELECT * FROM events LIMIT 10")
    """

    def __init__(self, config: Optional[PoolConfig] = None):
        """
        Initialize Pool with validated configuration.

        Args:
            config: Pool configuration (uses defaults if not provided)

        Raises:
            ValidationError: If configuration is invalid

        Examples:
            # Default configuration
            pool = Pool()

            # Custom configuration
            config = PoolConfig(
                database=DatabaseConfig(host="db.example.com", database="mydb"),
                limits=PoolLimitsConfig(min_size=10, max_size=100),
            )
            pool = Pool(config=config)
        """
        self._config = config or PoolConfig()
        self._pool: Optional[asyncpg.Pool] = None
        self._is_connected: bool = False
        self._connection_lock = asyncio.Lock()  # Protect connection state changes

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "Pool":
        """
        Create Pool from YAML configuration file.

        Args:
            yaml_path: Path to YAML configuration file

        Returns:
            Pool instance

        Raises:
            FileNotFoundError: If YAML file doesn't exist
            ValidationError: If configuration is invalid
            yaml.YAMLError: If YAML parsing fails
        """
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {yaml_path}")

        with path.open() as f:
            config_data = yaml.safe_load(f)

        return cls.from_dict(config_data or {})

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> "Pool":
        """
        Create Pool from dictionary configuration.

        Args:
            config_dict: Configuration dictionary matching YAML structure

        Returns:
            Pool instance

        Raises:
            ValidationError: If configuration is invalid
        """
        config = PoolConfig(**config_dict)
        return cls(config=config)

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

            while attempt < self._config.retry.max_attempts:
                try:
                    # Create asyncpg pool with configuration
                    # Note: 'timeout' here is for pool.acquire() only
                    # Operation timeouts are controlled by the caller via asyncpg method parameters
                    self._pool = await asyncpg.create_pool(
                        # Connection parameters
                        host=self._config.database.host,
                        port=self._config.database.port,
                        database=self._config.database.database,
                        user=self._config.database.user,
                        password=self._config.database.password,
                        # Pool resource limits
                        min_size=self._config.limits.min_size,
                        max_size=self._config.limits.max_size,
                        max_queries=self._config.limits.max_queries,
                        max_inactive_connection_lifetime=self._config.limits.max_inactive_connection_lifetime,
                        # Pool acquisition timeout
                        timeout=self._config.timeouts.acquisition,
                        # Server settings
                        server_settings={
                            "application_name": self._config.server_settings.application_name,
                            "timezone": self._config.server_settings.timezone,
                        },
                    )
                    self._is_connected = True
                    return

                except (asyncpg.PostgresError, OSError, ConnectionError) as e:
                    attempt += 1
                    if attempt >= self._config.retry.max_attempts:
                        raise ConnectionError(
                            f"Failed to connect to database after {self._config.retry.max_attempts} attempts: {e}"
                        ) from e

                    await asyncio.sleep(delay)

                    if self._config.retry.exponential_backoff:
                        delay = min(delay * 2, self._config.retry.max_delay)
                    else:
                        delay = min(
                            delay + self._config.retry.initial_delay, self._config.retry.max_delay
                        )

    async def close(self) -> None:
        """
        Close pool and release all resources.

        Note: Even if pool.close() raises an exception, we still mark
        the pool as disconnected to prevent further operations.
        """
        async with self._connection_lock:
            if self._pool is not None:
                try:
                    await self._pool.close()
                finally:
                    # Always cleanup state, even if close() fails
                    self._pool = None
                    self._is_connected = False

    def acquire(self) -> AbstractAsyncContextManager[asyncpg.Connection]:
        """
        Acquire a connection from the pool.

        Returns:
            Connection context manager

        Raises:
            RuntimeError: If pool is not connected

        Example:
            async with pool.acquire() as conn:
                result = await conn.fetch("SELECT * FROM events")
        """
        if not self._is_connected or self._pool is None:
            raise RuntimeError("Pool is not connected. Call connect() first.")
        return self._pool.acquire()

    @asynccontextmanager
    async def acquire_healthy(
        self,
        max_retries: int = 3,
        health_check_timeout: Optional[float] = None,
    ) -> AsyncIterator[asyncpg.Connection]:
        """
        Acquire a health-checked connection from the pool.

        Unlike acquire(), this method validates connection health before returning.
        If the connection fails the health check, it's released and a new one is acquired.

        Args:
            max_retries: Maximum attempts to acquire a healthy connection (default: 3)
            health_check_timeout: Timeout for health check query (uses config default if None)

        Yields:
            Healthy database connection

        Raises:
            RuntimeError: If pool is not connected
            ConnectionError: If no healthy connection could be acquired after max_retries

        Example:
            async with pool.acquire_healthy() as conn:
                # Connection is guaranteed to be healthy
                result = await conn.fetch("SELECT * FROM events")
        """
        if not self._is_connected or self._pool is None:
            raise RuntimeError("Pool is not connected. Call connect() first.")

        timeout = health_check_timeout or self._config.timeouts.health_check
        last_error: Optional[Exception] = None

        for _attempt in range(max_retries):
            conn: Optional[asyncpg.Connection] = None
            try:
                # Acquire connection from pool
                conn = await self._pool.acquire()

                # Perform health check before yielding
                try:
                    await conn.fetchval("SELECT 1", timeout=timeout)
                except (asyncpg.PostgresError, TimeoutError) as e:
                    last_error = e
                    # Connection unhealthy, release and retry
                    await self._pool.release(conn)
                    conn = None
                    continue

                # Connection is healthy, yield it
                try:
                    yield conn
                    return  # Success - exit the retry loop
                finally:
                    # Always release connection back to pool
                    await self._pool.release(conn)

            except (asyncpg.PostgresError, OSError) as e:
                last_error = e
                # Release connection if acquired (and not already released)
                if conn is not None:
                    try:
                        await self._pool.release(conn)
                    except Exception:
                        pass  # Ignore release errors during retry
                continue

        raise ConnectionError(
            f"Failed to acquire healthy connection after {max_retries} attempts. "
            f"Last error: {last_error}"
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        """
        Acquire connection with automatic transaction management.

        Provides a connection within a transaction context. The transaction
        automatically commits on success or rolls back on exception.

        Yields:
            Connection within transaction context

        Raises:
            RuntimeError: If pool is not connected
            asyncpg.PostgresError: If database operation fails

        Example:
            async with pool.transaction() as conn:
                await conn.execute("INSERT INTO events ...")
                await conn.execute("UPDATE relays ...")
                # Commits automatically on success
                # Rolls back automatically on exception

        Note:
            This is a convenience method that combines acquire() and transaction().
            For operations that don't need atomicity, use acquire() or the
            high-level methods (fetch, execute, etc.) directly.
        """
        async with self.acquire() as conn, conn.transaction():
            yield conn

    async def fetch(
        self, query: str, *args: Any, timeout: Optional[float] = None
    ) -> list[asyncpg.Record]:
        """
        Execute query and fetch all results.

        Args:
            query: SQL query
            *args: Query parameters
            timeout: Optional query timeout in seconds (if None, uses asyncpg default)

        Returns:
            List of result rows

        Raises:
            asyncpg.PostgresError: If query execution fails
        """
        async with self.acquire() as conn:
            return await conn.fetch(query, *args, timeout=timeout)

    async def fetchrow(
        self, query: str, *args: Any, timeout: Optional[float] = None
    ) -> Optional[asyncpg.Record]:
        """
        Execute query and fetch single row.

        Args:
            query: SQL query
            *args: Query parameters
            timeout: Optional query timeout in seconds (if None, uses asyncpg default)

        Returns:
            Single result row or None

        Raises:
            asyncpg.PostgresError: If query execution fails
        """
        async with self.acquire() as conn:
            return await conn.fetchrow(query, *args, timeout=timeout)

    async def fetchval(
        self, query: str, *args: Any, column: int = 0, timeout: Optional[float] = None
    ) -> Any:
        """
        Execute query and fetch single value.

        Args:
            query: SQL query
            *args: Query parameters
            column: Column index to fetch (default: 0)
            timeout: Optional query timeout in seconds (if None, uses asyncpg default)

        Returns:
            Single value or None

        Raises:
            asyncpg.PostgresError: If query execution fails
        """
        async with self.acquire() as conn:
            return await conn.fetchval(query, *args, column=column, timeout=timeout)

    async def execute(self, query: str, *args: Any, timeout: Optional[float] = None) -> str:
        """
        Execute query without returning results.

        Args:
            query: SQL query
            *args: Query parameters
            timeout: Optional query timeout in seconds (if None, uses asyncpg default)

        Returns:
            Query execution status string

        Raises:
            asyncpg.PostgresError: If query execution fails
        """
        async with self.acquire() as conn:
            return await conn.execute(query, *args, timeout=timeout)

    async def executemany(
        self, query: str, args_list: list[tuple[Any, ...]], timeout: Optional[float] = None
    ) -> None:
        """
        Execute query multiple times with different parameters.

        Args:
            query: SQL query
            args_list: List of parameter tuples
            timeout: Optional query timeout in seconds (if None, uses asyncpg default)

        Raises:
            asyncpg.PostgresError: If query execution fails
        """
        async with self.acquire() as conn:
            await conn.executemany(query, args_list, timeout=timeout)

    @property
    def is_connected(self) -> bool:
        """
        Check if pool is connected.

        Note: This property reads _is_connected without acquiring the lock
        to maintain synchronous API. While connect() and close() operations
        are thread-safe, there's a small window where this property might
        return a stale value during concurrent connect/close operations.
        For critical checks, call connect() first (idempotent).
        """
        return self._is_connected

    @property
    def config(self) -> PoolConfig:
        """
        Get validated configuration.

        Note: The returned configuration should be treated as read-only.
        Modifying it after initialization may lead to inconsistent state.
        """
        return self._config

    async def __aenter__(self) -> "Pool":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"Pool("
            f"host={self._config.database.host}, "
            f"port={self._config.database.port}, "
            f"database={self._config.database.database}, "
            f"connected={self._is_connected})"
        )
