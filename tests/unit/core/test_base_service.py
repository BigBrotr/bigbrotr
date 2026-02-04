"""
Unit tests for core.base_service module.

Tests:
- BaseServiceConfig initialization and validation
- BaseService initialization with Brotr and config
- Factory methods (from_yaml, from_dict)
- run_forever() continuous execution with intervals
- Graceful shutdown via request_shutdown()
- wait() interruptible sleep
- is_running property
- Context manager support (__aenter__/__aexit__)
- Consecutive failure handling
- Metrics integration (set_gauge, inc_counter)
- Abstract class behavior
"""

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import Field, ValidationError

from core.base_service import BaseService, BaseServiceConfig
from core.brotr import Brotr
from core.metrics import MetricsConfig


# ============================================================================
# Test Fixtures - Concrete Service Implementation
# ============================================================================


class ConcreteServiceConfig(BaseServiceConfig):
    """Test configuration inheriting from BaseServiceConfig."""

    max_items: int = Field(default=100, ge=1)
    enabled: bool = Field(default=True)
    custom_timeout: float = Field(default=30.0, ge=0.1)


class ConcreteService(BaseService[ConcreteServiceConfig]):
    """Concrete test implementation of BaseService."""

    SERVICE_NAME = "test_service"
    CONFIG_CLASS = ConcreteServiceConfig

    def __init__(self, brotr: Brotr, config: ConcreteServiceConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config or ConcreteServiceConfig())
        self.run_count = 0
        self.should_fail = False
        self.fail_count = 0
        self.fail_exception: type[Exception] = RuntimeError

    async def run(self) -> None:
        """Execute service logic."""
        self.run_count += 1
        if self.should_fail:
            self.fail_count += 1
            raise self.fail_exception("Simulated failure")


# ============================================================================
# Configuration Tests
# ============================================================================


class TestBaseServiceConfig:
    """Tests for BaseServiceConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default configuration values."""
        config = BaseServiceConfig()

        assert config.interval == 300.0
        assert config.max_consecutive_failures == 5
        assert isinstance(config.metrics, MetricsConfig)
        assert config.metrics.enabled is False

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = BaseServiceConfig(
            interval=120.0,
            max_consecutive_failures=10,
            metrics=MetricsConfig(enabled=True, port=9090),
        )

        assert config.interval == 120.0
        assert config.max_consecutive_failures == 10
        assert config.metrics.enabled is True
        assert config.metrics.port == 9090

    def test_interval_minimum_validation(self) -> None:
        """Test that interval must be >= 60.0 seconds."""
        # Valid at minimum
        config = BaseServiceConfig(interval=60.0)
        assert config.interval == 60.0

        # Invalid: below minimum
        with pytest.raises(ValidationError):
            BaseServiceConfig(interval=30.0)

    def test_max_consecutive_failures_zero_allowed(self) -> None:
        """Test that max_consecutive_failures=0 (unlimited) is allowed."""
        config = BaseServiceConfig(max_consecutive_failures=0)
        assert config.max_consecutive_failures == 0

    def test_max_consecutive_failures_negative_not_allowed(self) -> None:
        """Test that negative max_consecutive_failures is not allowed."""
        with pytest.raises(ValidationError):
            BaseServiceConfig(max_consecutive_failures=-1)


class TestConcreteServiceConfig:
    """Tests for custom service configuration extending BaseServiceConfig."""

    def test_inherits_base_defaults(self) -> None:
        """Test that base config defaults are inherited."""
        config = ConcreteServiceConfig()

        assert config.interval == 300.0
        assert config.max_consecutive_failures == 5
        assert config.max_items == 100
        assert config.enabled is True

    def test_custom_fields(self) -> None:
        """Test custom fields in subclass."""
        config = ConcreteServiceConfig(max_items=50, enabled=False, custom_timeout=60.0)

        assert config.max_items == 50
        assert config.enabled is False
        assert config.custom_timeout == 60.0

    def test_override_base_fields(self) -> None:
        """Test overriding base config fields."""
        config = ConcreteServiceConfig(interval=120.0, max_items=200)

        assert config.interval == 120.0
        assert config.max_items == 200


# ============================================================================
# Initialization Tests
# ============================================================================


