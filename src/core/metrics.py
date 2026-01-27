"""
Prometheus Metrics.

Provides production-ready metrics collection and exposition:
- Common metrics for all services (cycles, items, errors, duration)
- MetricsConfig for YAML configuration
- MetricsServer for HTTP exposition

Design principles:
- Metrics defined at module level (singleton pattern, thread-safe)
- Labels for service differentiation, not separate metrics
- Uses prometheus_client directly (no custom wrappers)
- Async HTTP server using aiohttp (already a project dependency)

Usage:
    from core.metrics import start_metrics_server

    # Common metrics are updated automatically by BaseService.run_forever()
    # Start server (handled by service entrypoint)
    server = await start_metrics_server(config)
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


# =============================================================================
# Configuration
# =============================================================================


class MetricsConfig(BaseModel):
    """
    Prometheus metrics configuration.

    Attributes:
        enabled: Enable metrics collection and HTTP server
        port: HTTP port for /metrics endpoint
        host: HTTP bind address (0.0.0.0 for container environments)
        path: URL path for metrics endpoint
    """

    enabled: bool = Field(default=False, description="Enable metrics collection")
    port: int = Field(default=8000, ge=1024, le=65535, description="Metrics HTTP port")
    host: str = Field(default="127.0.0.1", description="Metrics HTTP bind address")
    path: str = Field(default="/metrics", description="Metrics endpoint path")


# =============================================================================
# Common Service Metrics
# =============================================================================
#
# Simplified metrics architecture:
# - SERVICE_INFO: Static metadata (set once at startup)
# - SERVICE_GAUGE: Point-in-time values (current state)
# - SERVICE_COUNTER: Cumulative totals (monotonically increasing)
# - CYCLE_DURATION_SECONDS: Histogram for percentiles (p50/p95/p99)
#
# BaseService.run_forever() automatically tracks cycles via SERVICE_COUNTER
# and SERVICE_GAUGE. Services add their own metrics using set_gauge()/inc_counter().
# =============================================================================

# Service information (static labels set once at startup)
SERVICE_INFO = Info(
    "service",
    "Service information and metadata",
)

# Histogram for cycle duration - kept separate for percentile calculations
# Cannot be replaced with gauge/counter as histograms provide p50/p95/p99
CYCLE_DURATION_SECONDS = Histogram(
    "cycle_duration_seconds",
    "Duration of service cycle in seconds",
    ["service"],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600),
)


# =============================================================================
# Generic Service Metrics
# =============================================================================
#
# All service metrics flow through these two generic metrics with labels.
# This provides a consistent interface while allowing flexibility.
#
# Automatic metrics (set by BaseService.run_forever()):
#   - service_gauge{name="consecutive_failures"} - current failure streak
#   - service_gauge{name="last_cycle_timestamp"} - unix timestamp of last cycle
#   - service_counter{name="cycles_success"} - successful cycles
#   - service_counter{name="cycles_failed"} - failed cycles
#   - service_counter{name="errors_{type}"} - errors by type
#
# Service-specific metrics (examples):
#   - service_gauge{service="validator", name="candidates"} - pending candidates
#   - service_counter{service="validator", name="total_promoted"} - promoted relays
# =============================================================================

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


# =============================================================================
# HTTP Server
# =============================================================================


class MetricsServer:
    """
    Async HTTP server for Prometheus metrics endpoint.

    Uses aiohttp for async compatibility with the rest of the codebase.
    The metrics endpoint path is configurable via MetricsConfig.path
    (defaults to "/metrics").

    Endpoints:
        {config.path} - Prometheus scraping endpoint (default: /metrics)

    Example:
        config = MetricsConfig(port=8001, path="/custom/metrics")
        server = MetricsServer(config)
        await server.start()
        # ... service runs ...
        await server.stop()
    """

    def __init__(self, config: MetricsConfig) -> None:
        self._config = config
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """
        Start the metrics HTTP server.

        Creates an aiohttp web application with the metrics endpoint and
        starts listening on the configured host and port. If metrics are
        disabled in the configuration, this method returns immediately
        without starting any server.

        The server runs in the background and serves Prometheus metrics
        at the configured path (default: /metrics).

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
        """
        Stop the metrics HTTP server and release resources.

        Gracefully shuts down the aiohttp runner and cleans up all
        associated resources. Safe to call multiple times or if the
        server was never started (no-op in those cases).
        """
        if self._runner:
            await self._runner.cleanup()

    @staticmethod
    async def _handle_metrics(_request: web.Request) -> web.Response:
        """Handle /metrics endpoint for Prometheus scraping."""
        output = generate_latest()
        return web.Response(
            body=output,
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )


async def start_metrics_server(
    config: MetricsConfig | None = None,
) -> MetricsServer:
    """
    Start metrics server with given or default configuration.

    Args:
        config: Metrics configuration. Uses defaults if not provided.

    Returns:
        Running MetricsServer instance. Call stop() on shutdown.
    """
    config = config or MetricsConfig()
    server = MetricsServer(config)
    await server.start()
    return server
