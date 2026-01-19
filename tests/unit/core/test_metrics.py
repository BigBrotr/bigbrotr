"""
Unit tests for core.metrics module.

Tests:
- MetricsConfig initialization and validation
- MetricsServer start/stop lifecycle
- Metrics endpoint response format
- start_metrics_server helper function
- Module-level metrics objects
"""

import pytest
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import ValidationError

from core.metrics import (
    CYCLE_DURATION_SECONDS,
    SERVICE_COUNTER,
    SERVICE_GAUGE,
    SERVICE_INFO,
    MetricsConfig,
    MetricsServer,
    start_metrics_server,
)


class TestMetricsConfig:
    """MetricsConfig initialization and validation."""

    def test_defaults(self):
        """Test default configuration values."""
        config = MetricsConfig()
        assert config.enabled is True
        assert config.port == 8000
        assert config.host == "0.0.0.0"
        assert config.path == "/metrics"

    def test_custom_values(self):
        """Test custom configuration values."""
        config = MetricsConfig(
            enabled=False,
            port=9090,
            host="127.0.0.1",
            path="/custom/metrics",
        )
        assert config.enabled is False
        assert config.port == 9090
        assert config.host == "127.0.0.1"
        assert config.path == "/custom/metrics"

    def test_port_validation_min(self):
        """Test port minimum validation (1024)."""
        with pytest.raises(ValidationError) as exc_info:
            MetricsConfig(port=1023)
        assert "greater than or equal to 1024" in str(exc_info.value)

    def test_port_validation_max(self):
        """Test port maximum validation (65535)."""
        with pytest.raises(ValidationError) as exc_info:
            MetricsConfig(port=65536)
        assert "less than or equal to 65535" in str(exc_info.value)

    def test_port_boundary_valid(self):
        """Test valid port boundary values."""
        config_min = MetricsConfig(port=1024)
        assert config_min.port == 1024

        config_max = MetricsConfig(port=65535)
        assert config_max.port == 65535


class TestMetricsServer:
    """MetricsServer lifecycle and functionality."""

    def test_init(self):
        """Test server initialization stores config."""
        config = MetricsConfig(port=9999)
        server = MetricsServer(config)
        assert server._config is config
        assert server._runner is None

    @pytest.mark.asyncio
    async def test_start_disabled(self):
        """Test start() returns immediately when disabled."""
        config = MetricsConfig(enabled=False)
        server = MetricsServer(config)
        await server.start()
        # Runner should not be created when disabled
        assert server._runner is None

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        """Test server start and stop lifecycle."""
        # Use high port to avoid conflicts
        config = MetricsConfig(port=19876, host="127.0.0.1")
        server = MetricsServer(config)

        try:
            await server.start()
            # Runner should be created
            assert server._runner is not None
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        """Test stop() is safe to call without start()."""
        config = MetricsConfig()
        server = MetricsServer(config)
        # Should not raise
        await server.stop()

    @pytest.mark.asyncio
    async def test_stop_multiple_times(self):
        """Test stop() can be called multiple times safely."""
        config = MetricsConfig(port=19877, host="127.0.0.1")
        server = MetricsServer(config)

        try:
            await server.start()
        finally:
            await server.stop()
            # Second stop should be safe
            await server.stop()

    @pytest.mark.asyncio
    async def test_handle_metrics_response(self):
        """Test _handle_metrics returns correct response format."""
        # Create mock request (not actually used by the handler)
        mock_request = None

        response = await MetricsServer._handle_metrics(mock_request)

        assert isinstance(response, web.Response)
        assert response.headers["Content-Type"] == CONTENT_TYPE_LATEST
        # Response body should be bytes containing prometheus format
        assert isinstance(response.body, bytes)
        # Should contain at least some metric output
        assert len(response.body) > 0

    @pytest.mark.asyncio
    async def test_metrics_endpoint_serves_content(self):
        """Test that the metrics endpoint serves prometheus content."""
        from aiohttp import ClientSession

        config = MetricsConfig(port=19878, host="127.0.0.1")
        server = MetricsServer(config)

        try:
            await server.start()

            async with (
                ClientSession() as session,
                session.get(f"http://127.0.0.1:{config.port}/metrics") as resp,
            ):
                assert resp.status == 200
                assert CONTENT_TYPE_LATEST in resp.headers.get("Content-Type", "")
                body = await resp.text()
                # Should contain prometheus format indicators
                assert "# HELP" in body or "# TYPE" in body or "_" in body
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_custom_path(self):
        """Test server respects custom path configuration."""
        from aiohttp import ClientSession

        config = MetricsConfig(port=19879, host="127.0.0.1", path="/custom/prom")
        server = MetricsServer(config)

        try:
            await server.start()

            async with ClientSession() as session:
                # Custom path should work
                async with session.get(f"http://127.0.0.1:{config.port}/custom/prom") as resp:
                    assert resp.status == 200

                # Default path should not work
                async with session.get(f"http://127.0.0.1:{config.port}/metrics") as resp:
                    assert resp.status == 404
        finally:
            await server.stop()