class TestBaseServiceInit:
    """Tests for BaseService initialization."""

    def test_with_config(self, mock_brotr: Brotr) -> None:
        """Test initialization with custom configuration."""
        config = ConcreteServiceConfig(interval=120.0, max_items=50)
        service = ConcreteService(brotr=mock_brotr, config=config)

        assert service._config.interval == 120.0
        assert service._config.max_items == 50
        assert service._brotr is mock_brotr

    def test_with_default_config(self, mock_brotr: Brotr) -> None:
        """Test initialization with default configuration."""
        service = ConcreteService(brotr=mock_brotr)

        assert service._config.interval == 300.0
        assert service._config.max_items == 100

    def test_service_name(self, mock_brotr: Brotr) -> None:
        """Test SERVICE_NAME class attribute."""
        service = ConcreteService(brotr=mock_brotr)
        assert service.SERVICE_NAME == "test_service"

    def test_config_property(self, mock_brotr: Brotr) -> None:
        """Test config property returns configuration."""
        config = ConcreteServiceConfig(max_items=75)
        service = ConcreteService(brotr=mock_brotr, config=config)

        assert service.config.max_items == 75
        assert service.config is service._config

    def test_initial_running_state(self, mock_brotr: Brotr) -> None:
        """Test that service is running initially (shutdown not set)."""
        service = ConcreteService(brotr=mock_brotr)
        assert service.is_running is True
        assert not service._shutdown_event.is_set()


# ============================================================================
# Factory Methods Tests
# ============================================================================


class TestFactoryMethods:
    """Tests for BaseService factory methods."""

    def test_from_dict(self, mock_brotr: Brotr) -> None:
        """Test from_dict() factory method."""
        config_dict = {
            "interval": 90.0,
            "max_items": 200,
            "enabled": False,
        }
        service = ConcreteService.from_dict(config_dict, brotr=mock_brotr)

        assert service._config.interval == 90.0
        assert service._config.max_items == 200
        assert service._config.enabled is False

    def test_from_dict_with_extra_kwargs(self, mock_brotr: Brotr) -> None:
        """Test from_dict() preserves extra kwargs."""
        config_dict = {"interval": 90.0}
        service = ConcreteService.from_dict(config_dict, brotr=mock_brotr)

        assert service._config.interval == 90.0

    def test_from_yaml(self, mock_brotr: Brotr, tmp_path: Any) -> None:
        """Test from_yaml() factory method."""
        yaml_content = """
interval: 120.0
max_items: 75
enabled: true
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)

        service = ConcreteService.from_yaml(str(config_file), brotr=mock_brotr)

        assert service._config.interval == 120.0
        assert service._config.max_items == 75
        assert service._config.enabled is True

    def test_from_yaml_file_not_found(self, mock_brotr: Brotr) -> None:
        """Test from_yaml() raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            ConcreteService.from_yaml("/nonexistent/path/config.yaml", brotr=mock_brotr)

    def test_from_yaml_invalid_config(self, mock_brotr: Brotr, tmp_path: Any) -> None:
        """Test from_yaml() raises ValidationError for invalid config."""
        yaml_content = """
interval: 10.0
max_items: -5
"""
        config_file = tmp_path / "invalid_config.yaml"
        config_file.write_text(yaml_content)

        with pytest.raises(ValidationError):
            ConcreteService.from_yaml(str(config_file), brotr=mock_brotr)


# ============================================================================
# Context Manager Tests
# ============================================================================


class TestContextManager:
    """Tests for BaseService async context manager."""

    @pytest.mark.asyncio
    async def test_starts_service(self, mock_brotr: Brotr) -> None:
        """Test context manager sets service as running on entry."""
        service = ConcreteService(brotr=mock_brotr)

        async with service:
            assert service.is_running is True

        assert service.is_running is False

    @pytest.mark.asyncio
    async def test_clears_shutdown_event_on_enter(self, mock_brotr: Brotr) -> None:
        """Test that shutdown event is cleared on context entry."""
        service = ConcreteService(brotr=mock_brotr)
        service._shutdown_event.set()  # Simulate previous shutdown

        async with service:
            assert not service._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_sets_shutdown_event_on_exit(self, mock_brotr: Brotr) -> None:
        """Test that shutdown event is set on context exit."""
        service = ConcreteService(brotr=mock_brotr)

        async with service:
            pass

        assert service._shutdown_event.is_set()
        assert service.is_running is False

    @pytest.mark.asyncio
    async def test_sets_shutdown_on_exception(self, mock_brotr: Brotr) -> None:
        """Test that shutdown event is set even when exception occurs."""
        service = ConcreteService(brotr=mock_brotr)

        with pytest.raises(RuntimeError):
            async with service:
                raise RuntimeError("Test error")

        assert service._shutdown_event.is_set()
        assert service.is_running is False


# ============================================================================
# Shutdown Tests
# ============================================================================


