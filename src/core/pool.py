"""
Connection Pool Manager for PostgreSQL using asyncpg
This module provides a ConnectionPool class that manages PostgreSQL
connections using asyncpg with advanced features like automatic retries,
PGBouncer compatibility, and configuration validation via Pydantic.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncContextManager, AsyncIterator, Dict, Optional

import asyncpg
import yaml
from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Pydantic Models for Configuration Validation
# ============================================================================


class DatabaseConfig(BaseModel):
    """Database connection configuration."""

    host: str = Field(default="localhost", min_length=1)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(default="database", min_length=1)
    user: str = Field(default="admin", min_length=1)
    password: Optional[str] = Field(default=None)

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
    Connection pool size and resource limits configuration.

    Controls how many connections are maintained and when they are recycled.
    Does NOT include timeout configuration - see PoolTimeoutsConfig for that.
    """

    min_size: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Minimum number of connections in the pool"
    )
    max_size: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Maximum number of connections in the pool"
    )
    max_queries: int = Field(
        default=50000,
        ge=100,
        description="Max queries per connection before recycling"
    )
    max_inactive_connection_lifetime: float = Field(
        default=300.0,
        ge=0.0,
        description="Seconds before idle connection is closed"
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
        description="Timeout for acquiring a connection from the pool (seconds)"
    )
    health_check: float = Field(
        default=5.0,
        ge=0.1,
        description="Timeout for connection health check (seconds)"
    )


class RetryConfig(BaseModel):
    """Retry configuration for connection failures."""

    max_attempts: int = Field(default=3, ge=1, le=10)
    initial_delay: float = Field(default=1.0, ge=0.1)
    max_delay: float = Field(default=10.0, ge=0.1)
    exponential_backoff: bool = Field(default=True)

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

    application_name: str = Field(default="pool")
    timezone: str = Field(default="UTC")


