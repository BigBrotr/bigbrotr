"""
Unit tests for core.pool module.

Tests:
- Configuration models (DatabaseConfig, LimitsConfig, RetryConfig, etc.)
- Pool initialization and factory methods
- Connection lifecycle (connect, close)
- Query methods (fetch, fetchval, fetchrow, execute, executemany)
- acquire_healthy with retry logic
- Transaction context manager
- Async context manager
"""

import os
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from pydantic import ValidationError

from core.pool import (
    DatabaseConfig,
    LimitsConfig,
    Pool,
    PoolConfig,
    RetryConfig,
    ServerSettingsConfig,
    TimeoutsConfig,
)


# ============================================================================
# DatabaseConfig Tests
# ============================================================================


class TestDatabaseConfig:
    """Tests for DatabaseConfig Pydantic model."""

    def test_default_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test default configuration values."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
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

    def test_password_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test password loaded from environment variable."""
        monkeypatch.setenv("DB_PASSWORD", "env_password")
        config = DatabaseConfig(password=None)
        assert config.password.get_secret_value() == "env_password"

    def test_password_empty_string_loads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test empty string password loads from environment."""
        monkeypatch.setenv("DB_PASSWORD", "from_env")
        config = DatabaseConfig(password="")
        assert config.password.get_secret_value() == "from_env"

    def test_password_missing_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test error when password not provided and env not set."""
        monkeypatch.delenv("DB_PASSWORD", raising=False)
        with pytest.raises(ValidationError) as exc_info:
            DatabaseConfig(password=None)
        assert "DB_PASSWORD" in str(exc_info.value)

    def test_invalid_port_too_high(self) -> None:
        """Test validation error for port > 65535."""
        with pytest.raises(ValidationError):
            DatabaseConfig(port=70000, password="test")

    def test_invalid_port_zero(self) -> None:
        """Test validation error for port = 0."""
        with pytest.raises(ValidationError):
            DatabaseConfig(port=0, password="test")

    def test_empty_host_fails(self) -> None:
        """Test validation error for empty host."""
        with pytest.raises(ValidationError):
            DatabaseConfig(host="", password="test")


# ============================================================================
# LimitsConfig Tests
# ============================================================================


class TestLimitsConfig:
    """Tests for LimitsConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default limits."""
        config = LimitsConfig()

        assert config.min_size == 5
        assert config.max_size == 20
        assert config.max_queries == 50000
        assert config.max_inactive_connection_lifetime == 300.0

    def test_max_size_must_be_gte_min_size(self) -> None:
        """Test max_size must be >= min_size."""
        with pytest.raises(ValidationError) as exc_info:
            LimitsConfig(min_size=10, max_size=5)
        assert "max_size" in str(exc_info.value)

    def test_valid_custom_limits(self) -> None:
        """Test valid custom limits."""
        config = LimitsConfig(
            min_size=10,
            max_size=50,
            max_queries=100000,
            max_inactive_connection_lifetime=600.0,
        )

        assert config.min_size == 10
        assert config.max_size == 50
        assert config.max_queries == 100000
        assert config.max_inactive_connection_lifetime == 600.0


# ============================================================================
# TimeoutsConfig Tests
# ============================================================================


class TestTimeoutsConfig:
    """Tests for TimeoutsConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default timeout values."""
        config = TimeoutsConfig()

        assert config.acquisition == 10.0
        assert config.health_check == 5.0

    def test_custom_values(self) -> None:
        """Test custom timeout values."""
        config = TimeoutsConfig(acquisition=30.0, health_check=10.0)

        assert config.acquisition == 30.0
        assert config.health_check == 10.0


# ============================================================================
# RetryConfig Tests
# ============================================================================


class TestRetryConfig:
    """Tests for RetryConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default retry configuration."""
        config = RetryConfig()

        assert config.max_attempts == 3
        assert config.initial_delay == 1.0
        assert config.max_delay == 10.0
        assert config.exponential_backoff is True

    def test_max_delay_must_be_gte_initial_delay(self) -> None:
        """Test max_delay must be >= initial_delay."""
        with pytest.raises(ValidationError):
            RetryConfig(initial_delay=5.0, max_delay=2.0)

    def test_linear_backoff(self) -> None:
        """Test exponential_backoff can be disabled."""
        config = RetryConfig(exponential_backoff=False)
        assert config.exponential_backoff is False


# ============================================================================
# ServerSettingsConfig Tests
# ============================================================================


class TestServerSettingsConfig:
    """Tests for ServerSettingsConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default server settings."""
        config = ServerSettingsConfig()

        assert config.application_name == "bigbrotr"
        assert config.timezone == "UTC"

    def test_custom_values(self) -> None:
        """Test custom server settings."""
        config = ServerSettingsConfig(application_name="test_app", timezone="US/Pacific")

        assert config.application_name == "test_app"
        assert config.timezone == "US/Pacific"


# ============================================================================
# Pool Initialization Tests
# ============================================================================


class TestPoolInit:
    """Tests for Pool initialization."""

    def test_init_with_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test initialization with default values."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
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
            limits=LimitsConfig(min_size=10, max_size=50),
        )
        pool = Pool(config=config)

        assert pool.config.database.host == "custom.host"
        assert pool.config.database.port == 5433
        assert pool.config.limits.min_size == 10
        assert pool.config.limits.max_size == 50

    def test_from_dict(self, pool_config_dict: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
        """Test creation from dictionary."""
        monkeypatch.setenv("DB_PASSWORD", "dict_pass")
        pool = Pool.from_dict(pool_config_dict)

        assert pool.config.database.host == "localhost"
        assert pool.config.limits.min_size == 2
        assert pool.config.limits.max_size == 10

    def test_from_yaml(
        self, pool_config_dict: dict[str, Any], tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test creation from YAML file."""
        import yaml

        monkeypatch.setenv("DB_PASSWORD", "yaml_pass")

        config_file = tmp_path / "pool_config.yaml"
        config_file.write_text(yaml.dump(pool_config_dict))

        pool = Pool.from_yaml(str(config_file))

        assert pool.config.database.host == "localhost"
        assert pool.config.limits.min_size == 2
        assert pool.config.limits.max_size == 10
        assert pool.config.timeouts.acquisition == 5.0

    def test_from_yaml_file_not_found(self) -> None:
        """Test from_yaml raises when file not found."""
        with pytest.raises(FileNotFoundError):
            Pool.from_yaml("/nonexistent/path/config.yaml")

    def test_repr(self, mock_pool: Pool) -> None:
        """Test string representation."""
        repr_str = repr(mock_pool)

        assert "Pool" in repr_str
        assert "localhost" in repr_str
        assert "connected=True" in repr_str


