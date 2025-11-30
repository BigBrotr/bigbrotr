"""
Unit tests for Pool.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from core.pool import (
    DatabaseConfig,
    Pool,
    PoolConfig,
    PoolLimitsConfig,
    RetryConfig,
)


class TestDatabaseConfig:
    """Tests for DatabaseConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        os.environ["DB_PASSWORD"] = "test_pass"
        # password=None tells it to load from env
        config = DatabaseConfig(password=None)

        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "database"
        assert config.user == "admin"
        assert config.password.get_secret_value() == "test_pass"

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = DatabaseConfig(
            host="custom.host.com",
            port=5433,
            database="custom_db",
            user="custom_user",
            password="custom_pass",
        )

        assert config.host == "custom.host.com"
        assert config.port == 5433
        assert config.database == "custom_db"
        assert config.user == "custom_user"
        assert config.password.get_secret_value() == "custom_pass"

    def test_password_from_env(self) -> None:
        """Test password loaded from environment variable."""
        os.environ["DB_PASSWORD"] = "env_password"
        config = DatabaseConfig(password=None)
        assert config.password.get_secret_value() == "env_password"

    def test_password_missing_raises(self) -> None:
        """Test error when password not provided and env not set."""
        # Temporarily remove DB_PASSWORD
        old_password = os.environ.pop("DB_PASSWORD", None)
        try:
            with pytest.raises(ValidationError) as exc_info:
                DatabaseConfig(password=None)
            assert "DB_PASSWORD" in str(exc_info.value)
        finally:
            if old_password:
                os.environ["DB_PASSWORD"] = old_password

    def test_invalid_port(self) -> None:
        """Test validation error for invalid port."""
        with pytest.raises(ValidationError):
            DatabaseConfig(port=70000, password="test")

        with pytest.raises(ValidationError):
            DatabaseConfig(port=0, password="test")


class TestPoolLimitsConfig:
    """Tests for PoolLimitsConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default limits."""
        config = PoolLimitsConfig()

        assert config.min_size == 5
        assert config.max_size == 20
        assert config.max_queries == 50000
        assert config.max_inactive_connection_lifetime == 300.0

    def test_max_size_validation(self) -> None:
        """Test max_size must be >= min_size."""
        with pytest.raises(ValidationError) as exc_info:
            PoolLimitsConfig(min_size=10, max_size=5)
        assert "max_size" in str(exc_info.value)

    def test_valid_custom_limits(self) -> None:
        """Test valid custom limits."""
        config = PoolLimitsConfig(
            min_size=10,
            max_size=50,
            max_queries=100000,
            max_inactive_connection_lifetime=600.0,
        )

        assert config.min_size == 10
        assert config.max_size == 50


class TestRetryConfig:
    """Tests for RetryConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default retry configuration."""
        config = RetryConfig()

        assert config.max_attempts == 3
        assert config.initial_delay == 1.0
        assert config.max_delay == 10.0
        assert config.exponential_backoff is True

    def test_max_delay_validation(self) -> None:
        """Test max_delay must be >= initial_delay."""
        with pytest.raises(ValidationError):
            RetryConfig(initial_delay=5.0, max_delay=2.0)


class TestPool:
    """Tests for Pool class."""

    def test_init_with_defaults(self) -> None:
        """Test initialization with default values."""
        os.environ["DB_PASSWORD"] = "test_pass"
        pool = Pool()

        assert pool.config.database.host == "localhost"
        assert pool.config.database.port == 5432
        assert pool.is_connected is False

    def test_init_with_custom_config(self) -> None:
        """Test initialization with custom config."""
        config = PoolConfig(
            database=DatabaseConfig(
                host="custom.host",
                port=5433,
                database="custom_db",
                user="custom_user",
                password="custom_pass",
            ),
            limits=PoolLimitsConfig(min_size=10, max_size=50),
        )
        pool = Pool(config=config)

        assert pool.config.database.host == "custom.host"
        assert pool.config.database.port == 5433
        assert pool.config.limits.min_size == 10
        assert pool.config.limits.max_size == 50

    def test_from_dict(self, pool_config: dict) -> None:
        """Test creation from dictionary."""
        pool_config["database"]["password"] = "dict_pass"
        pool = Pool.from_dict(pool_config)

        assert pool.config.database.host == "localhost"
        assert pool.config.limits.min_size == 2
        assert pool.config.limits.max_size == 10

    def test_acquire_not_connected_raises(self) -> None:
        """Test acquire raises when not connected."""
        os.environ["DB_PASSWORD"] = "test_pass"
        pool = Pool()

        with pytest.raises(RuntimeError) as exc_info:
            pool.acquire()
        assert "not connected" in str(exc_info.value)

    def test_acquire_connected(self, mock_connection_pool: Pool) -> None:
        """Test acquire returns context manager when connected."""
        ctx = mock_connection_pool.acquire()
        assert ctx is not None

    @pytest.mark.asyncio
    async def test_fetch(self, mock_connection_pool: Pool) -> None:
        """Test fetch method."""
        result = await mock_connection_pool.fetch("SELECT 1")
        assert result == []

    @pytest.mark.asyncio
    async def test_fetchval(self, mock_connection_pool: Pool) -> None:
        """Test fetchval method."""
        result = await mock_connection_pool.fetchval("SELECT 1")
        assert result == 1

    @pytest.mark.asyncio
    async def test_execute(self, mock_connection_pool: Pool) -> None:
        """Test execute method."""
        result = await mock_connection_pool.execute("INSERT INTO test VALUES (1)")
        assert result == "OK"

    @pytest.mark.asyncio
    async def test_close(self, mock_connection_pool: Pool) -> None:
        """Test close method."""
        await mock_connection_pool.close()

        assert mock_connection_pool.is_connected is False
        assert mock_connection_pool._pool is None

    def test_repr(self, mock_connection_pool: Pool) -> None:
        """Test string representation."""
        repr_str = repr(mock_connection_pool)

        assert "Pool" in repr_str
        assert "localhost" in repr_str
        assert "connected=True" in repr_str