class ConnectionPoolConfig(BaseModel):
    """
    Complete connection pool configuration.

    Structured configuration with clear separation of concerns:
    - database: Connection parameters (host, port, user, etc.)
    - limits: Resource limits (pool size, connection lifecycle)
    - timeouts: Pool-level timeouts (acquisition only)
    - retry: Connection retry logic
    - server_settings: PostgreSQL server settings
    """

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    limits: PoolLimitsConfig = Field(default_factory=PoolLimitsConfig)
    timeouts: PoolTimeoutsConfig = Field(default_factory=PoolTimeoutsConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    server_settings: ServerSettingsConfig = Field(default_factory=ServerSettingsConfig)


# ============================================================================
# ConnectionPool Class
# ============================================================================


class ConnectionPool:
    """
    Manages PostgreSQL connection pooling with asyncpg.

    Features:
    - Async connection pooling with configurable pool sizes
    - Automatic connection retry with exponential backoff
    - PGBouncer compatibility
    - Configuration via YAML or direct instantiation
    - Comprehensive validation using Pydantic
    - Context manager support for clean resource management

    Example usage:
        # Via YAML configuration
        pool = ConnectionPool.from_yaml("path/to/pool.yaml")
        await pool.connect()
        async with pool.acquire() as conn:
            result = await conn.fetch("SELECT * FROM events LIMIT 10")
        await pool.close()

        # Via direct instantiation
        pool = ConnectionPool(
            host="localhost",
            port=5432,
            database="database",
            user="admin",
            password="secret",
            min_size=5,
            max_size=20
        )
        async with pool:
            async with pool.acquire() as conn:
                result = await conn.fetch("SELECT * FROM events LIMIT 10")
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        max_queries: Optional[int] = None,
        max_inactive_connection_lifetime: Optional[float] = None,
        acquisition_timeout: Optional[float] = None,
        max_attempts: Optional[int] = None,
        initial_delay: Optional[float] = None,
        max_delay: Optional[float] = None,
        exponential_backoff: Optional[bool] = None,
        application_name: Optional[str] = None,
        timezone: Optional[str] = None,
    ):
        """
        Initialize ConnectionPool with validated configuration.

        All parameters are optional - defaults are defined in Pydantic models.

        Args:
            host: Database host (default: "localhost")
            port: Database port (default: 5432)
            database: Database name (default: "database")
            user: Database user (default: "admin")
            password: Database password (if None, loads from DB_PASSWORD env var)
            min_size: Minimum pool size (default: 5)
            max_size: Maximum pool size (default: 20)
            max_queries: Max queries per connection before recycling (default: 50000)
            max_inactive_connection_lifetime: Seconds before idle connection is closed (default: 300.0)
            acquisition_timeout: Timeout for acquiring connection from pool in seconds (default: 10.0)
            max_attempts: Maximum connection retry attempts (default: 3)
            initial_delay: Initial delay between retries in seconds (default: 1.0)
            max_delay: Maximum delay between retries in seconds (default: 10.0)
            exponential_backoff: Use exponential backoff for retries (default: True)
            application_name: Application name for PostgreSQL (default: "pool")
            timezone: Timezone for connection (default: "UTC")

        Raises:
            ValidationError: If configuration is invalid
        """
        # Build config dict only with non-None values
        # Pydantic will apply defaults for missing values
        config_dict = {}

        # Database connection parameters
        database_dict = {}
        if host is not None:
            database_dict["host"] = host
        if port is not None:
            database_dict["port"] = port
        if database is not None:
            database_dict["database"] = database
        if user is not None:
            database_dict["user"] = user
        if password is not None:
            database_dict["password"] = password
        if database_dict:
            config_dict["database"] = database_dict

        # Pool resource limits (size, lifecycle)
        limits_dict = {}
        if min_size is not None:
            limits_dict["min_size"] = min_size
        if max_size is not None:
            limits_dict["max_size"] = max_size
        if max_queries is not None:
            limits_dict["max_queries"] = max_queries
        if max_inactive_connection_lifetime is not None:
            limits_dict["max_inactive_connection_lifetime"] = max_inactive_connection_lifetime
        if limits_dict:
            config_dict["limits"] = limits_dict

        # Pool-level timeouts (acquisition only - operation timeouts controlled by caller)
        timeouts_dict = {}
        if acquisition_timeout is not None:
            timeouts_dict["acquisition"] = acquisition_timeout
        if timeouts_dict:
            config_dict["timeouts"] = timeouts_dict

        # Retry config
        retry_dict = {}
        if max_attempts is not None:
            retry_dict["max_attempts"] = max_attempts
        if initial_delay is not None:
            retry_dict["initial_delay"] = initial_delay
        if max_delay is not None:
            retry_dict["max_delay"] = max_delay
        if exponential_backoff is not None:
            retry_dict["exponential_backoff"] = exponential_backoff
        if retry_dict:
            config_dict["retry"] = retry_dict

        # Server settings config
        server_settings_dict = {}
        if application_name is not None:
            server_settings_dict["application_name"] = application_name
        if timezone is not None:
            server_settings_dict["timezone"] = timezone
        if server_settings_dict:
            config_dict["server_settings"] = server_settings_dict

        # Pydantic will apply defaults for any missing sections/fields
        self._config = ConnectionPoolConfig(**config_dict)
        self._pool: Optional[asyncpg.Pool] = None
        self._is_connected: bool = False
        self._connection_lock = asyncio.Lock()  # Protect connection state changes

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "ConnectionPool":
        """
        Create ConnectionPool from YAML configuration file.

        Args:
            yaml_path: Path to YAML configuration file

        Returns:
            ConnectionPool instance

        Raises:
            FileNotFoundError: If YAML file doesn't exist
            ValidationError: If configuration is invalid
            yaml.YAMLError: If YAML parsing fails
        """
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {yaml_path}")

        with open(path, "r") as f:
            config_data = yaml.safe_load(f)

        if config_data is None:
            config_data = {}

        # Validate with Pydantic
        config = ConnectionPoolConfig(**config_data)

        # Create instance from validated config
        return cls(
            host=config.database.host,
            port=config.database.port,
            database=config.database.database,
            user=config.database.user,
            password=config.database.password,
            min_size=config.limits.min_size,
            max_size=config.limits.max_size,
            max_queries=config.limits.max_queries,
            max_inactive_connection_lifetime=config.limits.max_inactive_connection_lifetime,
            acquisition_timeout=config.timeouts.acquisition,
            max_attempts=config.retry.max_attempts,
            initial_delay=config.retry.initial_delay,
            max_delay=config.retry.max_delay,
            exponential_backoff=config.retry.exponential_backoff,
            application_name=config.server_settings.application_name,
            timezone=config.server_settings.timezone,
        )

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "ConnectionPool":
        """
        Create ConnectionPool from dictionary configuration.

        Args:
            config_dict: Configuration dictionary matching YAML structure

        Returns:
            ConnectionPool instance

        Raises:
            ValidationError: If configuration is invalid
        """
        config = ConnectionPoolConfig(**config_dict)

        return cls(
            host=config.database.host,
            port=config.database.port,
            database=config.database.database,
            user=config.database.user,
            password=config.database.password,
            min_size=config.limits.min_size,
            max_size=config.limits.max_size,
            max_queries=config.limits.max_queries,
            max_inactive_connection_lifetime=config.limits.max_inactive_connection_lifetime,
            acquisition_timeout=config.timeouts.acquisition,
            max_attempts=config.retry.max_attempts,
            initial_delay=config.retry.initial_delay,
            max_delay=config.retry.max_delay,
            exponential_backoff=config.retry.exponential_backoff,
            application_name=config.server_settings.application_name,
            timezone=config.server_settings.timezone,
        )

    async def connect(self) -> None:
        """
        Establish connection pool with retry logic.

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
                        delay = min(delay + self._config.retry.initial_delay, self._config.retry.max_delay)

    async def close(self) -> None:
        """
        Close connection pool and release all resources.

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

    def acquire(self) -> AsyncContextManager[asyncpg.Connection]:
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
            raise RuntimeError("Connection pool is not connected. Call connect() first.")
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
            raise RuntimeError("Connection pool is not connected. Call connect() first.")

        timeout = health_check_timeout or self._config.timeouts.health_check
        last_error: Optional[Exception] = None

        for attempt in range(max_retries):
            conn: Optional[asyncpg.Connection] = None
            try:
                # Acquire connection from pool
                conn = await self._pool.acquire()

                # Perform health check before yielding
                try:
                    await conn.fetchval("SELECT 1", timeout=timeout)
                except (asyncpg.PostgresError, asyncio.TimeoutError) as e:
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
                    if conn is not None:
                        await self._pool.release(conn)

            except (asyncpg.PostgresError, OSError) as e:
                last_error = e
                # Release connection if acquired
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
        async with self.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def fetch(self, query: str, *args, timeout: Optional[float] = None) -> list:
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

    async def fetchrow(self, query: str, *args, timeout: Optional[float] = None):
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

    async def fetchval(self, query: str, *args, column: int = 0, timeout: Optional[float] = None):
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

    async def execute(self, query: str, *args, timeout: Optional[float] = None) -> str:
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

    async def executemany(self, query: str, args_list: list, timeout: Optional[float] = None) -> None:
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
    def config(self) -> ConnectionPoolConfig:
        """
        Get validated configuration.

        Note: The returned configuration should be treated as read-only.
        Modifying it after initialization may lead to inconsistent state.
        """
        return self._config

    async def __aenter__(self) -> "ConnectionPool":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"ConnectionPool("
            f"host={self._config.database.host}, "
            f"port={self._config.database.port}, "
            f"database={self._config.database.database}, "
            f"connected={self._is_connected})"
        )
