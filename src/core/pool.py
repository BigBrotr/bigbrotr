"""
PostgreSQL Connection Pool using asyncpg.

Manages database connections with:
- Async pooling with configurable sizes
- Automatic retry with exponential backoff
- PGBouncer compatibility
- Structured logging
- Context manager support
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

from .logger import Logger, get_logger


# ============================================================================
# Configuration Models
# ============================================================================


def _get_password_from_env() -> str:
    """Load password from DB_PASSWORD environment variable."""
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise ValueError("DB_PASSWORD environment variable not set")
    return password


class DatabaseConfig(BaseModel):
    """Database connection configuration."""

    host: str = Field(default="localhost", min_length=1, description="Database hostname")
    port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    database: str = Field(default="database", min_length=1, description="Database name")
    user: str = Field(default="admin", min_length=1, description="Database user")
    password: str = Field(
        default_factory=_get_password_from_env,
        description="Database password (from DB_PASSWORD env)",
    )

    @field_validator("password", mode="before")
    @classmethod
    def load_password_from_env(cls, v: Optional[str]) -> str:
        """Load password from environment if not provided."""
        if not v:
            return _get_password_from_env()
        return v


class PoolLimitsConfig(BaseModel):
    """Pool size and resource limits."""

    min_size: int = Field(default=5, ge=1, le=100, description="Minimum connections")
    max_size: int = Field(default=20, ge=1, le=200, description="Maximum connections")
    max_queries: int = Field(default=50000, ge=100, description="Queries before recycling")
    max_inactive_connection_lifetime: float = Field(
        default=300.0, ge=0.0, description="Idle timeout (seconds)"
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
    def validate_max_delay(cls, v: float, info) -> float:
        """Ensure max_delay >= initial_delay."""
        initial_delay = info.data.get("initial_delay", 1.0)
        if v < initial_delay:
            raise ValueError(f"max_delay ({v}) must be >= initial_delay ({initial_delay})")
        return v


class ServerSettingsConfig(BaseModel):
    """PostgreSQL server settings."""

    application_name: str = Field(default="bigbrotr", description="Application name")
    timezone: str = Field(default="UTC", description="Timezone")


class PoolConfig(BaseModel):
    """Complete pool configuration."""

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    limits: PoolLimitsConfig = Field(default_factory=PoolLimitsConfig)
    timeouts: PoolTimeoutsConfig = Field(default_factory=PoolTimeoutsConfig)
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

    def __init__(self, config: Optional[PoolConfig] = None) -> None:
        """
        Initialize pool.

        Args:
            config: Pool configuration (uses defaults if not provided)
        """
        self._config = config or PoolConfig()
        self._pool: Optional[asyncpg.Pool] = None
        self._is_connected: bool = False
        self._connection_lock = asyncio.Lock()
        self._logger: Logger = get_logger("pool", component="Pool")

    @classmethod
    def from_yaml(cls, config_path: str) -> "Pool":
        """Create pool from YAML configuration file."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with path.open() as f:
            config_data = yaml.safe_load(f)

        return cls.from_dict(config_data or {})

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> "Pool":
        """Create pool from dictionary configuration."""
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
                "connecting",
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
                        password=db.password,
                        min_size=self._config.limits.min_size,
                        max_size=self._config.limits.max_size,
                        max_queries=self._config.limits.max_queries,
                        max_inactive_connection_lifetime=self._config.limits.max_inactive_connection_lifetime,
                        timeout=self._config.timeouts.acquisition,
                        server_settings={
                            "application_name": self._config.server_settings.application_name,
                            "timezone": self._config.server_settings.timezone,
                        },
                    )
                    self._is_connected = True
                    self._logger.info("connected")
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
                        delay = min(delay + self._config.retry.initial_delay, self._config.retry.max_delay)

    async def close(self) -> None:
        """Close pool and release resources."""
        async with self._connection_lock:
            if self._pool is not None:
                try:
                    await self._pool.close()
                    self._logger.info("closed")
                finally:
                    self._pool = None
                    self._is_connected = False

    # -------------------------------------------------------------------------
    # Connection Acquisition
    # -------------------------------------------------------------------------

    def acquire(self) -> AbstractAsyncContextManager[asyncpg.Connection]:
        """
        Acquire a connection from the pool.

        Raises:
            RuntimeError: If pool is not connected
        """
        if not self._is_connected or self._pool is None:
            raise RuntimeError("Pool not connected. Call connect() first.")
        return self._pool.acquire()

    @asynccontextmanager
    async def acquire_healthy(
        self,
        max_retries: int = 3,
        health_check_timeout: Optional[float] = None,
    ) -> AsyncIterator[asyncpg.Connection]:
        """
        Acquire a health-checked connection.

        Validates connection health before returning. Retries on failure.

        Args:
            max_retries: Max attempts to acquire healthy connection
            health_check_timeout: Timeout for health check query
        """
        if not self._is_connected or self._pool is None:
            raise RuntimeError("Pool not connected. Call connect() first.")

        timeout = health_check_timeout or self._config.timeouts.health_check
        last_error: Optional[Exception] = None

        for attempt in range(max_retries):
            conn: Optional[asyncpg.Connection] = None
            try:
                conn = await self._pool.acquire()

                # Health check
                try:
                    await conn.fetchval("SELECT 1", timeout=timeout)
                except (asyncpg.PostgresError, TimeoutError) as e:
                    last_error = e
                    await self._pool.release(conn)
                    conn = None
                    continue

                # Healthy - yield connection
                try:
                    yield conn
                    return
                finally:
                    await self._pool.release(conn)

            except (asyncpg.PostgresError, OSError) as e:
                last_error = e
                if conn is not None:
                    try:
                        await self._pool.release(conn)
                    except Exception:
                        pass
                continue

        raise ConnectionError(
            f"Failed to acquire healthy connection after {max_retries} attempts: {last_error}"
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        """
        Acquire connection with transaction management.

        Commits on success, rolls back on exception.
        """
        async with self.acquire() as conn, conn.transaction():
            yield conn

    # -------------------------------------------------------------------------
    # Query Methods
    # -------------------------------------------------------------------------

    async def fetch(
        self, query: str, *args: Any, timeout: Optional[float] = None
    ) -> list[asyncpg.Record]:
        """Execute query and fetch all results."""
        async with self.acquire() as conn:
            return await conn.fetch(query, *args, timeout=timeout)

    async def fetchrow(
        self, query: str, *args: Any, timeout: Optional[float] = None
    ) -> Optional[asyncpg.Record]:
        """Execute query and fetch single row."""
        async with self.acquire() as conn:
            return await conn.fetchrow(query, *args, timeout=timeout)

    async def fetchval(
        self, query: str, *args: Any, column: int = 0, timeout: Optional[float] = None
    ) -> Any:
        """Execute query and fetch single value."""
        async with self.acquire() as conn:
            return await conn.fetchval(query, *args, column=column, timeout=timeout)

    async def execute(
        self, query: str, *args: Any, timeout: Optional[float] = None
    ) -> str:
        """Execute query without returning results."""
        async with self.acquire() as conn:
            return await conn.execute(query, *args, timeout=timeout)

    async def executemany(
        self, query: str, args_list: list[tuple[Any, ...]], timeout: Optional[float] = None
    ) -> None:
        """Execute query multiple times with different parameters."""
        async with self.acquire() as conn:
            await conn.executemany(query, args_list, timeout=timeout)

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

    # -------------------------------------------------------------------------
    # Context Manager
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> "Pool":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    def __repr__(self) -> str:
        """String representation."""
        db = self._config.database
        return f"Pool(host={db.host}, database={db.database}, connected={self._is_connected})"