"""
Unit tests for core.pool module.

Tests:
- Configuration models (DatabaseConfig, PoolLimitsConfig, PoolTimeoutsConfig, PoolRetryConfig, ServerSettingsConfig)
- Pool initialization with defaults and custom config
- Factory methods (from_yaml, from_dict)
- Connection lifecycle (connect, close)
- Query methods (fetch, fetchrow, fetchval, execute)
- Connection acquisition (acquire, transaction)
- Pool properties
- Context manager support
- Retry logic and error handling
- _init_connection JSON codec setup
"""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from pydantic import SecretStr, ValidationError

from bigbrotr.core.pool import (
    DatabaseConfig,
    Pool,
    PoolConfig,
    PoolLimitsConfig,
    PoolRetryConfig,
    PoolTimeoutsConfig,
    ServerSettingsConfig,
    _init_connection,
)


# ============================================================================
# Configuration Models Tests
# ============================================================================


class TestDatabaseConfig:
    """Tests for DatabaseConfig Pydantic model."""

    def test_defaults_with_env_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test default values when DB_ADMIN_PASSWORD env var is set."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_password")
        config = DatabaseConfig()

        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "bigbrotr"
        assert config.user == "admin"
        assert config.password.get_secret_value() == "test_password"

    def test_custom_values(self) -> None:
        """Test configuration with custom values."""
        config = DatabaseConfig(
            host="custom.host.com",
            port=5433,
            database="mydb",
            user="myuser",
            password="mypassword",  # pragma: allowlist secret
        )

        assert config.host == "custom.host.com"
        assert config.port == 5433
        assert config.database == "mydb"
        assert config.user == "myuser"
        assert config.password.get_secret_value() == "mypassword"

    def test_password_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test password resolution from DB_ADMIN_PASSWORD environment variable."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "env_secret_password")
        config = DatabaseConfig()

        assert isinstance(config.password, SecretStr)
        assert config.password.get_secret_value() == "env_secret_password"

    def test_password_missing_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that missing DB_ADMIN_PASSWORD raises ValueError."""
        monkeypatch.delenv("DB_ADMIN_PASSWORD", raising=False)

        with pytest.raises(ValueError, match="DB_ADMIN_PASSWORD"):
            DatabaseConfig()

    def test_explicit_password_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that explicitly provided password is used over environment."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "env_password")
        config = DatabaseConfig(password="explicit_password")

        assert config.password.get_secret_value() == "explicit_password"

    @pytest.mark.parametrize(
        ("port", "expected_error"),
        [
            (0, "greater than or equal to 1"),
            (-1, "greater than or equal to 1"),
            (65536, "less than or equal to 65535"),
            (70000, "less than or equal to 65535"),
        ],
    )
    def test_invalid_port_raises_validation_error(
        self, port: int, expected_error: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that invalid port values raise ValidationError."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")

        with pytest.raises(ValidationError):
            DatabaseConfig(port=port)

    def test_valid_port_boundaries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test valid port boundary values."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")

        config_min = DatabaseConfig(port=1)
        assert config_min.port == 1

        config_max = DatabaseConfig(port=65535)
        assert config_max.port == 65535

    def test_empty_host_raises_validation_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that empty host raises ValidationError."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")

        with pytest.raises(ValidationError):
            DatabaseConfig(host="")

    def test_empty_database_raises_validation_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that empty database name raises ValidationError."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")

        with pytest.raises(ValidationError):
            DatabaseConfig(database="")

    def test_empty_user_raises_validation_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that empty user raises ValidationError."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")

        with pytest.raises(ValidationError):
            DatabaseConfig(user="")


class TestPoolLimitsConfig:
    """Tests for PoolLimitsConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default configuration values."""
        config = PoolLimitsConfig()

        assert config.min_size == 2
        assert config.max_size == 20
        assert config.max_queries == 50000
        assert config.max_inactive_connection_lifetime == 300.0

    def test_custom_values(self) -> None:
        """Test configuration with custom values."""
        config = PoolLimitsConfig(
            min_size=10,
            max_size=50,
            max_queries=100000,
            max_inactive_connection_lifetime=600.0,
        )

        assert config.min_size == 10
        assert config.max_size == 50
        assert config.max_queries == 100000
        assert config.max_inactive_connection_lifetime == 600.0

    def test_max_size_greater_than_or_equal_to_min_size(self) -> None:
        """Test that max_size must be >= min_size."""
        # Valid case: equal sizes are allowed
        config = PoolLimitsConfig(min_size=10, max_size=10)
        assert config.max_size == 10

        # Invalid case: smaller max_size should fail
        with pytest.raises(ValidationError, match="max_size"):
            PoolLimitsConfig(min_size=10, max_size=5)

    def test_min_size_boundaries(self) -> None:
        """Test min_size boundary validations."""
        # Valid minimum
        config = PoolLimitsConfig(min_size=1)
        assert config.min_size == 1

        # Invalid: below minimum
        with pytest.raises(ValidationError):
            PoolLimitsConfig(min_size=0)

        # Invalid: above maximum
        with pytest.raises(ValidationError):
            PoolLimitsConfig(min_size=101)

    def test_max_size_boundaries(self) -> None:
        """Test max_size boundary validations."""
        # Valid at boundaries
        config_min = PoolLimitsConfig(min_size=1, max_size=1)
        assert config_min.max_size == 1

        config_max = PoolLimitsConfig(max_size=200)
        assert config_max.max_size == 200

        # Invalid: above maximum
        with pytest.raises(ValidationError):
            PoolLimitsConfig(max_size=201)

    def test_max_queries_minimum(self) -> None:
        """Test max_queries minimum validation."""
        config = PoolLimitsConfig(max_queries=100)
        assert config.max_queries == 100

        with pytest.raises(ValidationError):
            PoolLimitsConfig(max_queries=99)


class TestPoolTimeoutsConfig:
    """Tests for PoolTimeoutsConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default configuration values."""
        config = PoolTimeoutsConfig()

        assert config.acquisition == 10.0

    def test_custom_values(self) -> None:
        """Test configuration with custom values."""
        config = PoolTimeoutsConfig(acquisition=30.0)

        assert config.acquisition == 30.0

    def test_minimum_validation(self) -> None:
        """Test minimum value validation (>= 0.1)."""
        # Valid at minimum
        config = PoolTimeoutsConfig(acquisition=0.1)
        assert config.acquisition == 0.1

        # Invalid: below minimum
        with pytest.raises(ValidationError):
            PoolTimeoutsConfig(acquisition=0.05)


class TestPoolRetryConfig:
    """Tests for PoolRetryConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default configuration values."""
        config = PoolRetryConfig()

        assert config.max_attempts == 3
        assert config.initial_delay == 1.0
        assert config.max_delay == 10.0
        assert config.exponential_backoff is True

    def test_custom_values(self) -> None:
        """Test configuration with custom values."""
        config = PoolRetryConfig(
            max_attempts=5,
            initial_delay=0.5,
            max_delay=30.0,
            exponential_backoff=False,
        )

        assert config.max_attempts == 5
        assert config.initial_delay == 0.5
        assert config.max_delay == 30.0
        assert config.exponential_backoff is False

    def test_max_delay_greater_than_or_equal_to_initial(self) -> None:
        """Test that max_delay must be >= initial_delay."""
        # Valid case: equal delays are allowed
        config = PoolRetryConfig(initial_delay=5.0, max_delay=5.0)
        assert config.max_delay == 5.0

        # Invalid case: smaller max_delay should fail
        with pytest.raises(ValidationError, match="max_delay"):
            PoolRetryConfig(initial_delay=5.0, max_delay=2.0)

    def test_max_attempts_boundaries(self) -> None:
        """Test max_attempts boundary validations."""
        # Valid boundaries
        config_min = PoolRetryConfig(max_attempts=1)
        assert config_min.max_attempts == 1

        config_max = PoolRetryConfig(max_attempts=10)
        assert config_max.max_attempts == 10

        # Invalid
        with pytest.raises(ValidationError):
            PoolRetryConfig(max_attempts=0)

        with pytest.raises(ValidationError):
            PoolRetryConfig(max_attempts=11)

    def test_delay_minimum_validation(self) -> None:
        """Test delay minimum validation (>= 0.1)."""
        config = PoolRetryConfig(initial_delay=0.1, max_delay=0.1)
        assert config.initial_delay == 0.1

        with pytest.raises(ValidationError):
            PoolRetryConfig(initial_delay=0.05)


class TestServerSettingsConfig:
    """Tests for ServerSettingsConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default configuration values."""
        config = ServerSettingsConfig()

        assert config.application_name == "bigbrotr"
        assert config.timezone == "UTC"
        assert config.statement_timeout == 300000

    def test_custom_values(self) -> None:
        """Test configuration with custom values."""
        config = ServerSettingsConfig(
            application_name="custom_app",
            timezone="America/New_York",
            statement_timeout=600000,
        )

        assert config.application_name == "custom_app"
        assert config.timezone == "America/New_York"
        assert config.statement_timeout == 600000

    def test_statement_timeout_zero_allowed(self) -> None:
        """Test that statement_timeout of 0 (unlimited) is allowed."""
        config = ServerSettingsConfig(statement_timeout=0)
        assert config.statement_timeout == 0


class TestPoolConfig:
    """Tests for PoolConfig composite model."""

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test default nested configuration."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        config = PoolConfig()

        assert config.database.host == "localhost"
        assert config.limits.min_size == 2
        assert config.timeouts.acquisition == 10.0
        assert config.retry.max_attempts == 3
        assert config.server_settings.application_name == "bigbrotr"

    def test_nested_custom_values(self) -> None:
        """Test configuration with nested custom values."""
        config = PoolConfig(
            database=DatabaseConfig(
                host="custom.host",
                port=5433,
                database="customdb",
                user="customuser",
                password="custompass",  # pragma: allowlist secret
            ),
            limits=PoolLimitsConfig(min_size=10, max_size=50),
            timeouts=PoolTimeoutsConfig(acquisition=30.0),
            retry=PoolRetryConfig(max_attempts=5),
            server_settings=ServerSettingsConfig(application_name="custom_app"),
        )

        assert config.database.host == "custom.host"
        assert config.limits.min_size == 10
        assert config.timeouts.acquisition == 30.0
        assert config.retry.max_attempts == 5
        assert config.server_settings.application_name == "custom_app"

    def test_model_dump_excludes_password(self) -> None:
        """Test that model_dump with exclude omits the password field.

        Workers inherit the DB_ADMIN_PASSWORD environment variable, so the password
        should never be serialized through IPC (SA-002).
        """
        config = PoolConfig(
            database=DatabaseConfig(
                host="db.host",
                password="secret123",  # pragma: allowlist secret
            ),
        )

        dump = config.model_dump(exclude={"database": {"password"}})

        assert "password" not in dump["database"]
        assert dump["database"]["host"] == "db.host"
        assert dump["database"]["password_env"] == "DB_ADMIN_PASSWORD"  # pragma: allowlist secret


# ============================================================================
# Pool Initialization Tests
# ============================================================================


class TestPoolInit:
    """Tests for Pool initialization."""

    def test_default_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test Pool with default configuration."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        pool = Pool()

        assert pool.config.database.host == "localhost"
        assert pool.is_connected is False
        assert pool._pool is None

    def test_custom_config(self) -> None:
        """Test Pool with custom configuration."""
        config = PoolConfig(
            database=DatabaseConfig(
                host="custom.host",
                port=5433,
                database="mydb",
                user="myuser",
                password="mypass",
            ),
            limits=PoolLimitsConfig(min_size=10, max_size=50),
        )
        pool = Pool(config=config)

        assert pool.config.database.host == "custom.host"
        assert pool.config.limits.min_size == 10

    def test_none_config_uses_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that None config results in default configuration."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        pool = Pool(config=None)

        assert pool.config.database.host == "localhost"


class TestPoolFactoryMethods:
    """Tests for Pool factory methods."""

    def test_from_dict(
        self, pool_config_dict: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Pool.from_dict() factory method."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "dict_pass")
        pool = Pool.from_dict(pool_config_dict)

        assert pool.config.limits.min_size == 2
        assert pool.config.limits.max_size == 10
        assert pool.config.timeouts.acquisition == 5.0

    def test_from_yaml(
        self, pool_config_dict: dict[str, Any], tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Pool.from_yaml() factory method."""
        import yaml

        monkeypatch.setenv("DB_ADMIN_PASSWORD", "yaml_pass")
        config_file = tmp_path / "pool_config.yaml"
        config_file.write_text(yaml.dump(pool_config_dict))

        pool = Pool.from_yaml(str(config_file))

        assert pool.config.limits.min_size == 2
        assert pool.config.retry.max_attempts == 2

    def test_from_yaml_file_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test from_yaml raises FileNotFoundError for missing file."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")

        with pytest.raises(FileNotFoundError):
            Pool.from_yaml("/nonexistent/path/config.yaml")