# ============================================================================
# Pool Connection Tests
# ============================================================================


class TestPoolConnect:
    """Tests for Pool.connect() method."""

    @pytest.mark.asyncio
    async def test_connect_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test successful connection."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()

        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_pool = MagicMock()
            mock_create.return_value = mock_pool

            await pool.connect()

            assert pool.is_connected is True
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_already_connected(self, mock_pool: Pool) -> None:
        """Test connect when already connected is idempotent."""
        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            await mock_pool.connect()
            mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_retry_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test connection retry logic."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        config = PoolConfig(
            retry=RetryConfig(max_attempts=3, initial_delay=0.1, max_delay=0.5),
        )
        pool = Pool(config=config)

        call_count = 0

        async def mock_create(*args: Any, **kwargs: Any) -> MagicMock:
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
    async def test_connect_max_retries_exceeded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test connection failure after max retries."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
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


# ============================================================================
# Pool Close Tests
# ============================================================================


class TestPoolClose:
    """Tests for Pool.close() method."""

    @pytest.mark.asyncio
    async def test_close(self, mock_pool: Pool) -> None:
        """Test close method."""
        await mock_pool.close()

        assert mock_pool.is_connected is False
        assert mock_pool._pool is None

    @pytest.mark.asyncio
    async def test_close_not_connected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test close when not connected does nothing."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()
        await pool.close()  # Should not raise
        assert pool.is_connected is False


# ============================================================================
# Pool Acquire Tests
# ============================================================================


class TestPoolAcquire:
    """Tests for Pool.acquire() method."""

    def test_acquire_not_connected_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test acquire raises when not connected."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()

        with pytest.raises(RuntimeError) as exc_info:
            pool.acquire()
        assert "not connected" in str(exc_info.value)

    def test_acquire_connected(self, mock_pool: Pool) -> None:
        """Test acquire returns context manager when connected."""
        ctx = mock_pool.acquire()
        assert ctx is not None


