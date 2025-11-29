"""
Unit tests for Service wrapper.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.service import (
    CircuitBreakerConfig,
    CircuitBreakerState,
    HealthCheckConfig,
    LoggingConfig,
    Service,
    ServiceConfig,
    ServiceStats,
)


class TestServiceConfig:
    """Tests for ServiceConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = ServiceConfig()

        assert config.logging.enable_logging is True
        assert config.logging.log_level == "INFO"
        assert config.health_check.enable_health_checks is True
        assert config.health_check.health_check_interval == 60.0
        assert config.warmup.enable_warmup is False
        assert config.circuit_breaker.enable_circuit_breaker is False
        assert config.metrics.enable_stats is True

    def test_custom_values(self) -> None:
        """Test custom configuration."""
        config = ServiceConfig(
            logging=LoggingConfig(enable_logging=False, log_level="DEBUG"),
            health_check=HealthCheckConfig(
                enable_health_checks=True,
                health_check_interval=30.0,
                health_check_timeout=10.0,
            ),
            circuit_breaker=CircuitBreakerConfig(
                enable_circuit_breaker=True,
                circuit_breaker_threshold=3,
                circuit_breaker_timeout=60.0,
            ),
        )

        assert config.logging.enable_logging is False
        assert config.logging.log_level == "DEBUG"
        assert config.health_check.health_check_interval == 30.0
        assert config.circuit_breaker.enable_circuit_breaker is True
        assert config.circuit_breaker.circuit_breaker_threshold == 3

    def test_invalid_log_level(self) -> None:
        """Test invalid log level raises error."""
        with pytest.raises(ValueError):
            LoggingConfig(log_level="INVALID")


class TestCircuitBreakerState:
    """Tests for CircuitBreakerState."""

    @pytest.mark.asyncio
    async def test_initial_state(self) -> None:
        """Test initial circuit breaker state."""
        cb = CircuitBreakerState()

        assert cb.consecutive_failures == 0
        assert cb.is_open is False
        assert cb.opened_at is None
        assert cb.total_opens == 0

    @pytest.mark.asyncio
    async def test_record_success(self) -> None:
        """Test recording success resets failures."""
        cb = CircuitBreakerState()
        cb.consecutive_failures = 5
        cb.is_open = True
        cb.opened_at = datetime.now()

        await cb.record_success()

        assert cb.consecutive_failures == 0
        assert cb.is_open is False
        assert cb.opened_at is None

    @pytest.mark.asyncio
    async def test_record_failure(self) -> None:
        """Test recording failure increments counter."""
        cb = CircuitBreakerState()

        await cb.record_failure()
        assert cb.consecutive_failures == 1

        await cb.record_failure()
        assert cb.consecutive_failures == 2

    @pytest.mark.asyncio
    async def test_open_circuit(self) -> None:
        """Test opening circuit breaker."""
        cb = CircuitBreakerState()

        await cb.open_circuit()

        assert cb.is_open is True
        assert cb.opened_at is not None
        assert cb.total_opens == 1

    @pytest.mark.asyncio
    async def test_open_circuit_idempotent(self) -> None:
        """Test opening already open circuit is idempotent."""
        cb = CircuitBreakerState()

        await cb.open_circuit()
        first_opened_at = cb.opened_at

        await cb.open_circuit()

        assert cb.total_opens == 1
        assert cb.opened_at == first_opened_at

    @pytest.mark.asyncio
    async def test_should_attempt_reset(self) -> None:
        """Test reset attempt timing."""
        cb = CircuitBreakerState()
        await cb.open_circuit()

        # Should not reset immediately
        should_reset = await cb.should_attempt_reset(timeout=10.0)
        assert should_reset is False

    @pytest.mark.asyncio
    async def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        cb = CircuitBreakerState()
        cb.consecutive_failures = 3
        await cb.open_circuit()

        result = await cb.to_dict()

        assert result["is_open"] is True
        assert result["consecutive_failures"] == 3
        assert result["total_opens"] == 1
        assert result["opened_at"] is not None


class TestServiceStats:
    """Tests for ServiceStats."""

    @pytest.mark.asyncio
    async def test_record_health_check_success(self) -> None:
        """Test recording successful health check."""
        stats = ServiceStats(name="test")

        await stats.record_health_check(is_healthy=True)

        assert stats.health_checks_performed == 1
        assert stats.health_checks_failed == 0
        assert stats.last_health_status is True

    @pytest.mark.asyncio
    async def test_record_health_check_failure(self) -> None:
        """Test recording failed health check."""
        stats = ServiceStats(name="test")

        await stats.record_health_check(is_healthy=False)

        assert stats.health_checks_performed == 1
        assert stats.health_checks_failed == 1
        assert stats.last_health_status is False

    @pytest.mark.asyncio
    async def test_update_custom_stat(self) -> None:
        """Test updating custom statistics."""
        stats = ServiceStats(name="test")

        await stats.update_custom_stat("requests", 100)
        await stats.update_custom_stat("errors", 5)

        assert stats.custom_stats["requests"] == 100
        assert stats.custom_stats["errors"] == 5

    @pytest.mark.asyncio
    async def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        stats = ServiceStats(name="test")
        stats.started_at = datetime.now()
        await stats.record_health_check(is_healthy=True)

        result = await stats.to_dict()

        assert result["name"] == "test"
        assert "health_checks" in result
        assert result["health_checks"]["total"] == 1
        assert result["health_checks"]["success_rate"] == 100.0

    @pytest.mark.asyncio
    async def test_to_prometheus(self) -> None:
        """Test Prometheus metrics export."""
        stats = ServiceStats(name="test_service")
        await stats.record_health_check(is_healthy=True)
        await stats.update_custom_stat("requests", 100)

        metrics = await stats.to_prometheus()

        assert 'service="test_service"' in metrics
        assert "service_health_checks_total" in metrics
        assert "service_custom_requests" in metrics