class TestPoolRepr:
    """Tests for Pool string representation."""

    def test_repr_connected(self, mock_pool: Pool) -> None:
        """Test repr shows connected status."""
        repr_str = repr(mock_pool)

        assert "Pool" in repr_str
        assert "connected=True" in repr_str
        assert "test_db" in repr_str

    def test_repr_disconnected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test repr shows disconnected status."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        pool = Pool()
        repr_str = repr(pool)

        assert "Pool" in repr_str
        assert "connected=False" in repr_str


# ============================================================================
# Connection Lifecycle Tests
# ============================================================================


class TestPoolConnect:
    """Tests for Pool.connect() method."""

    async def test_connect_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test successful connection establishment."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        pool = Pool()
        mock_asyncpg_pool = MagicMock()

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_asyncpg_pool):
            await pool.connect()

        assert pool.is_connected is True
        assert pool._pool is mock_asyncpg_pool

    async def test_connect_already_connected_is_noop(self, mock_pool: Pool) -> None:
        """Test that connect() on already connected pool is a no-op."""
        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            await mock_pool.connect()
            mock_create.assert_not_called()

        assert mock_pool.is_connected is True

    async def test_connect_retry_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test connection retry on transient failures."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        config = PoolConfig(retry=PoolRetryConfig(max_attempts=3, initial_delay=0.1, max_delay=0.5))
        pool = Pool(config=config)
        call_count = 0

        async def mock_create(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection failed")
            return MagicMock()

        with (
            patch("asyncpg.create_pool", side_effect=mock_create),
            patch("bigbrotr.core.pool.asyncio.sleep", AsyncMock()),
        ):
            await pool.connect()

        assert call_count == 3
        assert pool.is_connected is True

    async def test_connect_max_attempts_exceeded_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that exceeding max retries raises ConnectionError."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        config = PoolConfig(retry=PoolRetryConfig(max_attempts=2, initial_delay=0.1, max_delay=0.2))
        pool = Pool(config=config)

        with (
            patch(
                "asyncpg.create_pool",
                new_callable=AsyncMock,
                side_effect=ConnectionError("Connection failed"),
            ),
            patch("bigbrotr.core.pool.asyncio.sleep", AsyncMock()),
            pytest.raises(ConnectionError, match="2 attempts"),
        ):
            await pool.connect()

    async def test_connect_handles_postgres_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that PostgresError triggers retry."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        config = PoolConfig(retry=PoolRetryConfig(max_attempts=2, initial_delay=0.1))
        pool = Pool(config=config)

        with (
            patch(
                "asyncpg.create_pool",
                new_callable=AsyncMock,
                side_effect=asyncpg.PostgresError("Database error"),
            ),
            patch("bigbrotr.core.pool.asyncio.sleep", AsyncMock()),
            pytest.raises(ConnectionError),
        ):
            await pool.connect()

    async def test_connect_handles_os_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that OSError triggers retry."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        config = PoolConfig(retry=PoolRetryConfig(max_attempts=2, initial_delay=0.1))
        pool = Pool(config=config)

        with (
            patch(
                "asyncpg.create_pool",
                new_callable=AsyncMock,
                side_effect=OSError("Network error"),
            ),
            patch("bigbrotr.core.pool.asyncio.sleep", AsyncMock()),
            pytest.raises(ConnectionError),
        ):
            await pool.connect()

    async def test_connect_exponential_backoff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test exponential backoff delay calculation."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        config = PoolConfig(
            retry=PoolRetryConfig(
                max_attempts=4,
                initial_delay=1.0,
                max_delay=10.0,
                exponential_backoff=True,
            )
        )
        pool = Pool(config=config)
        sleep_delays: list[float] = []

        async def mock_sleep(delay: float) -> None:
            sleep_delays.append(delay)

        with (
            patch(
                "asyncpg.create_pool",
                new_callable=AsyncMock,
                side_effect=ConnectionError("Fail"),
            ),
            patch("bigbrotr.core.pool.asyncio.sleep", mock_sleep),
            pytest.raises(ConnectionError),
        ):
            await pool.connect()

        # Should have 3 sleep calls (between 4 attempts)
        assert len(sleep_delays) == 3
        # Verify exponential pattern: 1.0 -> 2.0 -> 4.0 (capped at max_delay)
        assert sleep_delays[0] == 1.0
        assert sleep_delays[1] == 2.0
        assert sleep_delays[2] == 4.0

    async def test_connect_linear_backoff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test linear backoff when exponential is disabled."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        config = PoolConfig(
            retry=PoolRetryConfig(
                max_attempts=4,
                initial_delay=1.0,
                max_delay=10.0,
                exponential_backoff=False,
            )
        )
        pool = Pool(config=config)
        sleep_delays: list[float] = []

        async def mock_sleep(delay: float) -> None:
            sleep_delays.append(delay)

        with (
            patch(
                "asyncpg.create_pool",
                new_callable=AsyncMock,
                side_effect=ConnectionError("Fail"),
            ),
            patch("bigbrotr.core.pool.asyncio.sleep", mock_sleep),
            pytest.raises(ConnectionError),
        ):
            await pool.connect()

        # Linear: 1.0 -> 2.0 -> 3.0
        assert sleep_delays == [1.0, 2.0, 3.0]


