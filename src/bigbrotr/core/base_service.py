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

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Any, ClassVar, Generic, Self, TypeVar, cast

from pydantic import BaseModel, Field

from .brotr import Brotr
from .logger import Logger
from .metrics import (
    SERVICE_COUNTER,
    SERVICE_GAUGE,
    MetricsConfig,
)
from .service_runtime import ServiceCycleRunner, ServiceRuntimeState
from .yaml import load_yaml


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
        le=604_800.0,
        description="Target seconds between cycle starts (fixed-schedule)",
    )
    max_consecutive_failures: int = Field(
        default=5,
        ge=0,
        le=100,
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

    SERVICE_NAME: ClassVar[str]
    CONFIG_CLASS: ClassVar[type[BaseModel]]

    def __init__(self, brotr: Brotr, config: ConfigT | None = None) -> None:
        self._brotr = brotr
        self._config: ConfigT = (
            config if config is not None else cast("ConfigT", self.CONFIG_CLASS())
        )
        self._logger = Logger(self.SERVICE_NAME)
        self._runtime_state = ServiceRuntimeState()
        self._cycle_runner = ServiceCycleRunner(self)
        self._shutdown_event = self._runtime_state.shutdown_event

    @property
    def config(self) -> ConfigT:
        """The typed service configuration (read-only)."""
        return self._config

    @property
    def service_name(self) -> str:
        """Stable string identifier for the service instance."""
        return str(self.SERVICE_NAME)

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
        self._runtime_state.request_shutdown()

    @property
    def is_running(self) -> bool:
        """Whether the service is still active (shutdown not yet requested)."""
        return self._runtime_state.is_running

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
        return await self._runtime_state.wait(timeout)

    async def run_forever(self) -> None:
        """Run the service in an infinite loop with interval-based cycling.

        Repeatedly calls
        [run()][bigbrotr.core.base_service.BaseService.run] on a
        fixed-schedule cadence: the next cycle starts ``config.interval``
        seconds after the previous one started, subtracting the elapsed
        cycle duration. If a cycle takes longer than the interval, the
        next cycle starts immediately with zero wait. Exits when shutdown
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
        await self._cycle_runner.run_forever()

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

    async def __aenter__(self) -> Self:
        """Mark the service as running on context entry."""
        self._runtime_state.activate()
        self._logger.info("service_started")
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        """Signal shutdown on context exit."""
        self._runtime_state.deactivate()
        self._logger.info("service_stopped")

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

    def inc_gauge(self, name: str, value: float = 1) -> None:
        """Increment a named gauge metric for this service.

        Increments a point-in-time value via the shared ``SERVICE_GAUGE``
        Prometheus metric. No-op if metrics are disabled.

        Args:
            name: Metric name (e.g. ``"relays_connected"``).
            value: Amount to increment (default: 1).
        """
        if not self._config.metrics.enabled:
            return
        SERVICE_GAUGE.labels(service=self.SERVICE_NAME, name=name).inc(value)

    def dec_gauge(self, name: str, value: float = 1) -> None:
        """Decrement a named gauge metric for this service.

        Decrements a point-in-time value via the shared ``SERVICE_GAUGE``
        Prometheus metric. No-op if metrics are disabled.

        Args:
            name: Metric name (e.g. ``"active_connections"``).
            value: Amount to decrement (default: 1).
        """
        if not self._config.metrics.enabled:
            return
        SERVICE_GAUGE.labels(service=self.SERVICE_NAME, name=name).dec(value)

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

    @abstractmethod
    async def cleanup(self) -> int:
        """Pre-cycle cleanup hook invoked by ``run_forever()`` before ``run()``.

        Called automatically at the beginning of each cycle. Services
        implement this to remove stale state, expired records, or any
        other housekeeping that should precede the main cycle logic.

        Returns:
            Number of items removed or cleaned up (0 if nothing to do).

        See Also:
            [run_forever()][bigbrotr.core.base_service.BaseService.run_forever]:
                The loop that calls this method before each ``run()``.
        """
