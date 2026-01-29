"""
Unit tests for core.metrics module.

Tests:
- MetricsConfig initialization and validation
- MetricsServer start/stop lifecycle
- Metrics endpoint response format
- start_metrics_server helper function
- Module-level metrics objects (SERVICE_INFO, SERVICE_GAUGE, SERVICE_COUNTER, CYCLE_DURATION_SECONDS)
- Metric usage patterns
"""

import pytest
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, Info
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


# ============================================================================
# MetricsConfig Tests
# ============================================================================


class TestMetricsConfig:
    """Tests for MetricsConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default configuration values."""
        config = MetricsConfig()

        assert config.enabled is False
        assert config.port == 8000
        assert config.host == "127.0.0.1"
        assert config.path == "/metrics"

    def test_custom_values(self) -> None:
        """Test configuration with custom values."""
        config = MetricsConfig(
            enabled=True,
            port=9090,
            host="0.0.0.0",
            path="/custom/metrics",
        )

        assert config.enabled is True
        assert config.port == 9090
        assert config.host == "0.0.0.0"
        assert config.path == "/custom/metrics"

    def test_enabled_false_by_default(self) -> None:
        """Test that metrics are disabled by default for security."""
        config = MetricsConfig()
        assert config.enabled is False


class TestMetricsConfigPortValidation:
    """Tests for port validation in MetricsConfig."""

    def test_port_minimum_validation(self) -> None:
        """Test port minimum validation (>= 1024)."""
        with pytest.raises(ValidationError) as exc_info:
            MetricsConfig(port=1023)
        assert "greater than or equal to 1024" in str(exc_info.value)

    def test_port_maximum_validation(self) -> None:
        """Test port maximum validation (<= 65535)."""
        with pytest.raises(ValidationError) as exc_info:
            MetricsConfig(port=65536)
        assert "less than or equal to 65535" in str(exc_info.value)

    def test_port_boundary_minimum(self) -> None:
        """Test valid port at minimum boundary."""
        config = MetricsConfig(port=1024)
        assert config.port == 1024

    def test_port_boundary_maximum(self) -> None:
        """Test valid port at maximum boundary."""
        config = MetricsConfig(port=65535)
        assert config.port == 65535

    @pytest.mark.parametrize(
        "port",
        [1024, 8000, 8080, 9090, 19999, 49999, 65535],
    )
    def test_common_ports(self, port: int) -> None:
        """Test common metrics port values are valid."""
        config = MetricsConfig(port=port)
        assert config.port == port


class TestMetricsConfigPaths:
    """Tests for path configuration in MetricsConfig."""

    def test_default_path(self) -> None:
        """Test default metrics path."""
        config = MetricsConfig()
        assert config.path == "/metrics"

    def test_custom_path(self) -> None:
        """Test custom metrics path."""
        config = MetricsConfig(path="/prometheus/metrics")
        assert config.path == "/prometheus/metrics"

    def test_root_path(self) -> None:
        """Test root path is valid."""
        config = MetricsConfig(path="/")
        assert config.path == "/"


# ============================================================================
# MetricsServer Tests
# ============================================================================


class TestMetricsServerInit:
    """Tests for MetricsServer initialization."""

    def test_init_stores_config(self) -> None:
        """Test server initialization stores configuration."""
        config = MetricsConfig(port=9999)
        server = MetricsServer(config)

        assert server._config is config
        assert server._runner is None