class TestPoolClose:
    """Tests for Pool.close() method."""

    async def test_close_connected_pool(self, mock_pool: Pool) -> None:
        """Test closing a connected pool."""
        await mock_pool.close()

        assert mock_pool.is_connected is False
        assert mock_pool._pool is None

    async def test_close_not_connected_is_safe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that close() on unconnected pool is safe."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        pool = Pool()

        await pool.close()  # Should not raise

        assert pool.is_connected is False

    async def test_close_multiple_times_is_safe(self, mock_pool: Pool) -> None:
        """Test that close() can be called multiple times safely."""
        await mock_pool.close()
        await mock_pool.close()  # Second call should not raise

        assert mock_pool.is_connected is False


# ============================================================================
# Connection Acquisition Tests
# ============================================================================


class TestPoolAcquire:
    """Tests for Pool.acquire() method."""

    def test_acquire_not_connected_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that acquire() on unconnected pool raises RuntimeError."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        pool = Pool()

        with pytest.raises(RuntimeError, match="not connected"):
            pool.acquire()

    def test_acquire_returns_context_manager(self, mock_pool: Pool) -> None:
        """Test that acquire() returns a context manager."""
        ctx = mock_pool.acquire()
        assert ctx is not None
        assert hasattr(ctx, "__aenter__")
        assert hasattr(ctx, "__aexit__")

    async def test_acquire_yields_connection(self, mock_pool: Pool) -> None:
        """Test that acquire() context manager yields a connection."""
        async with mock_pool.acquire() as conn:
            assert conn is not None