class TestShutdown:
    """Tests for shutdown methods."""

    def test_request_shutdown(self, mock_brotr: Brotr) -> None:
        """Test request_shutdown() sets shutdown event."""
        service = ConcreteService(brotr=mock_brotr)

        assert service.is_running is True

        service.request_shutdown()

        assert service.is_running is False
        assert service._shutdown_event.is_set()

    def test_request_shutdown_multiple_times(self, mock_brotr: Brotr) -> None:
        """Test request_shutdown() can be called multiple times safely."""
        service = ConcreteService(brotr=mock_brotr)

        service.request_shutdown()
        service.request_shutdown()

        assert service.is_running is False

    @pytest.mark.asyncio
    async def test_is_running_reflects_event_state(self, mock_brotr: Brotr) -> None:
        """Test is_running property reflects shutdown event state."""
        service = ConcreteService(brotr=mock_brotr)

        assert service.is_running is True

        service._shutdown_event.set()
        assert service.is_running is False

        service._shutdown_event.clear()
        assert service.is_running is True


# ============================================================================
# Wait Tests
# ============================================================================


class TestWait:
    """Tests for wait() method."""

    @pytest.mark.asyncio
    async def test_wait_returns_true_on_shutdown(self, mock_brotr: Brotr) -> None:
        """Test wait() returns True when shutdown is requested."""
        service = ConcreteService(brotr=mock_brotr)

        async def request_shutdown_after_delay() -> None:
            await asyncio.sleep(0.05)
            service.request_shutdown()

        task = asyncio.create_task(request_shutdown_after_delay())
        result = await service.wait(timeout=1.0)
        await task

        assert result is True

    @pytest.mark.asyncio
    async def test_wait_returns_false_on_timeout(self, mock_brotr: Brotr) -> None:
        """Test wait() returns False when timeout expires."""
        service = ConcreteService(brotr=mock_brotr)

        result = await service.wait(timeout=0.01)

        assert result is False
        assert service.is_running is True

    @pytest.mark.asyncio
    async def test_wait_is_interruptible(self, mock_brotr: Brotr) -> None:
        """Test wait() is interruptible by shutdown request."""
        service = ConcreteService(brotr=mock_brotr)

        async def request_shutdown() -> None:
            await asyncio.sleep(0.02)
            service.request_shutdown()

        task = asyncio.create_task(request_shutdown())

        # Wait with long timeout, but should return quickly on shutdown
        import time

        start = time.time()
        result = await service.wait(timeout=10.0)
        elapsed = time.time() - start

        await task

        assert result is True
        assert elapsed < 1.0  # Should not wait full 10 seconds


# ============================================================================
# Run Forever Tests
# ============================================================================


