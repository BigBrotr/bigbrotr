"""
Prometheus metrics collection and HTTP exposition.

Defines module-level metric objects (singletons, thread-safe) that are shared
across all services. ``BaseService.run_forever()`` automatically records cycle
counts, durations, and failure streaks. Services add custom metrics through
``set_gauge()`` and ``inc_counter()`` on the base class.

The ``MetricsServer`` provides an async HTTP endpoint (via aiohttp) for
Prometheus scraping. Configuration is handled through ``MetricsConfig``,
which can be embedded in any service's YAML configuration.

Architecture:
    SERVICE_INFO:               Static metadata set once at startup.
    SERVICE_GAUGE:              Point-in-time values (current state).
    SERVICE_COUNTER:            Cumulative totals (monotonically increasing).
    CYCLE_DURATION_SECONDS:     Histogram for latency percentiles (p50/p95/p99).
"""

from __future__ import annotations

from aiohttp import web
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
)
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class MetricsConfig(BaseModel):
    """Configuration for the Prometheus metrics endpoint.

    Set ``host`` to ``"0.0.0.0"`` in container environments to allow
    external scraping. The endpoint is only started when ``enabled``
    is True.
    """

    enabled: bool = Field(default=False, description="Enable metrics collection")
    port: int = Field(default=8000, ge=1024, le=65535, description="Metrics HTTP port")
    host: str = Field(default="127.0.0.1", description="Metrics HTTP bind address")
    path: str = Field(default="/metrics", description="Metrics endpoint path")


# ---------------------------------------------------------------------------
# Common Service Metrics (auto-tracked by BaseService.run_forever)
# ---------------------------------------------------------------------------

# Static service metadata (set once at startup)
SERVICE_INFO = Info(
    "service",
    "Service information and metadata",
)

# Cycle duration histogram for latency percentile calculations (p50/p95/p99)
CYCLE_DURATION_SECONDS = Histogram(
    "cycle_duration_seconds",
    "Duration of service cycle in seconds",
    ["service"],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600),
)


# ---------------------------------------------------------------------------
# Generic Label-Based Metrics (used by services via set_gauge/inc_counter)
#
# Automatic labels (BaseService.run_forever):
#   gauge:   consecutive_failures, last_cycle_timestamp
#   counter: cycles_success, cycles_failed, errors_{type}
#
# Service-specific labels (examples):
#   gauge:   {service="validator", name="candidates"}
#   counter: {service="validator", name="total_promoted"}
# ---------------------------------------------------------------------------

SERVICE_GAUGE = Gauge(
    "service_gauge",
    "Service gauge values (point-in-time state)",
    ["service", "name"],
)

SERVICE_COUNTER = Counter(
    "service_counter",
    "Service counter values (cumulative totals)",
    ["service", "name"],
)


# ---------------------------------------------------------------------------
# HTTP Server
# ---------------------------------------------------------------------------


class MetricsServer:
    """Async HTTP server exposing a Prometheus-compatible /metrics endpoint.

    Built on aiohttp for compatibility with the async service architecture.
    The endpoint path is configurable via ``MetricsConfig.path``.

    Example:
        server = MetricsServer(MetricsConfig(port=8001))
        await server.start()
        # ... service runs ...
        await server.stop()
    """

    def __init__(self, config: MetricsConfig) -> None:
        self._config = config
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Start listening for Prometheus scrape requests.

        Returns immediately (no-op) if metrics are disabled in the
        configuration. Otherwise, binds an aiohttp server to the
        configured host and port.

        Raises:
            OSError: If the port is already in use or binding fails.
        """
        if not self._config.enabled:
            return

        app = web.Application()
        app.router.add_get(self._config.path, self._handle_metrics)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()

        site = web.TCPSite(
            self._runner,
            self._config.host,
            self._config.port,
        )
        await site.start()

    async def stop(self) -> None:
        """Stop the HTTP server and release resources.

        Idempotent: safe to call if the server was never started or
        has already been stopped.
        """
        if self._runner:
            await self._runner.cleanup()

    @staticmethod
    async def _handle_metrics(_request: web.Request) -> web.Response:
        """Serve the latest Prometheus metrics in exposition format."""
        output = generate_latest()
        return web.Response(
            body=output,
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )


async def start_metrics_server(
    config: MetricsConfig | None = None,
) -> MetricsServer:
    """Convenience function to create and start a metrics server.

    Args:
        config: Metrics configuration. Uses defaults if not provided.

    Returns:
        A running MetricsServer instance. Caller should call ``stop()``
        during shutdown to release the bound port.
    """
    config = config or MetricsConfig()
    server = MetricsServer(config)
    await server.start()
    return server
