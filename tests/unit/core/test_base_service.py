"""
Unit tests for core.base_service module.

Tests:
- BaseService initialization with Brotr and config
- Factory methods (from_yaml, from_dict)
- run_forever() continuous execution with intervals
- Graceful shutdown via request_shutdown()
- wait() interruptible sleep
- is_running property
- Context manager support (__aenter__/__aexit__)
- Consecutive failure handling
"""

import asyncio
from unittest.mock import patch

import pytest
from pydantic import Field

from core.base_service import BaseService, BaseServiceConfig
from core.brotr import Brotr


class ConcreteServiceConfig(BaseServiceConfig):
    """Test configuration inheriting from BaseServiceConfig."""

    max_items: int = Field(default=100, ge=1)
    enabled: bool = Field(default=True)


class ConcreteService(BaseService[ConcreteServiceConfig]):
    """Test implementation."""

    SERVICE_NAME = "test_service"
    CONFIG_CLASS = ConcreteServiceConfig

    def __init__(self, brotr: Brotr, config: ConcreteServiceConfig | None = None):
        super().__init__(brotr=brotr, config=config or ConcreteServiceConfig())
        self.run_count = 0
        self.should_fail = False
        self.fail_count = 0

    async def run(self):
        self.run_count += 1
        if self.should_fail:
            self.fail_count += 1
            raise RuntimeError("Simulated failure")


class TestBaseServiceConfig:
    """BaseServiceConfig defaults and validation."""

    def test_defaults(self):
        config = BaseServiceConfig()
        assert config.interval == 300.0
        assert config.max_consecutive_failures == 5

    def test_custom_values(self):
        config = BaseServiceConfig(interval=120.0, max_consecutive_failures=10)
        assert config.interval == 120.0
        assert config.max_consecutive_failures == 10

    def test_interval_minimum(self):
        with pytest.raises(ValueError):
            BaseServiceConfig(interval=30.0)  # Below 60.0 minimum

    def test_max_consecutive_failures_zero_allowed(self):
        config = BaseServiceConfig(max_consecutive_failures=0)
        assert config.max_consecutive_failures == 0


class TestInit:
    """BaseService initialization."""

    def test_with_config(self, mock_brotr):
        config = ConcreteServiceConfig(interval=120.0, max_items=50)
        service = ConcreteService(brotr=mock_brotr, config=config)
        assert service._config.interval == 120.0
        assert service._config.max_items == 50

    def test_with_defaults(self, mock_brotr):
        service = ConcreteService(brotr=mock_brotr)
        assert service._config.interval == 300.0  # BaseServiceConfig default
        assert service._config.max_items == 100

    def test_service_name(self, mock_brotr):
        service = ConcreteService(brotr=mock_brotr)
        assert service.SERVICE_NAME == "test_service"

    def test_config_property(self, mock_brotr):
        config = ConcreteServiceConfig(max_items=75)
        service = ConcreteService(brotr=mock_brotr, config=config)
        assert service.config.max_items == 75
        assert service.config is service._config