class TestRunForever:
    """Tests for run_forever() method."""

    @pytest.mark.asyncio
    async def test_executes_run(self, mock_brotr: Brotr) -> None:
        """Test run_forever() calls run() method."""
        config = ConcreteServiceConfig(interval=60.0)
        service = ConcreteService(brotr=mock_brotr, config=config)

        async def mock_wait(timeout: float) -> bool:
            return True  # Simulate shutdown requested

        with patch.object(service, "wait", mock_wait):
            async with service:
                await service.run_forever()

        assert service.run_count >= 1

    @pytest.mark.asyncio
    async def test_multiple_cycles(self, mock_brotr: Brotr) -> None:
        """Test run_forever() executes multiple cycles."""
        config = ConcreteServiceConfig(interval=60.0)
        service = ConcreteService(brotr=mock_brotr, config=config)
        cycles = 0

        async def mock_wait(timeout: float) -> bool:
            nonlocal cycles
            cycles += 1
            return cycles >= 3  # Stop after 3 cycles

        with patch.object(service, "wait", mock_wait):
            async with service:
                await service.run_forever()

        assert service.run_count == 3

    @pytest.mark.asyncio
    async def test_stops_on_max_failures(self, mock_brotr: Brotr) -> None:
        """Test run_forever() stops after max consecutive failures."""
        config = ConcreteServiceConfig(interval=60.0, max_consecutive_failures=3)
        service = ConcreteService(brotr=mock_brotr, config=config)
        service.should_fail = True

        async def mock_wait(timeout: float) -> bool:
            return False  # Continue loop

        with patch.object(service, "wait", mock_wait):
            async with service:
                await service.run_forever()

        assert service.fail_count == 3

    @pytest.mark.asyncio
    async def test_unlimited_failures_when_zero(self, mock_brotr: Brotr) -> None:
        """Test run_forever() continues indefinitely when max_consecutive_failures=0."""
        config = ConcreteServiceConfig(interval=60.0, max_consecutive_failures=0)
        service = ConcreteService(brotr=mock_brotr, config=config)
        service.should_fail = True

        async def mock_wait(timeout: float) -> bool:
            return service.fail_count >= 10  # Stop after 10 failures

        with patch.object(service, "wait", mock_wait):
            async with service:
                await service.run_forever()

        assert service.fail_count >= 10

    @pytest.mark.asyncio
    async def test_resets_failures_on_success(self, mock_brotr: Brotr) -> None:
        """Test consecutive failure counter resets after successful run."""
        config = ConcreteServiceConfig(interval=60.0, max_consecutive_failures=5)
        service = ConcreteService(brotr=mock_brotr, config=config)
        cycles = 0

        async def mock_wait(timeout: float) -> bool:
            nonlocal cycles
            cycles += 1
            return cycles >= 5

        # Fail first 2 cycles, succeed rest
        original_run = service.run

        async def alternating_run() -> None:
            if service.run_count < 2:
                service.run_count += 1
                raise RuntimeError("Simulated failure")
            await original_run()

        with (
            patch.object(service, "run", alternating_run),
            patch.object(service, "wait", mock_wait),
        ):
            async with service:
                await service.run_forever()

        # Should complete without hitting max failures
        assert cycles == 5

    @pytest.mark.asyncio
    async def test_reads_interval_from_config(self, mock_brotr: Brotr) -> None:
        """Test run_forever() uses interval from config."""
        config = ConcreteServiceConfig(interval=120.0)
        service = ConcreteService(brotr=mock_brotr, config=config)
        recorded_interval: float | None = None

        async def mock_wait(timeout: float) -> bool:
            nonlocal recorded_interval
            recorded_interval = timeout
            return True  # Stop immediately

        with patch.object(service, "wait", mock_wait):
            async with service:
                await service.run_forever()

        assert recorded_interval == 120.0

    @pytest.mark.asyncio
    async def test_propagates_cancelled_error(self, mock_brotr: Brotr) -> None:
        """Test run_forever() propagates asyncio.CancelledError."""
        service = ConcreteService(brotr=mock_brotr)

        async def raise_cancelled() -> None:
            raise asyncio.CancelledError()

        with patch.object(service, "run", raise_cancelled):
            async with service:
                with pytest.raises(asyncio.CancelledError):
                    await service.run_forever()

    @pytest.mark.asyncio
    async def test_propagates_keyboard_interrupt(self, mock_brotr: Brotr) -> None:
        """Test run_forever() propagates KeyboardInterrupt."""
        service = ConcreteService(brotr=mock_brotr)

        async def raise_keyboard_interrupt() -> None:
            raise KeyboardInterrupt()

        with patch.object(service, "run", raise_keyboard_interrupt):
            async with service:
                with pytest.raises(KeyboardInterrupt):
                    await service.run_forever()

    @pytest.mark.asyncio
    async def test_propagates_system_exit(self, mock_brotr: Brotr) -> None:
        """Test run_forever() propagates SystemExit."""
        service = ConcreteService(brotr=mock_brotr)

        async def raise_system_exit() -> None:
            raise SystemExit()

        with patch.object(service, "run", raise_system_exit):
            async with service:
                with pytest.raises(SystemExit):
                    await service.run_forever()


# ============================================================================
# Metrics Tests
# ============================================================================


class TestSetGauge:
    """Tests for set_gauge() method."""

    def test_set_gauge_when_enabled(self, mock_brotr: Brotr) -> None:
        """Test set_gauge() sets metric when enabled."""
        config = ConcreteServiceConfig(metrics=MetricsConfig(enabled=True))
        service = ConcreteService(brotr=mock_brotr, config=config)

        with patch("core.base_service.SERVICE_GAUGE") as mock_gauge:
            service.set_gauge("test_metric", 42.0)
            mock_gauge.labels.assert_called_with(service="test_service", name="test_metric")
            mock_gauge.labels().set.assert_called_with(42.0)

    def test_set_gauge_when_disabled_is_noop(self, mock_brotr: Brotr) -> None:
        """Test set_gauge() is no-op when metrics disabled."""
        config = ConcreteServiceConfig(metrics=MetricsConfig(enabled=False))
        service = ConcreteService(brotr=mock_brotr, config=config)

        with patch("core.base_service.SERVICE_GAUGE") as mock_gauge:
            service.set_gauge("test_metric", 42.0)
            mock_gauge.labels.assert_not_called()