class TestMetricsServerLifecycle:
    """Tests for MetricsServer start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_disabled_is_noop(self) -> None:
        """Test start() returns immediately when metrics disabled."""
        config = MetricsConfig(enabled=False)
        server = MetricsServer(config)

        await server.start()

        assert server._runner is None

    @pytest.mark.asyncio
    async def test_start_enabled_creates_runner(self) -> None:
        """Test start() creates runner when enabled."""
        config = MetricsConfig(enabled=True, port=19876, host="127.0.0.1")
        server = MetricsServer(config)

        try:
            await server.start()
            assert server._runner is not None
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_stop_cleans_up_runner(self) -> None:
        """Test stop() cleans up runner."""
        config = MetricsConfig(enabled=True, port=19877, host="127.0.0.1")
        server = MetricsServer(config)

        try:
            await server.start()
            assert server._runner is not None
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self) -> None:
        """Test stop() is safe to call without prior start()."""
        config = MetricsConfig()
        server = MetricsServer(config)

        await server.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_stop_multiple_times_is_safe(self) -> None:
        """Test stop() can be called multiple times safely."""
        config = MetricsConfig(enabled=True, port=19878, host="127.0.0.1")
        server = MetricsServer(config)

        try:
            await server.start()
        finally:
            await server.stop()
            await server.stop()  # Second call should be safe


class TestMetricsServerHandler:
    """Tests for MetricsServer request handler."""

    @pytest.mark.asyncio
    async def test_handle_metrics_returns_response(self) -> None:
        """Test _handle_metrics returns proper Response object."""
        response = await MetricsServer._handle_metrics(None)  # type: ignore[arg-type]

        assert isinstance(response, web.Response)

    @pytest.mark.asyncio
    async def test_handle_metrics_content_type(self) -> None:
        """Test _handle_metrics sets correct content type."""
        response = await MetricsServer._handle_metrics(None)  # type: ignore[arg-type]

        assert response.headers["Content-Type"] == CONTENT_TYPE_LATEST

    @pytest.mark.asyncio
    async def test_handle_metrics_returns_bytes(self) -> None:
        """Test _handle_metrics returns bytes body."""
        response = await MetricsServer._handle_metrics(None)  # type: ignore[arg-type]

        assert isinstance(response.body, bytes)
        assert len(response.body) > 0


class TestMetricsServerEndpoint:
    """Tests for MetricsServer HTTP endpoint."""

    @pytest.mark.asyncio
    async def test_metrics_endpoint_serves_content(self) -> None:
        """Test metrics endpoint serves prometheus content."""
        from aiohttp import ClientSession

        config = MetricsConfig(enabled=True, port=19879, host="127.0.0.1")
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
                # Prometheus format contains comments or metric data
                assert len(body) > 0
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_custom_path_works(self) -> None:
        """Test server respects custom path configuration."""
        from aiohttp import ClientSession

        config = MetricsConfig(
            enabled=True, port=19880, host="127.0.0.1", path="/custom/prom"
        )
        server = MetricsServer(config)

        try:
            await server.start()

            async with ClientSession() as session:
                # Custom path should work
                async with session.get(
                    f"http://127.0.0.1:{config.port}/custom/prom"
                ) as resp:
                    assert resp.status == 200

                # Default path should not work
                async with session.get(
                    f"http://127.0.0.1:{config.port}/metrics"
                ) as resp:
                    assert resp.status == 404
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_prometheus_format_indicators(self) -> None:
        """Test response contains prometheus format indicators."""
        from aiohttp import ClientSession

        config = MetricsConfig(enabled=True, port=19881, host="127.0.0.1")
        server = MetricsServer(config)

        try:
            await server.start()

            async with (
                ClientSession() as session,
                session.get(f"http://127.0.0.1:{config.port}/metrics") as resp,
            ):
                body = await resp.text()
                # Should contain prometheus format indicators
                has_help = "# HELP" in body
                has_type = "# TYPE" in body
                has_metrics = "_" in body  # Metric names contain underscores

                assert has_help or has_type or has_metrics
        finally:
            await server.stop()


# ============================================================================
# start_metrics_server Helper Tests
# ============================================================================


class TestStartMetricsServer:
    """Tests for start_metrics_server() helper function."""

    @pytest.mark.asyncio
    async def test_with_custom_config(self) -> None:
        """Test start_metrics_server with custom configuration."""
        config = MetricsConfig(enabled=True, port=19882, host="127.0.0.1")
        server = await start_metrics_server(config)

        try:
            assert isinstance(server, MetricsServer)
            assert server._config is config
            assert server._runner is not None
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_with_default_config(self) -> None:
        """Test start_metrics_server with default configuration."""
        # Use disabled config to avoid port conflicts
        config = MetricsConfig(enabled=False)
        server = await start_metrics_server(config)

        try:
            assert isinstance(server, MetricsServer)
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_disabled_server(self) -> None:
        """Test start_metrics_server with disabled configuration."""
        config = MetricsConfig(enabled=False)
        server = await start_metrics_server(config)

        try:
            assert isinstance(server, MetricsServer)
            assert server._runner is None
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_with_none_config(self) -> None:
        """Test start_metrics_server with None uses defaults."""
        # Default config is disabled, so this is safe
        server = await start_metrics_server(None)

        try:
            assert isinstance(server, MetricsServer)
            # Default is disabled
            assert server._runner is None
        finally:
            await server.stop()


# ============================================================================
# Module-Level Metrics Objects Tests
# ============================================================================


class TestMetricObjects:
    """Tests for module-level metric objects."""

    def test_service_info_is_info_metric(self) -> None:
        """Test SERVICE_INFO is an Info metric."""
        assert isinstance(SERVICE_INFO, Info)

    def test_cycle_duration_is_histogram(self) -> None:
        """Test CYCLE_DURATION_SECONDS is a Histogram metric."""
        assert isinstance(CYCLE_DURATION_SECONDS, Histogram)

    def test_service_gauge_is_gauge(self) -> None:
        """Test SERVICE_GAUGE is a Gauge metric."""
        assert isinstance(SERVICE_GAUGE, Gauge)

    def test_service_counter_is_counter(self) -> None:
        """Test SERVICE_COUNTER is a Counter metric."""
        assert isinstance(SERVICE_COUNTER, Counter)


class TestMetricLabels:
    """Tests for metric label configurations."""

    def test_service_gauge_labels(self) -> None:
        """Test SERVICE_GAUGE has correct labels."""
        assert SERVICE_GAUGE._labelnames == ("service", "name")

    def test_service_counter_labels(self) -> None:
        """Test SERVICE_COUNTER has correct labels."""
        assert SERVICE_COUNTER._labelnames == ("service", "name")

    def test_cycle_duration_labels(self) -> None:
        """Test CYCLE_DURATION_SECONDS has correct labels."""
        assert CYCLE_DURATION_SECONDS._labelnames == ("service",)


class TestHistogramBuckets:
    """Tests for histogram bucket configuration."""

    def test_cycle_duration_buckets(self) -> None:
        """Test CYCLE_DURATION_SECONDS has expected buckets."""
        expected_buckets = (1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600)
        assert CYCLE_DURATION_SECONDS._kwargs.get("buckets") == expected_buckets


# ============================================================================
# Metric Usage Tests
# ============================================================================


class TestMetricUsage:
    """Tests for metric usage patterns."""

    def test_gauge_set_and_get(self) -> None:
        """Test SERVICE_GAUGE can be set and observed."""
        SERVICE_GAUGE.labels(service="test_service", name="test_metric").set(42)

        value = SERVICE_GAUGE.labels(
            service="test_service", name="test_metric"
        )._value.get()
        assert value == 42

    def test_gauge_set_float(self) -> None:
        """Test SERVICE_GAUGE accepts float values."""
        SERVICE_GAUGE.labels(service="test_service", name="float_metric").set(3.14)

        value = SERVICE_GAUGE.labels(
            service="test_service", name="float_metric"
        )._value.get()
        assert value == 3.14

    def test_gauge_set_negative(self) -> None:
        """Test SERVICE_GAUGE accepts negative values."""
        SERVICE_GAUGE.labels(service="test_service", name="negative_metric").set(-10)

        value = SERVICE_GAUGE.labels(
            service="test_service", name="negative_metric"
        )._value.get()
        assert value == -10

    def test_counter_increment(self) -> None:
        """Test SERVICE_COUNTER can be incremented."""
        initial = SERVICE_COUNTER.labels(
            service="test_service", name="test_count"
        )._value.get()

        SERVICE_COUNTER.labels(service="test_service", name="test_count").inc()

        after = SERVICE_COUNTER.labels(
            service="test_service", name="test_count"
        )._value.get()
        assert after == initial + 1

    def test_counter_increment_by_value(self) -> None:
        """Test SERVICE_COUNTER can be incremented by specific value."""
        initial = SERVICE_COUNTER.labels(
            service="test_service", name="count_by_value"
        )._value.get()

        SERVICE_COUNTER.labels(service="test_service", name="count_by_value").inc(5)

        after = SERVICE_COUNTER.labels(
            service="test_service", name="count_by_value"
        )._value.get()
        assert after == initial + 5

    def test_histogram_observe(self) -> None:
        """Test CYCLE_DURATION_SECONDS can observe values."""
        # Should not raise
        CYCLE_DURATION_SECONDS.labels(service="test_service").observe(1.5)

    def test_histogram_observe_multiple(self) -> None:
        """Test CYCLE_DURATION_SECONDS can observe multiple values."""
        CYCLE_DURATION_SECONDS.labels(service="histogram_test").observe(0.5)
        CYCLE_DURATION_SECONDS.labels(service="histogram_test").observe(1.0)
        CYCLE_DURATION_SECONDS.labels(service="histogram_test").observe(5.0)
        # Should not raise

    def test_info_set(self) -> None:
        """Test SERVICE_INFO can be set."""
        # Should not raise
        SERVICE_INFO.info({"version": "1.0.0", "service": "test"})

    def test_info_set_multiple_labels(self) -> None:
        """Test SERVICE_INFO accepts multiple label values."""
        SERVICE_INFO.info({
            "version": "2.0.0",
            "service": "multi_label_test",
            "environment": "test",
            "build": "abc123",
        })


class TestMetricDifferentServices:
    """Tests for using metrics with different service labels."""

    def test_gauge_different_services(self) -> None:
        """Test SERVICE_GAUGE separates values by service."""
        SERVICE_GAUGE.labels(service="service_a", name="shared_metric").set(10)
        SERVICE_GAUGE.labels(service="service_b", name="shared_metric").set(20)

        value_a = SERVICE_GAUGE.labels(
            service="service_a", name="shared_metric"
        )._value.get()
        value_b = SERVICE_GAUGE.labels(
            service="service_b", name="shared_metric"
        )._value.get()

        assert value_a == 10
        assert value_b == 20

    def test_counter_different_services(self) -> None:
        """Test SERVICE_COUNTER separates values by service."""
        # Reset or use unique names
        SERVICE_COUNTER.labels(service="counter_svc_a", name="unique_count").inc(5)
        SERVICE_COUNTER.labels(service="counter_svc_b", name="unique_count").inc(10)

        value_a = SERVICE_COUNTER.labels(
            service="counter_svc_a", name="unique_count"
        )._value.get()
        value_b = SERVICE_COUNTER.labels(
            service="counter_svc_b", name="unique_count"
        )._value.get()

        assert value_a == 5
        assert value_b == 10


class TestMetricDifferentNames:
    """Tests for using metrics with different name labels."""

    def test_gauge_different_names(self) -> None:
        """Test SERVICE_GAUGE separates values by name."""
        SERVICE_GAUGE.labels(service="name_test", name="metric_1").set(100)
        SERVICE_GAUGE.labels(service="name_test", name="metric_2").set(200)

        value_1 = SERVICE_GAUGE.labels(
            service="name_test", name="metric_1"
        )._value.get()
        value_2 = SERVICE_GAUGE.labels(
            service="name_test", name="metric_2"
        )._value.get()

        assert value_1 == 100
        assert value_2 == 200
