"""
Unit tests for core.pool module.

Tests:
- Configuration models (DatabaseConfig, LimitsConfig, TimeoutsConfig, RetryConfig)
- Pool initialization with defaults and custom config
- Factory methods (from_yaml, from_dict)
- Connection lifecycle (connect, close)
- Query methods (fetch, fetchrow, fetchval, execute, executemany)
- Connection acquisition (acquire, acquire_healthy, transaction)
- Pool metrics and properties
- Context manager support
- Retry logic and error handling
"""

from contextlib import asynccontextmanager
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


class TestDatabaseConfig:
    """DatabaseConfig Pydantic model."""

    def test_defaults(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        config = DatabaseConfig(password=None)
        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "database"
        assert config.user == "admin"

    def test_custom(self):
        config = DatabaseConfig(
            host="custom.host", port=5433, database="mydb", user="myuser", password="mypass"
        )
        assert config.host == "custom.host"
        assert config.password.get_secret_value() == "mypass"

    def test_password_from_env(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "env_password")
        config = DatabaseConfig(password=None)
        assert config.password.get_secret_value() == "env_password"

    def test_password_missing_raises(self, monkeypatch):
        monkeypatch.delenv("DB_PASSWORD", raising=False)
        with pytest.raises(ValidationError, match="DB_PASSWORD"):
            DatabaseConfig(password=None)

    @pytest.mark.parametrize("port", [0, 70000])
    def test_invalid_port(self, port):
        with pytest.raises(ValidationError):
            DatabaseConfig(port=port, password="test")


class TestLimitsConfig:
    """LimitsConfig Pydantic model."""

    def test_defaults(self):
        config = LimitsConfig()
        assert config.min_size == 5
        assert config.max_size == 20

    def test_max_gte_min(self):
        with pytest.raises(ValidationError, match="max_size"):
            LimitsConfig(min_size=10, max_size=5)


class TestTimeoutsConfig:
    """TimeoutsConfig Pydantic model."""

    def test_defaults(self):
        config = TimeoutsConfig()
        assert config.acquisition == 10.0
        assert config.health_check == 5.0


class TestRetryConfig:
    """RetryConfig Pydantic model."""

    def test_defaults(self):
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.exponential_backoff is True

    def test_max_delay_gte_initial(self):
        with pytest.raises(ValidationError):
            RetryConfig(initial_delay=5.0, max_delay=2.0)


class TestServerSettingsConfig:
    """ServerSettingsConfig Pydantic model."""

    def test_defaults(self):
        config = ServerSettingsConfig()
        assert config.application_name == "bigbrotr"
        assert config.timezone == "UTC"


class TestPoolInit:
    """Pool initialization."""

    def test_defaults(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()
        assert pool.config.database.host == "localhost"
        assert pool.is_connected is False

    def test_custom_config(self):
        config = PoolConfig(
            database=DatabaseConfig(
                host="custom", port=5433, database="mydb", user="user", password="pass"
            ),
            limits=LimitsConfig(min_size=10, max_size=50),
        )
        pool = Pool(config=config)
        assert pool.config.database.host == "custom"

    def test_from_dict(self, pool_config_dict, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "dict_pass")
        pool = Pool.from_dict(pool_config_dict)
        assert pool.config.limits.min_size == 2

    def test_from_yaml(self, pool_config_dict, tmp_path, monkeypatch):
        import yaml

        monkeypatch.setenv("DB_PASSWORD", "yaml_pass")
        config_file = tmp_path / "pool_config.yaml"
        config_file.write_text(yaml.dump(pool_config_dict))
        pool = Pool.from_yaml(str(config_file))
        assert pool.config.limits.min_size == 2

    def test_repr(self, mock_pool):
        assert "Pool" in repr(mock_pool)
        assert "connected=True" in repr(mock_pool)


class TestPoolConnect:
    """Pool.connect() method."""

    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=MagicMock()):
            await pool.connect()
        assert pool.is_connected is True

    @pytest.mark.asyncio
    async def test_already_connected(self, mock_pool):
        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock:
            await mock_pool.connect()
            mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        config = PoolConfig(retry=RetryConfig(max_attempts=3, initial_delay=0.1, max_delay=0.5))
        pool = Pool(config=config)
        call_count = 0

        async def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Fail")
            return MagicMock()

        with patch("asyncpg.create_pool", side_effect=mock_create):
            await pool.connect()
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        config = PoolConfig(retry=RetryConfig(max_attempts=2, initial_delay=0.1, max_delay=0.2))
        pool = Pool(config=config)

        with (
            patch(
                "asyncpg.create_pool", new_callable=AsyncMock, side_effect=ConnectionError("Fail")
            ),
            pytest.raises(ConnectionError, match="2 attempts"),
        ):
            await pool.connect()


class TestPoolClose:
    """Pool.close() method."""

    @pytest.mark.asyncio
    async def test_close(self, mock_pool):
        await mock_pool.close()
        assert mock_pool.is_connected is False

    @pytest.mark.asyncio
    async def test_close_not_connected(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()
        await pool.close()


class TestPoolAcquire:
    """Pool.acquire() method."""

    def test_not_connected_raises(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()
        with pytest.raises(RuntimeError, match="not connected"):
            pool.acquire()

    def test_connected(self, mock_pool):
        ctx = mock_pool.acquire()
        assert ctx is not None


class TestPoolQueryMethods:
    """Pool query methods."""

    @pytest.mark.asyncio
    async def test_fetch(self, mock_pool):
        result = await mock_pool.fetch("SELECT 1")
        assert result == []

    @pytest.mark.asyncio
    async def test_fetchrow(self, mock_pool):
        result = await mock_pool.fetchrow("SELECT 1")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetchval(self, mock_pool):
        result = await mock_pool.fetchval("SELECT 1")
        assert result == 1

    @pytest.mark.asyncio
    async def test_execute(self, mock_pool):
        result = await mock_pool.execute("INSERT INTO test VALUES (1)")
        assert result == "OK"


class TestPoolTransaction:
    """Pool.transaction() method."""

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_pool):
        async with mock_pool.transaction() as conn:
            assert conn is not None


class TestAcquireHealthy:
    """Pool.acquire_healthy() method."""

    @pytest.mark.asyncio
    async def test_not_connected(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()
        with pytest.raises(RuntimeError, match="not connected"):
            async with pool.acquire_healthy():
                pass

    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
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

    @pytest.mark.asyncio
    async def test_retries_on_unhealthy(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()
        unhealthy_conn = MagicMock()
        unhealthy_conn.fetchval = AsyncMock(side_effect=asyncpg.PostgresConnectionError("Dead"))
        healthy_conn = MagicMock()
        healthy_conn.fetchval = AsyncMock(return_value=1)

        connections = [unhealthy_conn, healthy_conn]
        call_count = 0

        @asynccontextmanager
        async def mock_acquire():
            nonlocal call_count
            conn = connections[min(call_count, len(connections) - 1)]
            call_count += 1
            yield conn

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.acquire = mock_acquire
        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        async with pool.acquire_healthy(max_retries=3) as conn:
            assert conn is healthy_conn


class TestPoolContextManager:
    """Pool async context manager."""

    @pytest.mark.asyncio
    async def test_connects_and_closes(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()
        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.close = AsyncMock()

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_asyncpg_pool):
            async with pool:
                assert pool.is_connected is True
            assert pool.is_connected is False


# ============================================================================
# acquire_healthy() Retry Exhaustion Tests
# ============================================================================


class TestAcquireHealthyRetryExhaustion:
    """Tests for acquire_healthy() retry exhaustion behavior."""

    @pytest.mark.asyncio
    async def test_exponential_backoff_timing_verified(self, monkeypatch):
        """Exponential backoff timing verified."""
        import time

        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()

        unhealthy_conn = MagicMock()
        unhealthy_conn.fetchval = AsyncMock(side_effect=asyncpg.PostgresConnectionError("Dead"))

        call_times: list[float] = []

        @asynccontextmanager
        async def mock_acquire():
            call_times.append(time.time())
            yield unhealthy_conn

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.acquire = mock_acquire
        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        with pytest.raises(ConnectionError):
            async with pool.acquire_healthy(max_retries=4):
                pass

        # Verify we got 4 attempts
        assert len(call_times) == 4

        # Verify exponential backoff: delays should be approximately 0.1s, 0.2s, 0.4s
        # Between attempt 1 and 2: ~0.1s
        # Between attempt 2 and 3: ~0.2s
        # Between attempt 3 and 4: ~0.4s
        if len(call_times) >= 4:
            delay1 = call_times[1] - call_times[0]
            delay2 = call_times[2] - call_times[1]
            delay3 = call_times[3] - call_times[2]

            # Delays should roughly double (with some tolerance for test execution)
            assert delay1 >= 0.05, f"First delay too short: {delay1}"
            assert delay2 >= delay1 * 1.5, f"Second delay should be larger: {delay2} vs {delay1}"
            assert delay3 >= delay2 * 1.5, f"Third delay should be larger: {delay3} vs {delay2}"

    @pytest.mark.asyncio
    async def test_max_retries_exhausted_raises_pool_error(self, monkeypatch):
        """Max retries exhausted raises ConnectionError."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()

        unhealthy_conn = MagicMock()
        unhealthy_conn.fetchval = AsyncMock(side_effect=asyncpg.PostgresConnectionError("Dead"))

        @asynccontextmanager
        async def mock_acquire():
            yield unhealthy_conn

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.acquire = mock_acquire
        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        with pytest.raises(ConnectionError) as exc_info:
            async with pool.acquire_healthy(max_retries=3):
                pass

        assert "Failed to acquire healthy connection" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_error_message_includes_attempt_count(self, monkeypatch):
        """Error message includes attempt count."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()

        unhealthy_conn = MagicMock()
        unhealthy_conn.fetchval = AsyncMock(
            side_effect=asyncpg.PostgresConnectionError("Connection died")
        )

        @asynccontextmanager
        async def mock_acquire():
            yield unhealthy_conn

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.acquire = mock_acquire
        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        with pytest.raises(ConnectionError) as exc_info:
            async with pool.acquire_healthy(max_retries=5):
                pass

        error_msg = str(exc_info.value)
        assert "5 attempts" in error_msg
        assert "Failed to acquire healthy connection" in error_msg

    @pytest.mark.asyncio
    async def test_successful_acquisition_after_initial_failures(self, monkeypatch):
        """Successful acquisition after initial failures."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()

        unhealthy_conn = MagicMock()
        unhealthy_conn.fetchval = AsyncMock(side_effect=asyncpg.PostgresConnectionError("Dead"))

        healthy_conn = MagicMock()
        healthy_conn.fetchval = AsyncMock(return_value=1)

        connections = [unhealthy_conn, unhealthy_conn, healthy_conn]
        call_count = 0

        @asynccontextmanager
        async def mock_acquire():
            nonlocal call_count
            conn = connections[min(call_count, len(connections) - 1)]
            call_count += 1
            yield conn

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.acquire = mock_acquire
        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        async with pool.acquire_healthy(max_retries=5) as conn:
            assert conn is healthy_conn

        # Should have taken 3 attempts (2 failures + 1 success)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_different_exception_types_trigger_retry(self, monkeypatch):
        """Different exception types trigger retry."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()

        healthy_conn = MagicMock()
        healthy_conn.fetchval = AsyncMock(return_value=1)

        exception_sequence = [
            asyncpg.PostgresConnectionError("Connection lost"),
            OSError("Network unreachable"),
            TimeoutError("Query timed out"),
        ]
        attempt = 0

        @asynccontextmanager
        async def mock_acquire():
            nonlocal attempt
            conn = MagicMock()
            if attempt < len(exception_sequence):
                conn.fetchval = AsyncMock(side_effect=exception_sequence[attempt])
                attempt += 1
            else:
                conn.fetchval = AsyncMock(return_value=1)
            yield conn

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.acquire = mock_acquire
        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        async with pool.acquire_healthy(max_retries=5):
            # Should succeed on 4th attempt
            pass

        assert attempt == 3  # 3 failures before success

    @pytest.mark.asyncio
    async def test_backoff_delay_increases_exponentially(self, monkeypatch):
        """Backoff delay increases exponentially."""
        import time

        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        pool = Pool()

        unhealthy_conn = MagicMock()
        unhealthy_conn.fetchval = AsyncMock(side_effect=asyncpg.PostgresConnectionError("Dead"))

        timestamps: list[float] = []

        @asynccontextmanager
        async def mock_acquire():
            timestamps.append(time.time())
            yield unhealthy_conn

        mock_asyncpg_pool = MagicMock()
        mock_asyncpg_pool.acquire = mock_acquire
        pool._pool = mock_asyncpg_pool
        pool._is_connected = True

        with pytest.raises(ConnectionError):
            async with pool.acquire_healthy(max_retries=5):
                pass

        # Should have 5 timestamps
        assert len(timestamps) == 5

        # Calculate delays between attempts
        delays = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]

        # Verify exponential growth pattern: 0.1s, 0.2s, 0.4s, 0.8s
        # Each delay should be roughly double the previous (with tolerance)
        for i in range(1, len(delays)):
            # Allow some tolerance for test execution overhead
            ratio = delays[i] / delays[i - 1] if delays[i - 1] > 0.01 else 2.0
            # Ratio should be approximately 2x (1.5x to 3x acceptable due to timing variance)
            assert 1.5 <= ratio <= 3.0, f"Delay ratio {ratio} at index {i} not exponential"