class TestPoolConnect:
    """Tests for Pool.connect() method."""

    @pytest.mark.asyncio
    async def test_connect_success(self) -> None:
        """Test successful connection."""
        os.environ["DB_PASSWORD"] = "test_pass"
        pool = Pool()

        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_pool = MagicMock()
            mock_create.return_value = mock_pool

            await pool.connect()

            assert pool.is_connected is True
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_already_connected(self, mock_connection_pool: Pool) -> None:
        """Test connect when already connected is idempotent."""
        # Already connected, should not reconnect
        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            await mock_connection_pool.connect()
            mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_retry_on_failure(self) -> None:
        """Test connection retry logic."""
        os.environ["DB_PASSWORD"] = "test_pass"
        config = PoolConfig(
            retry=RetryConfig(max_attempts=3, initial_delay=0.1, max_delay=0.5),
        )
        pool = Pool(config=config)

        call_count = 0

        async def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection failed")
            return MagicMock()

        with patch("asyncpg.create_pool", side_effect=mock_create):
            await pool.connect()

            assert pool.is_connected is True
            assert call_count == 3

    @pytest.mark.asyncio
    async def test_connect_max_retries_exceeded(self) -> None:
        """Test connection failure after max retries."""
        os.environ["DB_PASSWORD"] = "test_pass"
        config = PoolConfig(
            retry=RetryConfig(max_attempts=2, initial_delay=0.1, max_delay=0.2),
        )
        pool = Pool(config=config)

        with patch(
            "asyncpg.create_pool",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Always fails"),
        ):
            with pytest.raises(ConnectionError) as exc_info:
                await pool.connect()

            assert "2 attempts" in str(exc_info.value)
            assert pool.is_connected is False


class TestPoolContextManager:
    """Tests for Pool async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Test async context manager."""
        os.environ["DB_PASSWORD"] = "test_pass"
        pool = Pool()

        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            async with pool:
                assert pool.is_connected is True

            assert pool.is_connected is False
            mock_pool.close.assert_called_once()


class TestAcquireHealthy:
    """Tests for Pool.acquire_healthy() method."""

    @pytest.mark.asyncio
    async def test_acquire_healthy_not_connected(self) -> None:
        """Test acquire_healthy raises when not connected."""
        os.environ["DB_PASSWORD"] = "test_pass"
        pool = Pool()

        with pytest.raises(RuntimeError) as exc_info:
            async with pool.acquire_healthy():
                pass
        assert "not connected" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_acquire_healthy_success(self) -> None:
        """Test acquire_healthy returns healthy connection."""
        os.environ["DB_PASSWORD"] = "test_pass"
        pool = Pool()

        # Create mock pool and connection
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=1)

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_asyncpg_pool.release = AsyncMock()

        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        async with pool.acquire_healthy() as conn:
            assert conn is mock_conn
            mock_conn.fetchval.assert_called_once()

        mock_asyncpg_pool.release.assert_called_once_with(mock_conn)

    @pytest.mark.asyncio
    async def test_acquire_healthy_retries_on_unhealthy(self) -> None:
        """Test acquire_healthy retries when health check fails."""
        import asyncpg

        os.environ["DB_PASSWORD"] = "test_pass"
        pool = Pool()

        # Create unhealthy then healthy connections
        unhealthy_conn = MagicMock()
        unhealthy_conn.fetchval = AsyncMock(
            side_effect=asyncpg.PostgresConnectionError("Connection dead")
        )

        healthy_conn = MagicMock()
        healthy_conn.fetchval = AsyncMock(return_value=1)

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.acquire = AsyncMock(side_effect=[unhealthy_conn, healthy_conn])
        mock_asyncpg_pool.release = AsyncMock()

        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        async with pool.acquire_healthy(max_retries=3) as conn:
            assert conn is healthy_conn

        # Should have released the unhealthy connection
        assert mock_asyncpg_pool.release.call_count >= 1

    @pytest.mark.asyncio
    async def test_acquire_healthy_fails_after_max_retries(self) -> None:
        """Test acquire_healthy raises after exhausting retries."""
        import asyncpg

        os.environ["DB_PASSWORD"] = "test_pass"
        pool = Pool()

        # All connections fail health check
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(side_effect=asyncpg.PostgresConnectionError("Always fails"))

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_asyncpg_pool.release = AsyncMock()

        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        with pytest.raises(ConnectionError) as exc_info:
            async with pool.acquire_healthy(max_retries=2):
                pass

        assert "2 attempts" in str(exc_info.value)