class TestService:
    """Tests for Service wrapper class."""

    def _create_mock_service(self) -> MagicMock:
        """Create a mock service with connect/close methods."""
        service = MagicMock()
        service.connect = AsyncMock()
        service.close = AsyncMock()
        service.is_connected = True
        return service

    def test_init(self) -> None:
        """Test Service initialization."""
        mock_instance = self._create_mock_service()
        service = Service(mock_instance, name="test_service")

        assert service.instance is mock_instance
        assert service.name == "test_service"
        assert service.is_running is False

    def test_init_with_config(self, service_config: ServiceConfig) -> None:
        """Test Service initialization with config."""
        mock_instance = self._create_mock_service()
        service = Service(mock_instance, name="test", config=service_config)

        assert service.config.logging.log_level == "DEBUG"
        assert service.config.health_check.health_check_interval == 1.0

    @pytest.mark.asyncio
    async def test_start_database_service(self) -> None:
        """Test starting a database-style service."""
        mock_instance = self._create_mock_service()
        service = Service(
            mock_instance,
            name="test",
            config=ServiceConfig(
                health_check=HealthCheckConfig(enable_health_checks=False)
            ),
        )

        await service.start()

        assert service.is_running is True
        mock_instance.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_background_service(self) -> None:
        """Test starting a background-style service."""
        mock_instance = MagicMock()
        mock_instance.start = AsyncMock()
        mock_instance.stop = AsyncMock()
        mock_instance.is_running = True
        # Remove connect so Service uses start() instead
        del mock_instance.connect

        service = Service(
            mock_instance,
            name="test",
            config=ServiceConfig(
                health_check=HealthCheckConfig(enable_health_checks=False)
            ),
        )

        await service.start()

        assert service.is_running is True
        mock_instance.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop(self) -> None:
        """Test stopping a service."""
        mock_instance = self._create_mock_service()
        service = Service(
            mock_instance,
            name="test",
            config=ServiceConfig(
                health_check=HealthCheckConfig(enable_health_checks=False)
            ),
        )

        await service.start()
        await service.stop()

        assert service.is_running is False
        mock_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Test async context manager."""
        mock_instance = self._create_mock_service()
        service = Service(
            mock_instance,
            name="test",
            config=ServiceConfig(
                health_check=HealthCheckConfig(enable_health_checks=False)
            ),
        )

        async with service:
            assert service.is_running is True
            mock_instance.connect.assert_called_once()

        assert service.is_running is False
        mock_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_with_callback(self) -> None:
        """Test health check with custom callback."""
        mock_instance = self._create_mock_service()

        async def custom_check(instance) -> bool:
            return True

        service = Service(
            mock_instance,
            name="test",
            health_check_callback=custom_check,
            config=ServiceConfig(
                health_check=HealthCheckConfig(enable_health_checks=False)
            ),
        )
        service._is_running = True

        result = await service.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_with_fetchval(self) -> None:
        """Test health check using fetchval method."""
        mock_instance = MagicMock()
        mock_instance.connect = AsyncMock()
        mock_instance.close = AsyncMock()
        mock_instance.is_connected = True
        mock_instance.fetchval = AsyncMock(return_value=1)
        # Remove health_check method so it falls through to fetchval
        del mock_instance.health_check

        service = Service(
            mock_instance,
            name="test",
            config=ServiceConfig(
                health_check=HealthCheckConfig(
                    enable_health_checks=False,
                    health_check_retries=1,  # Single attempt for this test
                )
            ),
        )
        service._is_running = True

        result = await service.health_check()
        assert result is True
        mock_instance.fetchval.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self) -> None:
        """Test health check returns False when not connected."""
        mock_instance = self._create_mock_service()
        mock_instance.is_connected = False

        service = Service(
            mock_instance,
            name="test",
            config=ServiceConfig(
                health_check=HealthCheckConfig(enable_health_checks=False)
            ),
        )

        result = await service.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_retries_on_failure(self) -> None:
        """Test health check retries before reporting failure."""
        call_count = 0

        async def flaky_check(instance) -> bool:
            nonlocal call_count
            call_count += 1
            # Fail first 2 attempts, succeed on 3rd
            return call_count >= 3

        mock_instance = self._create_mock_service()
        service = Service(
            mock_instance,
            name="test",
            health_check_callback=flaky_check,
            config=ServiceConfig(
                health_check=HealthCheckConfig(
                    enable_health_checks=False,
                    health_check_retries=3,
                    health_check_retry_delay=0.1,  # Min allowed value
                )
            ),
        )
        service._is_running = True

        result = await service.health_check()

        assert result is True
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_health_check_fails_after_all_retries(self) -> None:
        """Test health check returns False after exhausting retries."""
        call_count = 0

        async def always_fails(instance) -> bool:
            nonlocal call_count
            call_count += 1
            return False

        mock_instance = self._create_mock_service()
        service = Service(
            mock_instance,
            name="test",
            health_check_callback=always_fails,
            config=ServiceConfig(
                health_check=HealthCheckConfig(
                    enable_health_checks=False,
                    health_check_retries=3,
                    health_check_retry_delay=0.1,
                )
            ),
        )
        service._is_running = True

        result = await service.health_check()

        assert result is False
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_health_check_succeeds_first_try(self) -> None:
        """Test health check doesn't retry when first attempt succeeds."""
        call_count = 0

        async def always_succeeds(instance) -> bool:
            nonlocal call_count
            call_count += 1
            return True

        mock_instance = self._create_mock_service()
        service = Service(
            mock_instance,
            name="test",
            health_check_callback=always_succeeds,
            config=ServiceConfig(
                health_check=HealthCheckConfig(
                    enable_health_checks=False,
                    health_check_retries=3,
                    health_check_retry_delay=0.1,
                )
            ),
        )
        service._is_running = True

        result = await service.health_check()

        assert result is True
        assert call_count == 1  # Only one attempt needed

    @pytest.mark.asyncio
    async def test_get_stats(self) -> None:
        """Test getting service statistics."""
        mock_instance = self._create_mock_service()
        service = Service(
            mock_instance,
            name="test",
            config=ServiceConfig(
                health_check=HealthCheckConfig(enable_health_checks=False)
            ),
        )

        await service.start()
        stats = await service.get_stats()

        assert stats["name"] == "test"
        assert "health_checks" in stats

    @pytest.mark.asyncio
    async def test_update_custom_stats(self) -> None:
        """Test updating custom statistics."""
        mock_instance = self._create_mock_service()
        service = Service(
            mock_instance,
            name="test",
            config=ServiceConfig(
                health_check=HealthCheckConfig(enable_health_checks=False)
            ),
        )

        await service.update_custom_stats("requests", 100)

        stats = await service.get_stats()
        assert stats["custom"]["requests"] == 100

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_threshold(self) -> None:
        """Test circuit breaker opens after threshold failures."""
        mock_instance = self._create_mock_service()
        mock_instance.is_connected = False  # Force health check to fail

        service = Service(
            mock_instance,
            name="test",
            config=ServiceConfig(
                health_check=HealthCheckConfig(
                    enable_health_checks=False,
                    health_check_timeout=0.1,
                ),
                circuit_breaker=CircuitBreakerConfig(
                    enable_circuit_breaker=True,
                    circuit_breaker_threshold=3,
                ),
            ),
        )
        service._is_running = True

        # Simulate 3 failures
        for _ in range(3):
            await service.health_check()
            await service._circuit_breaker.record_failure()

        # Check threshold
        assert service._circuit_breaker.consecutive_failures >= 3

    def test_repr(self) -> None:
        """Test string representation."""
        mock_instance = self._create_mock_service()
        service = Service(mock_instance, name="test_service")

        repr_str = repr(service)

        assert "Service" in repr_str
        assert "test_service" in repr_str
        assert "stopped" in repr_str


