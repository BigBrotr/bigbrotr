"""
Base Service for BigBrotr Services.

Provides abstract base class for all services with:
- Logging
- Lifecycle management (start/stop)
- Factory methods (from_yaml/from_dict)
- Graceful error handling with max consecutive failures
- Prometheus metrics (automatic tracking in run_forever)

Also provides mixins for common service patterns:
- NetworkSemaphoreMixin: Per-network concurrency limiting

Services that need state persistence should implement their own
storage using dedicated database tables.
"""

import asyncio
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar, cast

from pydantic import BaseModel, Field

from logger import Logger
from utils.network import NetworkType
from utils.yaml import load_yaml

from .brotr import Brotr
from .metrics import (
    CYCLE_DURATION_SECONDS,
    SERVICE_COUNTER,
    SERVICE_GAUGE,
    SERVICE_INFO,
    MetricsConfig,
)


if TYPE_CHECKING:
    from utils.network import NetworkConfig


# =============================================================================
# Base Configuration
# =============================================================================


class BaseServiceConfig(BaseModel):
    """
    Base configuration for all continuous services.

    All services that run in a loop (via run_forever) should inherit from this.
    """

    interval: float = Field(
        default=300.0,
        ge=60.0,
        description="Seconds between run cycles",
    )
    max_consecutive_failures: int = Field(
        default=5,
        ge=0,
        description="Stop after this many consecutive errors (0 = unlimited)",
    )
    metrics: MetricsConfig = Field(
        default_factory=MetricsConfig,
        description="Prometheus metrics configuration",
    )


# Type variable for service configuration (bound to BaseServiceConfig for type safety)
ConfigT = TypeVar("ConfigT", bound=BaseServiceConfig)