class TestIncCounter:
    """Tests for inc_counter() method."""

    def test_inc_counter_when_enabled(self, mock_brotr: Brotr) -> None:
        """Test inc_counter() increments metric when enabled."""
        config = ConcreteServiceConfig(metrics=MetricsConfig(enabled=True))
        service = ConcreteService(brotr=mock_brotr, config=config)

        with patch("core.base_service.SERVICE_COUNTER") as mock_counter:
            service.inc_counter("test_count", 5.0)
            mock_counter.labels.assert_called_with(service="test_service", name="test_count")
            mock_counter.labels().inc.assert_called_with(5.0)

    def test_inc_counter_default_value(self, mock_brotr: Brotr) -> None:
        """Test inc_counter() uses default value of 1."""
        config = ConcreteServiceConfig(metrics=MetricsConfig(enabled=True))
        service = ConcreteService(brotr=mock_brotr, config=config)

        with patch("core.base_service.SERVICE_COUNTER") as mock_counter:
            service.inc_counter("test_count")
            mock_counter.labels().inc.assert_called_with(1)

    def test_inc_counter_when_disabled_is_noop(self, mock_brotr: Brotr) -> None:
        """Test inc_counter() is no-op when metrics disabled."""
        config = ConcreteServiceConfig(metrics=MetricsConfig(enabled=False))
        service = ConcreteService(brotr=mock_brotr, config=config)

        with patch("core.base_service.SERVICE_COUNTER") as mock_counter:
            service.inc_counter("test_count")
            mock_counter.labels.assert_not_called()


# ============================================================================
# Abstract Class Behavior Tests
# ============================================================================


class TestAbstractBehavior:
    """Tests for abstract class behavior."""

    def test_cannot_instantiate_base_directly(self, mock_brotr: Brotr) -> None:
        """Test BaseService cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseService(brotr=mock_brotr)  # type: ignore[abstract]

    def test_must_implement_run(self, mock_brotr: Brotr) -> None:
        """Test subclass must implement run() method."""

        class IncompleteService(BaseService[BaseServiceConfig]):
            SERVICE_NAME = "incomplete"
            CONFIG_CLASS = BaseServiceConfig

        with pytest.raises(TypeError):
            IncompleteService(brotr=mock_brotr)  # type: ignore[abstract]

    def test_must_set_service_name(self, mock_brotr: Brotr) -> None:
        """Test subclass has SERVICE_NAME class attribute."""

        class CompleteService(BaseService[BaseServiceConfig]):
            SERVICE_NAME = "complete_service"
            CONFIG_CLASS = BaseServiceConfig

            async def run(self) -> None:
                pass

        service = CompleteService(brotr=mock_brotr)
        assert service.SERVICE_NAME == "complete_service"

    def test_must_set_config_class(self, mock_brotr: Brotr) -> None:
        """Test subclass has CONFIG_CLASS class attribute."""

        class CompleteService(BaseService[BaseServiceConfig]):
            SERVICE_NAME = "complete_service"
            CONFIG_CLASS = BaseServiceConfig

            async def run(self) -> None:
                pass

        assert CompleteService.CONFIG_CLASS is BaseServiceConfig


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling in run_forever()."""

    @pytest.mark.asyncio
    async def test_logs_error_on_failure(self, mock_brotr: Brotr) -> None:
        """Test run_forever() logs errors on failure."""
        service = ConcreteService(brotr=mock_brotr)
        service.should_fail = True

        async def mock_wait(timeout: float) -> bool:
            return service.fail_count >= 1

        with (
            patch.object(service, "wait", mock_wait),
            patch.object(service._logger, "error") as mock_log,
        ):
            async with service:
                await service.run_forever()

        mock_log.assert_called()

    @pytest.mark.asyncio
    async def test_different_exception_types(self, mock_brotr: Brotr) -> None:
        """Test run_forever() handles different exception types."""
        config = ConcreteServiceConfig(max_consecutive_failures=5)
        service = ConcreteService(brotr=mock_brotr, config=config)
        service.should_fail = True

        exceptions = [ValueError, TypeError, RuntimeError, OSError, IOError]
        exception_index = 0

        async def mock_run() -> None:
            nonlocal exception_index
            if exception_index < len(exceptions):
                exc = exceptions[exception_index]
                exception_index += 1
                raise exc("Test error")

        async def mock_wait(timeout: float) -> bool:
            return exception_index >= 5

        with (
            patch.object(service, "run", mock_run),
            patch.object(service, "wait", mock_wait),
        ):
            async with service:
                await service.run_forever()