class TestPoolTransaction:
    """Tests for Pool.transaction() method."""

    async def test_transaction_yields_connection(self, mock_pool: Pool) -> None:
        """Test that transaction() yields a connection."""
        async with mock_pool.transaction() as conn:
            assert conn is not None

    async def test_transaction_not_connected_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that transaction() on unconnected pool raises RuntimeError."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        pool = Pool()

        with pytest.raises(RuntimeError, match="not connected"):
            async with pool.transaction():
                pass


# ============================================================================
# Query Methods Tests
# ============================================================================


class TestPoolQueryMethods:
    """Tests for Pool query methods (fetch, fetchrow, fetchval, execute)."""

    async def test_fetch_returns_list(self, mock_pool: Pool) -> None:
        """Test fetch() returns list of records."""
        result = await mock_pool.fetch("SELECT * FROM test")
        assert isinstance(result, list)

    async def test_fetchrow_returns_record_or_none(self, mock_pool: Pool) -> None:
        """Test fetchrow() returns single record or None."""
        result = await mock_pool.fetchrow("SELECT 1")
        # Mock returns None by default
        assert result is None

    async def test_fetchval_returns_value(self, mock_pool: Pool) -> None:
        """Test fetchval() returns single value."""
        result = await mock_pool.fetchval("SELECT 1")
        assert result == 1

    async def test_execute_returns_status(self, mock_pool: Pool) -> None:
        """Test execute() returns status string."""
        result = await mock_pool.execute("INSERT INTO test VALUES (1)")
        assert result == "OK"

    async def test_fetch_with_parameters(self, mock_pool: Pool) -> None:
        """Test fetch() with query parameters."""
        await mock_pool.fetch("SELECT * FROM test WHERE id = $1", 123)

        mock_pool._mock_connection.fetch.assert_called_once_with(  # type: ignore[attr-defined]
            "SELECT * FROM test WHERE id = $1", 123, timeout=None
        )

    async def test_fetch_with_timeout(self, mock_pool: Pool) -> None:
        """Test fetch() with custom timeout."""
        await mock_pool.fetch("SELECT 1", timeout=30.0)

        mock_pool._mock_connection.fetch.assert_called_once_with(  # type: ignore[attr-defined]
            "SELECT 1", timeout=30.0
        )

    async def test_fetchval_with_column(self, mock_pool: Pool) -> None:
        """Test fetchval() with column parameter."""
        await mock_pool.fetchval("SELECT 1, 2", column=1)

        mock_pool._mock_connection.fetchval.assert_called_once_with(  # type: ignore[attr-defined]
            "SELECT 1, 2", timeout=None, column=1
        )