class BaseService(ABC, Generic[ConfigT]):
    """
    Abstract base class for all BigBrotr services.

    Subclasses must:
    - Set SERVICE_NAME class attribute
    - Set CONFIG_CLASS for automatic config parsing
    - Implement run() method for main service logic

    Services that need persistent state should implement their own
    storage mechanism using dedicated database tables.

    Class Attributes:
        SERVICE_NAME: Unique identifier for the service (used in logging)
        CONFIG_CLASS: Pydantic model class for configuration parsing

    Instance Attributes:
        _brotr: Database interface (access pool via _brotr.pool)
        _config: Service configuration (Pydantic model, uses CONFIG_CLASS defaults if not provided)
        _logger: Structured logger
        _shutdown_event: Event for graceful shutdown (single source of truth)
                        Not set = service is running
                        Set = shutdown requested
    """

    SERVICE_NAME: ClassVar[str] = "base_service"
    CONFIG_CLASS: ClassVar[type[BaseModel]]

    def __init__(self, brotr: Brotr, config: ConfigT | None = None) -> None:
        self._brotr = brotr
        self._config: ConfigT = (
            config if config is not None else cast("ConfigT", self.CONFIG_CLASS())
        )
        self._logger = Logger(self.SERVICE_NAME)
        # Use shutdown event as single source of truth to avoid race conditions
        # Event not set = service is running, Event set = shutdown requested
        self._shutdown_event = asyncio.Event()

    @property
    def config(self) -> ConfigT:
        """Get service configuration (typed to CONFIG_CLASS)."""
        return self._config

    @abstractmethod
    async def run(self) -> None:
        """Execute main service logic."""
        ...

    def request_shutdown(self) -> None:
        """
        Request graceful shutdown (sync-safe for signal handlers).

        Thread-safe: Setting an asyncio.Event is atomic and safe to call
        from signal handlers or other threads.
        """
        self._shutdown_event.set()

    @property
    def is_running(self) -> bool:
        """
        Check if service is running.

        Returns True if shutdown has NOT been requested.
        """
        return not self._shutdown_event.is_set()

    async def wait(self, timeout: float) -> bool:
        """
        Wait for shutdown event or timeout.

        Returns True if shutdown was requested, False if timeout expired.
        Use in service loops for interruptible waits.
        """
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def run_forever(self) -> None:
        """
        Run service continuously with interval between cycles.

        Calls run() repeatedly until shutdown is requested or max consecutive
        failures is reached. Each cycle is followed by an interruptible wait.

        Automatically tracks Prometheus metrics:
            - cycles_total: Counter of cycles by status (success/failed)
            - cycle_duration_seconds: Histogram of cycle durations
            - consecutive_failures: Gauge of current failure streak
            - last_cycle_timestamp_seconds: Gauge of last successful cycle
            - errors_total: Counter of errors by type

        Reads from config:
            - interval: Seconds to wait between run() cycles
            - max_consecutive_failures: Stop after this many consecutive errors (0 = unlimited)

        Example:
            >>> async with MyService(brotr, config) as service:
            ...     await service.run_forever()

        Note:
            - Use request_shutdown() to stop gracefully from signal handlers
            - Consecutive failure counter resets after each successful run()
            - CancelledError, KeyboardInterrupt, SystemExit propagate immediately
        """
        # Read from config (with fallback defaults for non-BaseServiceConfig)
        interval = getattr(self._config, "interval", 300.0)
        max_consecutive_failures = getattr(self._config, "max_consecutive_failures", 5)
        metrics_enabled = self._config.metrics.enabled

        # Set service info metric (static labels)
        if metrics_enabled:
            SERVICE_INFO.info({"service": self.SERVICE_NAME})

        self._logger.info(
            "run_forever_started",
            interval=interval,
            max_consecutive_failures=max_consecutive_failures,
        )

        consecutive_failures = 0

        # Use is_running property which checks shutdown_event atomically
        while self.is_running:
            cycle_start = time.time()

            try:
                await self.run()

                # Success metrics (using generic SERVICE_COUNTER/GAUGE)
                duration = time.time() - cycle_start
                self.inc_counter("cycles_success")
                if metrics_enabled:
                    CYCLE_DURATION_SECONDS.labels(service=self.SERVICE_NAME).observe(duration)
                self.set_gauge("last_cycle_timestamp", time.time())
                self.set_gauge("consecutive_failures", 0)

                consecutive_failures = 0  # Reset on success
                self._logger.info("cycle_completed", next_cycle_s=interval)

            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                # Let these propagate to allow proper shutdown
                raise

            except Exception as e:
                consecutive_failures += 1

                # Failure metrics (using generic SERVICE_COUNTER/GAUGE)
                self.inc_counter("cycles_failed")
                self.set_gauge("consecutive_failures", consecutive_failures)
                self.inc_counter(f"errors_{type(e).__name__}")

                self._logger.error(
                    "run_cycle_error",
                    error=str(e),
                    consecutive_failures=consecutive_failures,
                )

                if (
                    max_consecutive_failures > 0
                    and consecutive_failures >= max_consecutive_failures
                ):
                    self._logger.critical(
                        "max_consecutive_failures_reached",
                        failures=consecutive_failures,
                        limit=max_consecutive_failures,
                    )
                    break

            if await self.wait(interval):
                break

        self._logger.info("run_forever_stopped")

    # -------------------------------------------------------------------------
    # Factory Methods
    # -------------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, config_path: str, brotr: Brotr, **kwargs: Any) -> "BaseService[ConfigT]":
        """Create service from YAML configuration file."""
        return cls.from_dict(load_yaml(config_path), brotr=brotr, **kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any], brotr: Brotr, **kwargs: Any) -> "BaseService[ConfigT]":
        """Create service from dictionary configuration."""
        config = cast("ConfigT", cls.CONFIG_CLASS(**data))
        return cls(brotr=brotr, config=config, **kwargs)

    # -------------------------------------------------------------------------
    # Context Manager
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> "BaseService[ConfigT]":
        """Start service on context entry."""
        # Clear shutdown event to mark service as running
        self._shutdown_event.clear()
        self._logger.info("service_started")
        return self

    async def __aexit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        """Stop service on context exit."""
        # Set shutdown event to mark service as stopped
        self._shutdown_event.set()
        self._logger.info("service_stopped")

    # -------------------------------------------------------------------------
    # Custom Metrics
    # -------------------------------------------------------------------------

    def set_gauge(self, name: str, value: float) -> None:
        """
        Set a custom gauge metric for this service.

        Uses SERVICE_GAUGE with labels for service name and metric name.
        Each service can track its own named values.

        Args:
            name: Metric name (e.g., "pending", "active", "queue_size")
            value: Numeric value to set

        Example:
            self.set_gauge("pending", 100)
            # Creates: service_gauge{service="myservice", name="pending"} 100

        Note:
            No-op if metrics.enabled is False.
        """
        if not self._config.metrics.enabled:
            return
        SERVICE_GAUGE.labels(service=self.SERVICE_NAME, name=name).set(value)

    def inc_counter(self, name: str, value: float = 1) -> None:
        """
        Increment a custom counter metric for this service.

        Uses SERVICE_COUNTER with labels for service name and metric name.
        Counters are cumulative and persist across cycles - use for totals.

        Args:
            name: Metric name (e.g., "total_processed", "total_promoted")
            value: Amount to increment (default: 1)

        Example:
            self.inc_counter("total_promoted", 5)
            # Increments: service_counter{service="myservice", name="total_promoted"} by 5

        Note:
            No-op if metrics.enabled is False.
        """
        if not self._config.metrics.enabled:
            return
        SERVICE_COUNTER.labels(service=self.SERVICE_NAME, name=name).inc(value)


# =============================================================================
# Mixins
# =============================================================================


class NetworkSemaphoreMixin:
    """Mixin for services that use per-network concurrency semaphores.

    Provides methods to initialize and access asyncio semaphores that limit
    concurrent operations per network type (clearnet, tor, i2p, loki).

    Used by Validator and Monitor to prevent overwhelming network resources,
    especially important for Tor where too many simultaneous connections
    can degrade performance.

    The _semaphores dict is created by _init_semaphores() and should be called
    at the start of each run cycle to pick up configuration changes.
    """

    _semaphores: dict[NetworkType, asyncio.Semaphore]

    def _init_semaphores(self, networks: "NetworkConfig") -> None:
        """Initialize per-network concurrency semaphores.

        Creates an asyncio.Semaphore for each network type with max_tasks
        from the network configuration. Should be called at the start of
        each run cycle to pick up configuration changes.

        Args:
            networks: Network configuration with max_tasks per network type.
        """
        self._semaphores = {
            network: asyncio.Semaphore(networks.get(network).max_tasks) for network in NetworkType
        }

    def _get_semaphore(self, network: NetworkType) -> asyncio.Semaphore | None:
        """Get the semaphore for a specific network type.

        Args:
            network: The network type to get the semaphore for.

        Returns:
            The semaphore for the network, or None if not found.
        """
        return self._semaphores.get(network)
