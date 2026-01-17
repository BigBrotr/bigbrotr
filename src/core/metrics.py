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

import time

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


class HealthConfig(BaseModel):
    """
    Health check configuration for readiness probes.

    Attributes:
        max_cycle_age_seconds: Maximum seconds since last successful cycle before unhealthy
    """

    max_cycle_age_seconds: float = Field(
        default=3600.0,
        ge=60.0,
        description="Maximum seconds since last cycle before unhealthy",
    )


class MetricsConfig(BaseModel):
    """
    Prometheus metrics configuration.

    Attributes:
        enabled: Enable metrics collection and HTTP server
        port: HTTP port for /metrics endpoint
        host: HTTP bind address (0.0.0.0 for container environments)
        path: URL path for metrics endpoint
        health: Health check configuration for readiness probes
    """

    enabled: bool = Field(default=True, description="Enable metrics collection")
    port: int = Field(default=8000, ge=1024, le=65535, description="Metrics HTTP port")
    host: str = Field(default="0.0.0.0", description="Metrics HTTP bind address")
    path: str = Field(default="/metrics", description="Metrics endpoint path")
    health: HealthConfig = Field(
        default_factory=HealthConfig,
        description="Health check configuration",
    )


# =============================================================================
# Common Service Metrics
# =============================================================================
#
# These metrics are automatically updated by BaseService.run_forever().
# All use 'service' label to distinguish between services in Grafana.
# =============================================================================

# Service information (static labels set once at startup)
SERVICE_INFO = Info(
    "service",
    "Service information and metadata",
)

# Cycle metrics - track run() invocations
CYCLES_TOTAL = Counter(
    "cycles_total",
    "Total service cycles executed",
    ["service", "status"],  # status: success, failed
)

CYCLE_DURATION_SECONDS = Histogram(
    "cycle_duration_seconds",
    "Duration of service cycle in seconds",
    ["service"],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600),
)

# Item processing metrics - track units of work
ITEMS_PROCESSED_TOTAL = Counter(
    "items_processed_total",
    "Total items processed by service",
    ["service", "result"],  # result: success, failed, skipped
)

# Error tracking with categorization
ERRORS_TOTAL = Counter(
    "errors_total",
    "Total errors encountered",
    ["service", "error_type"],  # error_type: TimeoutError, ConnectionError, etc.
)

# Runtime state gauges
CONSECUTIVE_FAILURES = Gauge(
    "consecutive_failures",
    "Current consecutive failure count",
    ["service"],
)

LAST_CYCLE_TIMESTAMP = Gauge(
    "last_cycle_timestamp_seconds",
    "Unix timestamp of last completed cycle",
    ["service"],
)


# =============================================================================
# HTTP Server
# =============================================================================


class MetricsServer:
    """
    Async HTTP server for Prometheus metrics endpoint.

    Uses aiohttp for async compatibility with the rest of the codebase.

    Endpoints:
        /metrics - Prometheus scraping endpoint
        /health  - Liveness probe (always returns 200 if server is running)
        /ready   - Readiness probe (checks service health via Prometheus metrics)

    Example:
        config = MetricsConfig(port=8001)
        server = MetricsServer(config, service_name="validator")
        await server.start()
        # ... service runs ...
        await server.stop()
    """

    def __init__(self, config: MetricsConfig, service_name: str = "unknown") -> None:
        self._config = config
        self._service_name = service_name
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Start the metrics HTTP server."""
        if not self._config.enabled:
            return

        app = web.Application()
        app.router.add_get(self._config.path, self._handle_metrics)
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/ready", self._handle_ready)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()

        site = web.TCPSite(
            self._runner,
            self._config.host,
            self._config.port,
        )
        await site.start()

    async def stop(self) -> None:
        """Stop the metrics HTTP server."""
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

    @staticmethod
    async def _handle_health(_request: web.Request) -> web.Response:
        """
        Handle /health endpoint for container liveness probes.

        Always returns 200 if the HTTP server is running.
        This indicates the process is alive and can accept requests.
        """
        return web.json_response({"status": "ok"})

    async def _handle_ready(self, _request: web.Request) -> web.Response:
        """
        Handle /ready endpoint for container readiness probes.

        Checks service health using Prometheus metrics:
        - Last successful cycle not too old

        Returns 200 if healthy, 503 if unhealthy.
        """
        current_time = time.time()
        health_config = self._config.health
        checks: dict[str, dict[str, object]] = {}
        healthy = True

        # Check last cycle age
        try:
            last_cycle = self._get_gauge_value(LAST_CYCLE_TIMESTAMP, self._service_name)
            if last_cycle > 0:
                age = current_time - last_cycle
                age_ok = age < health_config.max_cycle_age_seconds
                checks["last_cycle"] = {
                    "ok": age_ok,
                    "age_seconds": round(age, 1),
                    "threshold": health_config.max_cycle_age_seconds,
                }
                if not age_ok:
                    healthy = False
            else:
                # No cycle has run yet - this is OK during startup
                checks["last_cycle"] = {
                    "ok": True,
                    "age_seconds": None,
                    "threshold": health_config.max_cycle_age_seconds,
                }
        except Exception:
            # If we can't read the metric, assume OK (service may not have started yet)
            checks["last_cycle"] = {
                "ok": True,
                "age_seconds": None,
                "threshold": health_config.max_cycle_age_seconds,
            }

        response = {
            "status": "ok" if healthy else "unhealthy",
            "service": self._service_name,
            "checks": checks,
        }

        if healthy:
            return web.json_response(response)
        return web.json_response(response, status=503)

    @staticmethod
    def _get_gauge_value(gauge: Gauge, service_name: str) -> float:
        """
        Get the current value of a labeled gauge.

        Args:
            gauge: The Prometheus Gauge to read from
            service_name: The service label value

        Returns:
            The current gauge value, or 0.0 if not found
        """
        # Access the internal metric samples
        for metric in gauge.collect():
            for sample in metric.samples:
                if sample.labels.get("service") == service_name:
                    return sample.value
        return 0.0


async def start_metrics_server(
    config: MetricsConfig | None = None,
    service_name: str = "unknown",
) -> MetricsServer:
    """
    Start metrics server with given or default configuration.

    Args:
        config: Metrics configuration. Uses defaults if not provided.
        service_name: Service name for health check metric lookups.

    Returns:
        Running MetricsServer instance. Call stop() on shutdown.
    """
    config = config or MetricsConfig()
    server = MetricsServer(config, service_name=service_name)
    await server.start()
    return server
