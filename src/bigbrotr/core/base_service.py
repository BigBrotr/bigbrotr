"""
Abstract base class for long-running BigBrotr services.

``BaseService[ConfigT]`` provides the standard lifecycle for all services:
structured logging via [Logger][bigbrotr.core.logger.Logger], graceful
shutdown via ``asyncio.Event``, configurable interval-based cycling with
[run_forever()][bigbrotr.core.base_service.BaseService.run_forever],
consecutive failure limits, and automatic Prometheus metrics tracking via
[MetricsServer][bigbrotr.core.metrics.MetricsServer].

Services persist operational state through
[Brotr.upsert_service_state()][bigbrotr.core.brotr.Brotr.upsert_service_state]
and
[Brotr.get_service_state()][bigbrotr.core.brotr.Brotr.get_service_state]
rather than in-memory storage.

See Also:
    [Brotr][bigbrotr.core.brotr.Brotr]: Database interface injected into every
        service.
    [Pool][bigbrotr.core.pool.Pool]: Connection pool managed by Brotr.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]: Base
        configuration model for all services.
"""

import asyncio
import time
from abc import ABC, abstractmethod
from types import TracebackType
from typing import Any, ClassVar, Generic, Self, TypeVar, cast

from pydantic import BaseModel, Field

from bigbrotr.models.constants import ServiceName

from .brotr import Brotr
from .logger import Logger
from .metrics import (
    CYCLE_DURATION_SECONDS,
    SERVICE_COUNTER,
    SERVICE_GAUGE,
    SERVICE_INFO,
    MetricsConfig,
)
from .yaml import load_yaml


# ---------------------------------------------------------------------------
# Base Configuration
# ---------------------------------------------------------------------------