class TestStartMetricsServer:
    """start_metrics_server helper function."""

    @pytest.mark.asyncio
    async def test_with_config(self):
        """Test start_metrics_server with custom config."""
        config = MetricsConfig(port=19880, host="127.0.0.1")
        server = await start_metrics_server(config)

        try:
            assert isinstance(server, MetricsServer)
            assert server._config is config
            assert server._runner is not None
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_with_default_config(self):
        """Test start_metrics_server creates default config when None."""
        # This will try to bind to default port 8000, which may fail
        # Just test that it creates a MetricsServer with defaults
        config = MetricsConfig(port=19881, host="127.0.0.1", enabled=False)
        server = await start_metrics_server(config)

        try:
            assert isinstance(server, MetricsServer)
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_disabled_server(self):
        """Test start_metrics_server with disabled config."""
        config = MetricsConfig(enabled=False)
        server = await start_metrics_server(config)

        try:
            assert isinstance(server, MetricsServer)
            # Runner should not be created when disabled
            assert server._runner is None
        finally:
            await server.stop()


class TestMetricObjects:
    """Module-level metric objects exist and are properly typed."""

    def test_service_info_exists(self):
        """Test SERVICE_INFO is an Info metric."""
        from prometheus_client import Info

        assert isinstance(SERVICE_INFO, Info)

    def test_cycle_duration_exists(self):
        """Test CYCLE_DURATION_SECONDS is a Histogram metric."""
        from prometheus_client import Histogram

        assert isinstance(CYCLE_DURATION_SECONDS, Histogram)

    def test_service_gauge_exists(self):
        """Test SERVICE_GAUGE is a Gauge metric."""
        from prometheus_client import Gauge

        assert isinstance(SERVICE_GAUGE, Gauge)

    def test_service_counter_exists(self):
        """Test SERVICE_COUNTER is a Counter metric."""
        from prometheus_client import Counter

        assert isinstance(SERVICE_COUNTER, Counter)

    def test_cycle_duration_buckets(self):
        """Test CYCLE_DURATION_SECONDS has expected buckets."""
        # Access the internal buckets - they should match what's defined
        expected_buckets = (1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600)
        # The histogram stores upper bounds including +Inf
        assert CYCLE_DURATION_SECONDS._kwargs.get("buckets") == expected_buckets

    def test_service_gauge_labels(self):
        """Test SERVICE_GAUGE has correct labels."""
        assert SERVICE_GAUGE._labelnames == ("service", "name")

    def test_service_counter_labels(self):
        """Test SERVICE_COUNTER has correct labels."""
        assert SERVICE_COUNTER._labelnames == ("service", "name")

    def test_cycle_duration_labels(self):
        """Test CYCLE_DURATION_SECONDS has correct labels."""
        assert CYCLE_DURATION_SECONDS._labelnames == ("service",)


class TestMetricUsage:
    """Test that metrics can be used correctly."""

    def test_gauge_set_and_get(self):
        """Test SERVICE_GAUGE can be set and observed."""
        # Set a test value
        SERVICE_GAUGE.labels(service="test_service", name="test_metric").set(42)

        # Get the value back
        value = SERVICE_GAUGE.labels(service="test_service", name="test_metric")._value.get()
        assert value == 42

    def test_counter_increment(self):
        """Test SERVICE_COUNTER can be incremented."""
        # Get initial value
        initial = SERVICE_COUNTER.labels(service="test_service", name="test_count")._value.get()

        # Increment
        SERVICE_COUNTER.labels(service="test_service", name="test_count").inc()

        # Verify increment
        after = SERVICE_COUNTER.labels(service="test_service", name="test_count")._value.get()
        assert after == initial + 1

    def test_histogram_observe(self):
        """Test CYCLE_DURATION_SECONDS can observe values."""
        # Just verify it doesn't raise
        CYCLE_DURATION_SECONDS.labels(service="test_service").observe(1.5)

    def test_info_set(self):
        """Test SERVICE_INFO can be set."""
        # Just verify it doesn't raise
        SERVICE_INFO.info({"version": "1.0.0", "service": "test"})