class TestPoolQueryRetry:
    """Tests for query retry logic."""

    async def test_retries_on_interface_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that InterfaceError triggers retry."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        pool = Pool()

        attempt = 0
        mock_conn = MagicMock()

        async def mock_fetch(*args: Any, **kwargs: Any) -> list[Any]:
            nonlocal attempt
            attempt += 1
            if attempt < 3:
                raise asyncpg.InterfaceError("Connection lost")
            return []

        mock_conn.fetch = mock_fetch

        @asynccontextmanager
        async def mock_acquire() -> Any:
            yield mock_conn

        mock_asyncpg_pool = MagicMock()
        # Use the function directly so each call creates a new context manager
        mock_asyncpg_pool.acquire = mock_acquire
        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        with patch("bigbrotr.core.pool.asyncio.sleep", AsyncMock()):
            result = await pool.fetch("SELECT 1")

        assert result == []
        assert attempt == 3

    async def test_retries_on_connection_does_not_exist_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that ConnectionDoesNotExistError triggers retry."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        pool = Pool()

        attempt = 0
        mock_conn = MagicMock()

        async def mock_execute(*args: Any, **kwargs: Any) -> str:
            nonlocal attempt
            attempt += 1
            if attempt < 2:
                raise asyncpg.ConnectionDoesNotExistError("Connection gone")
            return "OK"

        mock_conn.execute = mock_execute

        @asynccontextmanager
        async def mock_acquire() -> Any:
            yield mock_conn

        mock_asyncpg_pool = MagicMock()
        # Use the function directly so each call creates a new context manager
        mock_asyncpg_pool.acquire = mock_acquire
        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        with patch("bigbrotr.core.pool.asyncio.sleep", AsyncMock()):
            result = await pool.execute("INSERT INTO test VALUES (1)")

        assert result == "OK"

    async def test_does_not_retry_query_errors(self, mock_pool: Pool) -> None:
        """Test that query errors (syntax, constraint) are not retried."""
        mock_pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            side_effect=asyncpg.PostgresSyntaxError("Syntax error")
        )

        with pytest.raises(asyncpg.PostgresSyntaxError):
            await mock_pool.fetch("INVALID SQL")


