"""
Base Service for BigBrotr Services.

Provides abstract base class for all services with:
- Logging
- Lifecycle management (start/stop)
- Factory methods (from_yaml/from_dict)
- Graceful error handling with max consecutive failures
- Prometheus metrics (automatic tracking in run_forever)

Services that need state persistence should implement their own
storage using dedicated database tables.
"""

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, TypeVar, cast

from pydantic import BaseModel, Field

from utils.yaml import load_yaml

from .brotr import Brotr
from .logger import Logger
from .metrics import (
    CONSECUTIVE_FAILURES,
    CYCLE_DURATION_SECONDS,
    CYCLES_TOTAL,
    ERRORS_TOTAL,
    ITEMS_PROCESSED_TOTAL,
    LAST_CYCLE_TIMESTAMP,
    SERVICE_INFO,
    MetricsConfig,
)


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

        # Set service info metric (static labels)
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

                # Success metrics
                duration = time.time() - cycle_start
                CYCLES_TOTAL.labels(service=self.SERVICE_NAME, status="success").inc()
                CYCLE_DURATION_SECONDS.labels(service=self.SERVICE_NAME).observe(duration)
                LAST_CYCLE_TIMESTAMP.labels(service=self.SERVICE_NAME).set(time.time())
                CONSECUTIVE_FAILURES.labels(service=self.SERVICE_NAME).set(0)

                consecutive_failures = 0  # Reset on success
                self._logger.info("cycle_completed", next_run_in_seconds=interval)

            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                # Let these propagate to allow proper shutdown
                raise

            except Exception as e:
                consecutive_failures += 1

                # Failure metrics
                CYCLES_TOTAL.labels(service=self.SERVICE_NAME, status="failed").inc()
                CONSECUTIVE_FAILURES.labels(service=self.SERVICE_NAME).set(consecutive_failures)
                ERRORS_TOTAL.labels(
                    service=self.SERVICE_NAME,
                    error_type=type(e).__name__,
                ).inc()

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
    # Metrics Helpers
    # -------------------------------------------------------------------------

    def record_items(
        self,
        success: int = 0,
        failed: int = 0,
        skipped: int = 0,
    ) -> None:
        """
        Record item processing metrics.

        Call this from run() to track units of work processed.
        Updates items_processed_total counter with appropriate labels.

        Args:
            success: Number of items processed successfully
            failed: Number of items that failed processing
            skipped: Number of items skipped (e.g., duplicates)
        """
        if success:
            ITEMS_PROCESSED_TOTAL.labels(
                service=self.SERVICE_NAME,
                result="success",
            ).inc(success)
        if failed:
            ITEMS_PROCESSED_TOTAL.labels(
                service=self.SERVICE_NAME,
                result="failed",
            ).inc(failed)
        if skipped:
            ITEMS_PROCESSED_TOTAL.labels(
                service=self.SERVICE_NAME,
                result="skipped",
            ).inc(skipped)

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
        config = cls.CONFIG_CLASS(**data)
        return cls(brotr=brotr, config=config, **kwargs)  # type: ignore[arg-type]

    # -------------------------------------------------------------------------
    # Context Manager
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> "BaseService[ConfigT]":
        """Start service on context entry."""
        # Clear shutdown event to mark service as running
        self._shutdown_event.clear()
        self._logger.info("started")
        return self

    async def __aexit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        """Stop service on context exit."""
        # Set shutdown event to mark service as stopped
        self._shutdown_event.set()
        self._logger.info("stopped")