class TestFactoryMethods:
    """BaseService factory methods."""

    def test_from_dict(self, mock_brotr):
        config_dict = {"interval": 90.0, "max_items": 200, "enabled": False}
        service = ConcreteService.from_dict(config_dict, brotr=mock_brotr)
        assert service._config.interval == 90.0
        assert service._config.enabled is False

    def test_from_yaml(self, mock_brotr, tmp_path):
        yaml_content = """
interval: 120.0
max_items: 75
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)
        service = ConcreteService.from_yaml(str(config_file), brotr=mock_brotr)
        assert service._config.interval == 120.0
        assert service._config.max_items == 75

    def test_from_yaml_file_not_found(self, mock_brotr):
        with pytest.raises(FileNotFoundError):
            ConcreteService.from_yaml("/nonexistent/path/config.yaml", brotr=mock_brotr)


class TestContextManager:
    """BaseService async context manager."""

    @pytest.mark.asyncio
    async def test_starts_service(self, mock_brotr):
        service = ConcreteService(brotr=mock_brotr)
        async with service:
            assert service.is_running is True
        assert service.is_running is False

    @pytest.mark.asyncio
    async def test_clears_shutdown_event(self, mock_brotr):
        service = ConcreteService(brotr=mock_brotr)
        service._shutdown_event.set()
        async with service:
            assert not service._shutdown_event.is_set()


class TestShutdown:
    """BaseService shutdown methods."""

    def test_request_shutdown(self, mock_brotr):
        service = ConcreteService(brotr=mock_brotr)
        assert service.is_running is True
        service.request_shutdown()
        assert service.is_running is False

    @pytest.mark.asyncio
    async def test_wait_returns_true_on_shutdown(self, mock_brotr):
        service = ConcreteService(brotr=mock_brotr)

        async def request_shutdown_after_delay():
            await asyncio.sleep(0.05)
            service.request_shutdown()

        task = asyncio.create_task(request_shutdown_after_delay())
        result = await service.wait(timeout=1.0)
        await task
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_returns_false_on_timeout(self, mock_brotr):
        service = ConcreteService(brotr=mock_brotr)
        result = await service.wait(timeout=0.01)
        assert result is False


class TestRunForever:
    """BaseService run_forever method."""

    @pytest.mark.asyncio
    async def test_executes_run(self, mock_brotr):
        config = ConcreteServiceConfig(interval=60.0)  # Minimum allowed
        service = ConcreteService(brotr=mock_brotr, config=config)

        # Mock wait to return True (shutdown requested) after first run
        wait_calls = 0

        async def mock_wait(timeout):
            nonlocal wait_calls
            wait_calls += 1
            return True  # Simulate shutdown requested

        with patch.object(service, "wait", mock_wait):
            async with service:
                await service.run_forever()
        assert service.run_count >= 1

    @pytest.mark.asyncio
    async def test_stops_on_max_failures(self, mock_brotr):
        config = ConcreteServiceConfig(interval=60.0, max_consecutive_failures=3)
        service = ConcreteService(brotr=mock_brotr, config=config)
        service.should_fail = True

        # Mock wait to return False (timeout, continue loop) instantly
        async def mock_wait(timeout):
            return False

        with patch.object(service, "wait", mock_wait):
            async with service:
                await service.run_forever()
        assert service.fail_count == 3

    @pytest.mark.asyncio
    async def test_unlimited_failures_when_zero(self, mock_brotr):
        config = ConcreteServiceConfig(interval=60.0, max_consecutive_failures=0)
        service = ConcreteService(brotr=mock_brotr, config=config)
        service.should_fail = True

        # Mock wait to return True (shutdown) after 10 failures
        async def mock_wait(timeout):
            return service.fail_count >= 10  # Stop after 10 failures

        with patch.object(service, "wait", mock_wait):
            async with service:
                await service.run_forever()
        assert service.fail_count >= 10

    @pytest.mark.asyncio
    async def test_reads_interval_from_config(self, mock_brotr):
        """Verify run_forever uses interval from config."""
        config = ConcreteServiceConfig(interval=60.0)
        service = ConcreteService(brotr=mock_brotr, config=config)

        # Track interval passed to wait
        recorded_interval = None

        async def mock_wait(timeout):
            nonlocal recorded_interval
            recorded_interval = timeout
            return True  # Stop immediately

        with patch.object(service, "wait", mock_wait):
            async with service:
                await service.run_forever()
        # Verify interval from config was used
        assert recorded_interval == 60.0
        assert service.run_count >= 1


class TestAbstract:
    """BaseService abstract behavior."""

    def test_cannot_instantiate_base(self, mock_brotr):
        with pytest.raises(TypeError):
            BaseService(brotr=mock_brotr)

    def test_must_implement_run(self, mock_brotr):
        class IncompleteService(BaseService):
            SERVICE_NAME = "incomplete"
            CONFIG_CLASS = BaseServiceConfig

        with pytest.raises(TypeError):
            IncompleteService(brotr=mock_brotr)
