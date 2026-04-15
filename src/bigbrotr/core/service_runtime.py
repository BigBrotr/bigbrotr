"""Shared runtime helpers for service lifecycle orchestration."""

from __future__ import annotations

import asyncio
import signal
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol


if TYPE_CHECKING:
    from types import TracebackType

from .logger import Logger
from .metrics import (
    CYCLE_DURATION_SECONDS,
    SERVICE_INFO,
    MetricsConfig,
    MetricsServer,
    start_metrics_server,
)


class ServiceLoopConfig(Protocol):
    """Configuration attributes required by the shared service loop."""

    interval: float
    max_consecutive_failures: int
    metrics: MetricsConfig

    def model_dump(self) -> dict[str, object]: ...


class LoopService(Protocol):
    """Protocol for a service that can run repeated cleanup + work cycles."""

    _logger: Logger

    @property
    def service_name(self) -> str: ...

    @property
    def config(self) -> ServiceLoopConfig: ...

    @property
    def is_running(self) -> bool: ...

    async def cleanup(self) -> int: ...

    async def run(self) -> None: ...

    async def wait(self, delay: float) -> bool: ...

    def inc_counter(self, name: str, value: float = 1) -> None: ...

    def set_gauge(self, name: str, value: float) -> None: ...


class HostedService(LoopService, Protocol):
    """Protocol for a service that can be hosted by the CLI runtime."""

    def request_shutdown(self) -> None: ...

    async def run_forever(self) -> None: ...

    async def __aenter__(self) -> HostedService: ...

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None: ...


StartMetricsServer = Callable[[MetricsConfig | None], Awaitable[MetricsServer]]


class ServiceRunState:
    """Tracks shutdown state and interruptible waits for a service."""

    def __init__(self) -> None:
        self._shutdown_event = asyncio.Event()

    @property
    def shutdown_event(self) -> asyncio.Event:
        """Expose the shutdown event for compatibility with existing tests."""
        return self._shutdown_event

    def activate(self) -> None:
        """Mark the service as running."""
        self._shutdown_event.clear()

    def deactivate(self) -> None:
        """Mark the service as stopped."""
        self._shutdown_event.set()

    def request_shutdown(self) -> None:
        """Request graceful shutdown."""
        self._shutdown_event.set()

    @property
    def is_running(self) -> bool:
        """Whether the service is still active."""
        return not self._shutdown_event.is_set()

    async def wait(self, timeout: float) -> bool:  # noqa: ASYNC109
        """Wait for shutdown or timeout, whichever comes first."""
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False


class ServiceLoopRunner:
    """Runs the continuous cycle loop for a service."""

    def __init__(self, service: LoopService) -> None:
        self._service = service

    async def run_forever(self) -> None:
        """Run service cleanup and cycle logic until shutdown is requested."""
        interval = self._service.config.interval
        max_consecutive_failures = self._service.config.max_consecutive_failures
        metrics_enabled = self._service.config.metrics.enabled

        if metrics_enabled:
            SERVICE_INFO.info({"service": self._service.service_name})

        self._service._logger.info(
            "run_forever_started",
            interval=interval,
            max_consecutive_failures=max_consecutive_failures,
        )

        consecutive_failures = 0

        while self._service.is_running:
            cycle_start = time.monotonic()

            try:
                self._service._logger.info("cleanup_started")
                removed = await self._service.cleanup()
                self._service._logger.info("cleanup_completed", removed=removed)

                self._service._logger.info("run_started", config=self._service.config.model_dump())
                await self._service.run()
                run_duration = time.monotonic() - cycle_start
                self._service._logger.info("run_completed", duration_s=run_duration)

                self._service.inc_counter("cycles_success")
                if metrics_enabled:
                    CYCLE_DURATION_SECONDS.labels(service=self._service.service_name).observe(
                        run_duration
                    )
                self._service.set_gauge("last_cycle_timestamp", time.time())
                self._service.set_gauge("consecutive_failures", 0)
                consecutive_failures = 0

            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise

            except Exception as exc:  # Intentionally broad: cycle-level boundary
                consecutive_failures += 1

                self._service.inc_counter("cycles_failed")
                self._service.set_gauge("consecutive_failures", consecutive_failures)
                self._service.inc_counter(f"errors_{type(exc).__name__}")

                self._service._logger.error(
                    "run_cycle_error",
                    error=str(exc),
                    consecutive_failures=consecutive_failures,
                )

                if (
                    max_consecutive_failures > 0
                    and consecutive_failures >= max_consecutive_failures
                ):
                    self._service._logger.critical(
                        "max_consecutive_failures_reached",
                        failures=consecutive_failures,
                        limit=max_consecutive_failures,
                    )
                    break

            elapsed = time.monotonic() - cycle_start
            remaining = max(0.0, interval - elapsed)
            if await self._service.wait(remaining):
                break

        self._service._logger.info("run_forever_stopped")


class ServiceCliRunner:
    """Runs a service in one-shot or continuous CLI mode."""

    def __init__(
        self,
        service: HostedService,
        *,
        logger: Logger | None = None,
        service_name: str | None = None,
        start_metrics_server_fn: StartMetricsServer = start_metrics_server,
    ) -> None:
        self._service = service
        self._logger = logger or Logger("cli")
        self._service_name = service_name or service.service_name
        self._start_metrics_server = start_metrics_server_fn

    async def run(self, *, once: bool) -> int:
        """Run the configured service in one-shot or continuous mode."""
        if once:
            return await self.run_once()
        return await self.run_continuous()

    async def run_once(self) -> int:
        """Run a single cleanup + cycle for the service."""
        try:
            async with self._service:
                await self._service.cleanup()
                await self._service.run()
            self._logger.info(f"{self._service_name}_completed")
            return 0
        except Exception as exc:  # Intentionally broad: CLI error boundary
            self._logger.error(f"{self._service_name}_failed", error=str(exc))
            return 1

    async def run_continuous(self) -> int:
        """Run the service with metrics and signal handling."""
        metrics_config = self._service.config.metrics
        metrics_server = await self._start_metrics_server(metrics_config)

        if metrics_config.enabled:
            self._logger.info(
                "metrics_server_started",
                host=metrics_config.host,
                port=metrics_config.port,
                path=metrics_config.path,
            )

        remove_signal_handlers = self._install_signal_handlers()

        try:
            async with self._service:
                await self._service.run_forever()
            return 0
        except Exception as exc:  # Intentionally broad: CLI error boundary
            self._logger.error(f"{self._service_name}_failed", error=str(exc))
            return 1
        finally:
            remove_signal_handlers()
            await metrics_server.stop()
            if metrics_config.enabled:
                self._logger.info("metrics_server_stopped")

    def _install_signal_handlers(self) -> Callable[[], None]:
        """Register shutdown signal handlers and return a cleanup callback."""
        loop = asyncio.get_running_loop()
        registered: list[signal.Signals] = []

        def handle_signal(sig: signal.Signals) -> None:
            self._logger.info("shutdown_signal", signal=sig.name)
            self._service.request_shutdown()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, handle_signal, sig)
            except NotImplementedError:
                self._logger.warning("signal_handlers_unsupported")
                break
            registered.append(sig)

        def cleanup() -> None:
            for sig in registered:
                loop.remove_signal_handler(sig)

        return cleanup
