"""
Unit tests for core.base_service module.

Tests:
- BaseService abstract class behavior
- Service initialization and configuration
- Factory methods (from_yaml, from_dict)
- Lifecycle management (context manager)
- run_forever loop with failure tracking
- Graceful shutdown (request_shutdown, wait)
"""

import asyncio
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from core.base_service import BaseService, ConfigT
from core.brotr import Brotr


# ============================================================================
# Test Configuration and Concrete Implementation
# ============================================================================


class ConcreteServiceConfig(BaseModel):
    """Configuration for concrete service implementation used in tests."""

    interval: float = Field(default=60.0, ge=1.0)
    max_items: int = Field(default=100, ge=1)
    enabled: bool = Field(default=True)


class ConcreteService(BaseService[ConcreteServiceConfig]):
    """Concrete implementation for testing BaseService."""

    SERVICE_NAME = "test_service"
    CONFIG_CLASS = ConcreteServiceConfig

    def __init__(self, brotr: Brotr, config: Optional[ConcreteServiceConfig] = None) -> None:
        super().__init__(brotr=brotr, config=config or ConcreteServiceConfig())
        self._config: ConcreteServiceConfig
        self.run_count = 0
        self.should_fail = False
        self.fail_count = 0

    async def run(self) -> None:
        """Execute main service logic."""
        self.run_count += 1
        if self.should_fail:
            self.fail_count += 1
            raise RuntimeError("Simulated failure")


# ============================================================================
# Class Attributes Tests
# ============================================================================


class TestClassAttributes:
    """Tests for BaseService class attributes."""

    def test_max_consecutive_failures_default(self) -> None:
        """Test MAX_CONSECUTIVE_FAILURES class attribute default."""
        assert BaseService.MAX_CONSECUTIVE_FAILURES == 5

    def test_max_consecutive_failures_inherited(self, mock_brotr: Brotr) -> None:
        """Test MAX_CONSECUTIVE_FAILURES is accessible on subclass."""
        service = ConcreteService(brotr=mock_brotr)
        assert service.MAX_CONSECUTIVE_FAILURES == 5


# ============================================================================
# BaseService Initialization Tests
# ============================================================================


class TestBaseServiceInit:
    """Tests for BaseService initialization."""

    def test_init_with_config(self, mock_brotr: Brotr) -> None:
        """Test initialization with provided config."""
        config = ConcreteServiceConfig(interval=120.0, max_items=50)
        service = ConcreteService(brotr=mock_brotr, config=config)

        assert service._brotr is mock_brotr
        assert service._config.interval == 120.0
        assert service._config.max_items == 50
        assert service._is_running is False

    def test_init_with_default_config(self, mock_brotr: Brotr) -> None:
        """Test initialization with default config."""
        service = ConcreteService(brotr=mock_brotr)

        assert service._config.interval == 60.0
        assert service._config.max_items == 100
        assert service._config.enabled is True

    def test_service_name_attribute(self, mock_brotr: Brotr) -> None:
        """Test SERVICE_NAME class attribute."""
        service = ConcreteService(brotr=mock_brotr)
        assert service.SERVICE_NAME == "test_service"

    def test_config_class_attribute(self) -> None:
        """Test CONFIG_CLASS class attribute."""
        assert ConcreteService.CONFIG_CLASS is ConcreteServiceConfig

    def test_config_property(self, mock_brotr: Brotr) -> None:
        """Test config property returns configuration."""
        config = ConcreteServiceConfig(interval=30.0)
        service = ConcreteService(brotr=mock_brotr, config=config)

        assert service.config is not None
        assert service.config.interval == 30.0


# ============================================================================
# Factory Methods Tests
# ============================================================================


class TestBaseServiceFactoryMethods:
    """Tests for BaseService factory methods."""

    def test_from_dict(self, mock_brotr: Brotr) -> None:
        """Test from_dict creates service with config from dictionary."""
        config_dict = {"interval": 90.0, "max_items": 200, "enabled": False}
        service = ConcreteService.from_dict(config_dict, brotr=mock_brotr)

        assert service._config.interval == 90.0
        assert service._config.max_items == 200
        assert service._config.enabled is False

    def test_from_dict_empty(self, mock_brotr: Brotr) -> None:
        """Test from_dict with empty dict uses defaults."""
        service = ConcreteService.from_dict({}, brotr=mock_brotr)

        assert service._config.interval == 60.0
        assert service._config.max_items == 100

    def test_from_yaml(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test from_yaml creates service from YAML file."""
        yaml_content = """
interval: 45.0
max_items: 75
enabled: true
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)

        service = ConcreteService.from_yaml(str(config_file), brotr=mock_brotr)

        assert service._config.interval == 45.0
        assert service._config.max_items == 75
        assert service._config.enabled is True

    def test_from_yaml_file_not_found(self, mock_brotr: Brotr) -> None:
        """Test from_yaml raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            ConcreteService.from_yaml("/nonexistent/path/config.yaml", brotr=mock_brotr)


# ============================================================================
# Context Manager Tests
# ============================================================================


class TestBaseServiceContextManager:
    """Tests for BaseService async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_starts_service(self, mock_brotr: Brotr) -> None:
        """Test context manager sets is_running on enter."""
        service = ConcreteService(brotr=mock_brotr)

        assert service._is_running is False

        async with service:
            assert service._is_running is True

        assert service._is_running is False

    @pytest.mark.asyncio
    async def test_context_manager_clears_shutdown_event(self, mock_brotr: Brotr) -> None:
        """Test context manager clears shutdown event on enter."""
        service = ConcreteService(brotr=mock_brotr)
        service._shutdown_event.set()

        async with service:
            assert not service._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_context_manager_sets_shutdown_on_exit(self, mock_brotr: Brotr) -> None:
        """Test context manager sets shutdown event on exit."""
        service = ConcreteService(brotr=mock_brotr)

        async with service:
            pass

        assert service._shutdown_event.is_set()