# ============================================================================
# Pool Query Methods Tests
# ============================================================================


class TestPoolQueryMethods:
    """Tests for Pool query methods."""

    @pytest.mark.asyncio
    async def test_fetch(self, mock_pool: Pool) -> None:
        """Test fetch method."""
        result = await mock_pool.fetch("SELECT 1")
        assert result == []

    @pytest.mark.asyncio
    async def test_fetchrow(self, mock_pool: Pool) -> None:
        """Test fetchrow method."""
        result = await mock_pool.fetchrow("SELECT 1")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetchval(self, mock_pool: Pool) -> None:
        """Test fetchval method."""
        result = await mock_pool.fetchval("SELECT 1")
        assert result == 1

    @pytest.mark.asyncio
    async def test_execute(self, mock_pool: Pool) -> None:
        """Test execute method."""
        result = await mock_pool.execute("INSERT INTO test VALUES (1)")
        assert result == "OK"

    @pytest.mark.asyncio
    async def test_executemany(self, mock_pool: Pool) -> None:
        """Test executemany method."""
        await mock_pool.executemany("INSERT INTO test VALUES ($1)", [(1,), (2,)])
        mock_pool._mock_connection.executemany.assert_called_once()  # type: ignore[attr-defined]


# ============================================================================
# Pool Transaction Tests
# ============================================================================


class TestPoolTransaction:
    """Tests for Pool.transaction() method."""

    @pytest.mark.asyncio
    async def test_transaction_context_manager(self, mock_pool: Pool) -> None:
        """Test transaction returns connection in transaction."""
        async with mock_pool.transaction() as conn:
            assert conn is not None


# ============================================================================
# Pool acquire_healthy Tests
# ============================================================================


class TestAcquireHealthy:
    """Tests for Pool.acquire_healthy() method."""

    @pytest.mark.asyncio
    async def test_acquire_healthy_not_connected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test acquire_healthy raises when not connected."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()

        with pytest.raises(RuntimeError) as exc_info:
            async with pool.acquire_healthy():
                pass
        assert "not connected" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_acquire_healthy_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test acquire_healthy returns healthy connection."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()

        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=1)

        @asynccontextmanager
        async def mock_acquire():
            yield mock_conn

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.acquire = mock_acquire

        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        async with pool.acquire_healthy() as conn:
            assert conn is mock_conn
            mock_conn.fetchval.assert_called_once()

    @pytest.mark.asyncio
    async def test_acquire_healthy_retries_on_unhealthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test acquire_healthy retries when health check fails."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()

        unhealthy_conn = MagicMock()
        unhealthy_conn.fetchval = AsyncMock(
            side_effect=asyncpg.PostgresConnectionError("Connection dead")
        )

        healthy_conn = MagicMock()
        healthy_conn.fetchval = AsyncMock(return_value=1)

        connections = [unhealthy_conn, healthy_conn]
        call_count = 0

        @asynccontextmanager
        async def mock_acquire():
            nonlocal call_count
            conn = connections[call_count]
            call_count += 1
            yield conn

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.acquire = mock_acquire

        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        async with pool.acquire_healthy(max_retries=3) as conn:
            assert conn is healthy_conn

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_acquire_healthy_fails_after_max_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test acquire_healthy raises after exhausting retries."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()

        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(side_effect=asyncpg.PostgresConnectionError("Always fails"))

        @asynccontextmanager
        async def mock_acquire():
            yield mock_conn

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.acquire = mock_acquire

        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        with pytest.raises(ConnectionError) as exc_info:
            async with pool.acquire_healthy(max_retries=2):
                pass

        assert "2 attempts" in str(exc_info.value)


# ============================================================================
# Pool Context Manager Tests
# ============================================================================


class TestPoolContextManager:
    """Tests for Pool async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test async context manager."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.close = AsyncMock()

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_asyncpg_pool):
            async with pool:
                assert pool.is_connected is True

            assert pool.is_connected is False
            mock_asyncpg_pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_exception_still_closes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test pool is closed even if exception occurs."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.close = AsyncMock()

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_asyncpg_pool):
            with pytest.raises(ValueError):
                async with pool:
                    raise ValueError("Test error")

            assert pool.is_connected is False
            mock_asyncpg_pool.close.assert_called_once()