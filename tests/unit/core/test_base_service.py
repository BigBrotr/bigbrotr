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
from typing import Optional

import pytest
from pydantic import BaseModel, Field

from core.base_service import BaseService
from core.brotr import Brotr


class ConcreteServiceConfig(BaseModel):
    """Test configuration."""

    interval: float = Field(default=60.0, ge=1.0)
    max_items: int = Field(default=100, ge=1)
    enabled: bool = Field(default=True)


class ConcreteService(BaseService[ConcreteServiceConfig]):
    """Test implementation."""

    SERVICE_NAME = "test_service"
    CONFIG_CLASS = ConcreteServiceConfig

    def __init__(self, brotr: Brotr, config: Optional[ConcreteServiceConfig] = None):
        super().__init__(brotr=brotr, config=config or ConcreteServiceConfig())
        self.run_count = 0
        self.should_fail = False
        self.fail_count = 0

    async def run(self):
        self.run_count += 1
        if self.should_fail:
            self.fail_count += 1
            raise RuntimeError("Simulated failure")


class TestClassAttributes:
    """BaseService class attributes."""

    def test_max_consecutive_failures_default(self):
        assert BaseService.MAX_CONSECUTIVE_FAILURES == 5

    def test_inherited(self, mock_brotr):
        service = ConcreteService(brotr=mock_brotr)
        assert service.MAX_CONSECUTIVE_FAILURES == 5


class TestInit:
    """BaseService initialization."""

    def test_with_config(self, mock_brotr):
        config = ConcreteServiceConfig(interval=120.0, max_items=50)
        service = ConcreteService(brotr=mock_brotr, config=config)
        assert service._config.interval == 120.0
        assert service._config.max_items == 50

    def test_with_defaults(self, mock_brotr):
        service = ConcreteService(brotr=mock_brotr)
        assert service._config.interval == 60.0
        assert service._config.max_items == 100

    def test_service_name(self, mock_brotr):
        service = ConcreteService(brotr=mock_brotr)
        assert service.SERVICE_NAME == "test_service"


class TestFactoryMethods:
    """BaseService factory methods."""

    def test_from_dict(self, mock_brotr):
        config_dict = {"interval": 90.0, "max_items": 200, "enabled": False}
        service = ConcreteService.from_dict(config_dict, brotr=mock_brotr)
        assert service._config.interval == 90.0
        assert service._config.enabled is False

    def test_from_yaml(self, mock_brotr, tmp_path):
        yaml_content = """
interval: 45.0
max_items: 75
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)
        service = ConcreteService.from_yaml(str(config_file), brotr=mock_brotr)
        assert service._config.interval == 45.0

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
        service = ConcreteService(brotr=mock_brotr)

        async def stop_after_one_run():
            await asyncio.sleep(0.05)
            service.request_shutdown()

        async with service:
            task = asyncio.create_task(stop_after_one_run())
            await service.run_forever(interval=0.01)
            await task
        assert service.run_count >= 1

    @pytest.mark.asyncio
    async def test_stops_on_max_failures(self, mock_brotr):
        service = ConcreteService(brotr=mock_brotr)
        service.should_fail = True

        async with service:
            await service.run_forever(interval=0.01, max_consecutive_failures=3)
        assert service.fail_count == 3

    @pytest.mark.asyncio
    async def test_unlimited_failures_when_zero(self, mock_brotr):
        service = ConcreteService(brotr=mock_brotr)
        service.should_fail = True

        async def stop_after_many_fails():
            while service.fail_count < 10:
                await asyncio.sleep(0.01)
            service.request_shutdown()

        async with service:
            task = asyncio.create_task(stop_after_many_fails())
            await service.run_forever(interval=0.001, max_consecutive_failures=0)
            await task
        assert service.fail_count >= 10


class TestAbstract:
    """BaseService abstract behavior."""

    def test_cannot_instantiate_base(self, mock_brotr):
        with pytest.raises(TypeError):
            BaseService(brotr=mock_brotr)

    def test_must_implement_run(self, mock_brotr):
        class IncompleteService(BaseService):
            SERVICE_NAME = "incomplete"

        with pytest.raises(TypeError):
            IncompleteService(brotr=mock_brotr)