# ============================================================================
# Shutdown Tests
# ============================================================================


class TestBaseServiceShutdown:
    """Tests for BaseService shutdown methods."""

    def test_request_shutdown(self, mock_brotr: Brotr) -> None:
        """Test request_shutdown sets is_running to False and signals event."""
        service = ConcreteService(brotr=mock_brotr)
        service._is_running = True

        service.request_shutdown()

        assert service._is_running is False
        assert service._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_wait_returns_true_on_shutdown(self, mock_brotr: Brotr) -> None:
        """Test wait returns True when shutdown is requested."""
        service = ConcreteService(brotr=mock_brotr)

        async def request_shutdown_after_delay() -> None:
            await asyncio.sleep(0.05)
            service.request_shutdown()

        asyncio.create_task(request_shutdown_after_delay())
        result = await service.wait(timeout=1.0)

        assert result is True

    @pytest.mark.asyncio
    async def test_wait_returns_false_on_timeout(self, mock_brotr: Brotr) -> None:
        """Test wait returns False when timeout expires."""
        service = ConcreteService(brotr=mock_brotr)
        result = await service.wait(timeout=0.01)
        assert result is False


# ============================================================================
# run_forever Tests
# ============================================================================


class TestBaseServiceRunForever:
    """Tests for BaseService run_forever method."""

    @pytest.mark.asyncio
    async def test_run_forever_executes_run(self, mock_brotr: Brotr) -> None:
        """Test run_forever calls run() method."""
        service = ConcreteService(brotr=mock_brotr)

        async def stop_after_one_run() -> None:
            await asyncio.sleep(0.05)
            service.request_shutdown()

        async with service:
            asyncio.create_task(stop_after_one_run())
            await service.run_forever(interval=0.01)

        assert service.run_count >= 1

    @pytest.mark.asyncio
    async def test_run_forever_uses_class_default(self, mock_brotr: Brotr) -> None:
        """Test run_forever uses MAX_CONSECUTIVE_FAILURES when not provided."""
        service = ConcreteService(brotr=mock_brotr)
        service.should_fail = True

        async with service:
            # Should use default MAX_CONSECUTIVE_FAILURES (5)
            await service.run_forever(interval=0.01)

        assert service.fail_count == 5

    @pytest.mark.asyncio
    async def test_run_forever_stops_on_shutdown(self, mock_brotr: Brotr) -> None:
        """Test run_forever stops when shutdown is requested."""
        service = ConcreteService(brotr=mock_brotr)

        async def stop_service() -> None:
            await asyncio.sleep(0.05)
            service.request_shutdown()

        async with service:
            asyncio.create_task(stop_service())
            await service.run_forever(interval=0.01)

        # Should have stopped, not run indefinitely
        assert service.run_count < 100

    @pytest.mark.asyncio
    async def test_run_forever_resets_failures_on_success(self, mock_brotr: Brotr) -> None:
        """Test consecutive failures counter resets on successful run."""
        service = ConcreteService(brotr=mock_brotr)
        call_count = 0

        async def sometimes_fail() -> None:
            nonlocal call_count
            call_count += 1
            service.run_count = call_count  # Update service counter
            if call_count < 3:
                raise RuntimeError("Fail")
            # Third call succeeds

        service.run = sometimes_fail  # type: ignore[method-assign]

        async def stop_after_runs() -> None:
            await asyncio.sleep(0.15)
            service.request_shutdown()

        async with service:
            asyncio.create_task(stop_after_runs())
            await service.run_forever(interval=0.01, max_consecutive_failures=10)

        # Should have run at least 3 times (2 failures + 1 success)
        assert call_count >= 3

    @pytest.mark.asyncio
    async def test_run_forever_stops_on_max_failures(self, mock_brotr: Brotr) -> None:
        """Test run_forever stops after max consecutive failures."""
        service = ConcreteService(brotr=mock_brotr)
        service.should_fail = True

        async with service:
            await service.run_forever(interval=0.01, max_consecutive_failures=3)

        # Should have stopped after 3 consecutive failures
        assert service.fail_count == 3

    @pytest.mark.asyncio
    async def test_run_forever_unlimited_failures_when_zero(self, mock_brotr: Brotr) -> None:
        """Test run_forever continues indefinitely when max_failures is 0."""
        service = ConcreteService(brotr=mock_brotr)
        service.should_fail = True

        async def stop_after_many_fails() -> None:
            while service.fail_count < 10:
                await asyncio.sleep(0.01)
            service.request_shutdown()

        async with service:
            asyncio.create_task(stop_after_many_fails())
            await service.run_forever(interval=0.001, max_consecutive_failures=0)

        # Should have run more than default max (5)
        assert service.fail_count >= 10


# ============================================================================
# Abstract Method Tests
# ============================================================================


class TestBaseServiceAbstract:
    """Tests for BaseService abstract behavior."""

    def test_cannot_instantiate_base_directly(self, mock_brotr: Brotr) -> None:
        """Test BaseService cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseService(brotr=mock_brotr)  # type: ignore[abstract]

    def test_must_implement_run(self, mock_brotr: Brotr) -> None:
        """Test subclass must implement run method."""

        class IncompleteService(BaseService):  # type: ignore[type-arg]
            SERVICE_NAME = "incomplete"

        with pytest.raises(TypeError):
            IncompleteService(brotr=mock_brotr)