class BaseServiceConfig(BaseModel):
    """Base configuration shared by all services that run in a loop.

    Subclass this to add service-specific fields. The fields defined here
    control the
    [run_forever()][bigbrotr.core.base_service.BaseService.run_forever]
    cycle interval, failure tolerance, and Prometheus metrics exposition.

    See Also:
        [BaseService][bigbrotr.core.base_service.BaseService]: The abstract
            service class that consumes this configuration.
        [MetricsConfig][bigbrotr.core.metrics.MetricsConfig]: Embedded
            configuration for the Prometheus metrics endpoint.
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


# Bound TypeVar ensuring all service configs inherit from BaseServiceConfig
ConfigT = TypeVar("ConfigT", bound=BaseServiceConfig)


class BaseService(ABC, Generic[ConfigT]):
    """Abstract base class for all BigBrotr services.

    Subclasses must set ``SERVICE_NAME`` to a unique string identifier,
    set ``CONFIG_CLASS`` to their Pydantic config model, and implement
    [run()][bigbrotr.core.base_service.BaseService.run] with the main
    service logic.

    Attributes:
        SERVICE_NAME: Unique service identifier used in logging and metrics.
        CONFIG_CLASS: Pydantic model class used by factory methods to parse
            configuration from YAML/dict sources.
        _brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface for
            all database operations.
        _config: Typed service configuration (defaults from ``CONFIG_CLASS``).
        _logger: [Logger][bigbrotr.core.logger.Logger] named after the service.
        _shutdown_event: ``asyncio.Event`` controlling the run loop. Clear
            means the service is running; set means shutdown was requested.

    Note:
        The lifecycle pattern is: ``async with brotr:`` then
        ``async with service:`` then
        [run_forever()][bigbrotr.core.base_service.BaseService.run_forever]
        (or a single
        [run()][bigbrotr.core.base_service.BaseService.run] call with
        ``--once``). The async context manager clears/sets the shutdown
        event on entry/exit, while
        [run_forever()][bigbrotr.core.base_service.BaseService.run_forever]
        handles the cycle loop, metrics, and failure tracking.

    See Also:
        [Brotr][bigbrotr.core.brotr.Brotr]: Database interface injected via
            the constructor.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base configuration model with interval, failure limits, and
            metrics settings.
        [Logger][bigbrotr.core.logger.Logger]: Structured logging used
            internally.
        [MetricsServer][bigbrotr.core.metrics.MetricsServer]: Prometheus
            endpoint started alongside the service.
    """

    SERVICE_NAME: ClassVar[ServiceName]
    CONFIG_CLASS: ClassVar[type[BaseModel]]

    def __init__(self, brotr: Brotr, config: ConfigT | None = None) -> None:
        self._brotr = brotr
        self._config: ConfigT = (
            config if config is not None else cast("ConfigT", self.CONFIG_CLASS())
        )
        self._logger = Logger(self.SERVICE_NAME)
        self._shutdown_event = asyncio.Event()

    @property
    def config(self) -> ConfigT:
        """The typed service configuration (read-only)."""
        return self._config

    @abstractmethod
    async def run(self) -> None:
        """Execute one cycle of the service's main logic.

        Called repeatedly by
        [run_forever()][bigbrotr.core.base_service.BaseService.run_forever].
        Implementations should perform a bounded unit of work and return.
        Long-running work should periodically check
        [is_running][bigbrotr.core.base_service.BaseService.is_running]
        for early exit.

        See Also:
            [run_forever()][bigbrotr.core.base_service.BaseService.run_forever]:
                The loop that calls this method repeatedly.
        """
        ...

    def request_shutdown(self) -> None:
        """Request a graceful shutdown of the service.

        Safe to call from signal handlers or other threads because
        setting an ``asyncio.Event`` is atomic. The next
        [wait()][bigbrotr.core.base_service.BaseService.wait] call in
        [run_forever()][bigbrotr.core.base_service.BaseService.run_forever]
        will detect the signal and break the loop.

        See Also:
            [is_running][bigbrotr.core.base_service.BaseService.is_running]:
                Property that reflects whether shutdown has been requested.
        """
        self._shutdown_event.set()

    @property
    def is_running(self) -> bool:
        """Whether the service is still active (shutdown not yet requested)."""
        return not self._shutdown_event.is_set()

    async def wait(self, timeout: float) -> bool:  # noqa: ASYNC109
        """Wait for either a shutdown signal or a timeout to elapse.

        Returns ``True`` if shutdown was requested during the wait, or
        ``False`` if the timeout expired normally. Use this instead of
        ``asyncio.sleep()`` to enable interruptible waits.

        Note:
            This method is used internally by
            [run_forever()][bigbrotr.core.base_service.BaseService.run_forever]
            for the inter-cycle sleep. Subclasses can also use it for
            long-running operations that should be interruptible by a
            [request_shutdown()][bigbrotr.core.base_service.BaseService.request_shutdown]
            call.
        """
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def run_forever(self) -> None:
        """Run the service in an infinite loop with interval-based cycling.

        Repeatedly calls
        [run()][bigbrotr.core.base_service.BaseService.run], sleeping for
        ``config.interval`` seconds between cycles. Exits when shutdown
        is requested via
        [request_shutdown()][bigbrotr.core.base_service.BaseService.request_shutdown]
        or when the consecutive failure limit
        (``config.max_consecutive_failures``) is reached. A value of ``0``
        disables the failure limit.

        Prometheus metrics are tracked automatically:
        ``cycles_success``, ``cycles_failed``,
        ``errors_{ExceptionType}`` (via
        ``SERVICE_COUNTER``),
        ``consecutive_failures``, ``last_cycle_timestamp`` (via
        ``SERVICE_GAUGE``), and
        ``cycle_duration_seconds`` (via
        ``CYCLE_DURATION_SECONDS``).

        The consecutive failure counter resets after each successful cycle.
        ``CancelledError``, ``KeyboardInterrupt``, and ``SystemExit`` always
        propagate immediately without being counted as failures.

        Note:
            The inter-cycle sleep uses
            [wait()][bigbrotr.core.base_service.BaseService.wait] rather
            than ``asyncio.sleep()`` so that a shutdown signal can interrupt
            the wait immediately instead of blocking until the next cycle.

        See Also:
            [run()][bigbrotr.core.base_service.BaseService.run]: The abstract
                method called each cycle.
            [request_shutdown()][bigbrotr.core.base_service.BaseService.request_shutdown]:
                Trigger graceful exit from this loop.
        """
        # Fallback defaults ensure compatibility if config is not BaseServiceConfig
        interval = getattr(self._config, "interval", 300.0)
        max_consecutive_failures = getattr(self._config, "max_consecutive_failures", 5)
        metrics_enabled = self._config.metrics.enabled

        # Publish static service metadata once at startup
        if metrics_enabled:
            SERVICE_INFO.info({"service": self.SERVICE_NAME})

        self._logger.info(
            "run_forever_started",
            interval=interval,
            max_consecutive_failures=max_consecutive_failures,
        )

        consecutive_failures = 0

        while self.is_running:
            cycle_start = time.monotonic()

            try:
                await self.run()

                duration = time.monotonic() - cycle_start
                self.inc_counter("cycles_success")
                if metrics_enabled:
                    CYCLE_DURATION_SECONDS.labels(service=self.SERVICE_NAME).observe(duration)
                self.set_gauge("last_cycle_timestamp", time.time())
                self.set_gauge("consecutive_failures", 0)

                consecutive_failures = 0
                self._logger.info("cycle_completed", next_cycle_s=interval)

            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise  # Always propagate shutdown signals

            except Exception as e:  # Intentionally broad: top-level error boundary for run_forever
                consecutive_failures += 1

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
    def from_yaml(cls, config_path: str, brotr: Brotr, **kwargs: Any) -> Self:
        """Create a service instance from a YAML configuration file.

        Delegates to [load_yaml()][bigbrotr.core.yaml.load_yaml] for safe
        YAML parsing, then to
        [from_dict()][bigbrotr.core.base_service.BaseService.from_dict]
        for construction.

        Args:
            config_path: Path to the YAML file.
            brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface
                for the service.
            **kwargs: Additional keyword arguments passed to the constructor.

        See Also:
            [from_dict()][bigbrotr.core.base_service.BaseService.from_dict]:
                Construct from a pre-parsed dictionary.
        """
        return cls.from_dict(load_yaml(config_path), brotr=brotr, **kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any], brotr: Brotr, **kwargs: Any) -> Self:
        """Create a service instance from a configuration dictionary.

        Parses ``data`` into the service's ``CONFIG_CLASS`` Pydantic model.

        Args:
            data: Configuration dictionary parsed into ``CONFIG_CLASS``.
            brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface
                for the service.
            **kwargs: Additional keyword arguments passed to the constructor.
        """
        config = cast("ConfigT", cls.CONFIG_CLASS(**data))
        return cls(brotr=brotr, config=config, **kwargs)

    # -------------------------------------------------------------------------
    # Context Manager
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> Self:
        """Mark the service as running on context entry."""
        self._shutdown_event.clear()
        self._logger.info("service_started")
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        """Signal shutdown on context exit."""
        self._shutdown_event.set()
        self._logger.info("service_stopped")

    # -------------------------------------------------------------------------
    # Custom Metrics
    # -------------------------------------------------------------------------

    def set_gauge(self, name: str, value: float) -> None:
        """Set a named gauge metric for this service.

        Records a point-in-time value via the shared
        ``SERVICE_GAUGE`` Prometheus
        metric with ``service`` and ``name`` labels. No-op if metrics
        are disabled in
        [MetricsConfig][bigbrotr.core.metrics.MetricsConfig].

        Args:
            name: Metric name (e.g. ``"pending"``, ``"queue_size"``).
            value: Current numeric value.

        See Also:
            [inc_counter()][bigbrotr.core.base_service.BaseService.inc_counter]:
                Increment a cumulative counter metric.
        """
        if not self._config.metrics.enabled:
            return
        SERVICE_GAUGE.labels(service=self.SERVICE_NAME, name=name).set(value)

    def inc_counter(self, name: str, value: float = 1) -> None:
        """Increment a named counter metric for this service.

        Records a monotonically increasing total via the shared
        ``SERVICE_COUNTER`` Prometheus
        metric. Counters persist across cycles, making them suitable for
        cumulative totals. No-op if metrics are disabled in
        [MetricsConfig][bigbrotr.core.metrics.MetricsConfig].

        Args:
            name: Metric name (e.g. ``"total_processed"``,
                ``"total_promoted"``).
            value: Amount to increment (default: 1).

        See Also:
            [set_gauge()][bigbrotr.core.base_service.BaseService.set_gauge]:
                Set a point-in-time gauge metric.
        """
        if not self._config.metrics.enabled:
            return
        SERVICE_COUNTER.labels(service=self.SERVICE_NAME, name=name).inc(value)