# ============================================================================
# Properties Tests
# ============================================================================


class TestPoolProperties:
    """Tests for Pool properties."""

    def test_is_connected_false_initially(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test is_connected is False initially."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        pool = Pool()
        assert pool.is_connected is False

    def test_is_connected_true_when_connected(self, mock_pool: Pool) -> None:
        """Test is_connected is True when connected."""
        assert mock_pool.is_connected is True

    def test_config_property(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test config property returns configuration."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        pool = Pool()
        assert pool.config is not None
        assert isinstance(pool.config, PoolConfig)


# ============================================================================
# Context Manager Tests
# ============================================================================


class TestPoolContextManager:
    """Tests for Pool async context manager."""

    async def test_context_manager_connects_on_enter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test context manager connects on entry."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        pool = Pool()
        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.close = AsyncMock()

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_asyncpg_pool):
            async with pool:
                assert pool.is_connected is True

    async def test_context_manager_closes_on_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test context manager closes on exit."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        pool = Pool()
        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.close = AsyncMock()

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_asyncpg_pool):
            async with pool:
                pass
            assert pool.is_connected is False

    async def test_context_manager_closes_on_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test context manager closes even when exception occurs."""
        monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_pass")
        pool = Pool()
        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.close = AsyncMock()

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_asyncpg_pool):
            with pytest.raises(RuntimeError):
                async with pool:
                    raise RuntimeError("Test error")

            assert pool.is_connected is False


# ============================================================================
# _init_connection Tests
# ============================================================================


class TestInitConnection:
    """Tests for _init_connection function."""

    async def test_sets_jsonb_codec(self) -> None:
        """Test that JSONB type codec is set."""
        mock_conn = MagicMock()
        mock_conn.set_type_codec = AsyncMock()

        await _init_connection(mock_conn)

        # Verify set_type_codec was called for jsonb
        calls = mock_conn.set_type_codec.call_args_list
        jsonb_call = next(
            (c for c in calls if c.kwargs.get("schema") == "pg_catalog" and c.args[0] == "jsonb"),
            None,
        )
        assert jsonb_call is not None

    async def test_sets_json_codec(self) -> None:
        """Test that JSON type codec is set."""
        mock_conn = MagicMock()
        mock_conn.set_type_codec = AsyncMock()

        await _init_connection(mock_conn)

        # Verify set_type_codec was called for json
        calls = mock_conn.set_type_codec.call_args_list
        json_call = next(
            (c for c in calls if c.kwargs.get("schema") == "pg_catalog" and c.args[0] == "json"),
            None,
        )
        assert json_call is not None