class TestServicePrometheusMetrics:
    """Tests for Prometheus metrics export."""

    @pytest.mark.asyncio
    async def test_export_prometheus_disabled(self) -> None:
        """Test Prometheus export when disabled."""
        mock_instance = MagicMock()
        mock_instance.connect = AsyncMock()
        mock_instance.close = AsyncMock()
        mock_instance.is_connected = True

        service = Service(
            mock_instance,
            name="test",
            config=ServiceConfig(
                health_check=HealthCheckConfig(enable_health_checks=False),
                metrics={"enable_prometheus_metrics": False},
            ),
        )

        metrics = await service.export_prometheus_metrics()
        assert "disabled" in metrics

    @pytest.mark.asyncio
    async def test_export_prometheus_enabled(self) -> None:
        """Test Prometheus export when enabled."""
        mock_instance = MagicMock()
        mock_instance.connect = AsyncMock()
        mock_instance.close = AsyncMock()
        mock_instance.is_connected = True

        service = Service(
            mock_instance,
            name="test_service",
            config=ServiceConfig(
                health_check=HealthCheckConfig(enable_health_checks=False),
                metrics={"enable_stats": True, "enable_prometheus_metrics": True},
            ),
        )

        await service.start()
        metrics = await service.export_prometheus_metrics()

        assert "service_uptime_seconds" in metrics
        assert 'service="test_service"' in metrics
