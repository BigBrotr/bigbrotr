"""
Unit tests for services.finder configuration models.

Tests:
- ConcurrencyConfig
- EventsConfig
- ApiSourceConfig
- ApiConfig
- FinderConfig
"""

import pytest

from bigbrotr.services.finder import (
    ApiConfig,
    ApiSourceConfig,
    ConcurrencyConfig,
    EventsConfig,
    FinderConfig,
)


# ============================================================================
# ConcurrencyConfig Tests
# ============================================================================


class TestConcurrencyConfig:
    """Tests for ConcurrencyConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default concurrency configuration."""
        config = ConcurrencyConfig()
        assert config.max_parallel_events == 10

    def test_custom_values(self) -> None:
        """Test custom concurrency configuration."""
        config = ConcurrencyConfig(max_parallel_events=20)
        assert config.max_parallel_events == 20

    def test_max_parallel_events_bounds(self) -> None:
        """Test max_parallel_events validation bounds."""
        config_min = ConcurrencyConfig(max_parallel_events=1)
        assert config_min.max_parallel_events == 1

        config_max = ConcurrencyConfig(max_parallel_events=50)
        assert config_max.max_parallel_events == 50

        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel_events=0)

        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel_events=51)


# ============================================================================
# EventsConfig Tests
# ============================================================================


class TestEventsConfig:
    """Tests for EventsConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default events configuration."""
        config = EventsConfig()
        assert config.enabled is True
        assert config.batch_size == 1000

    def test_disabled(self) -> None:
        """Test can disable events scanning."""
        config = EventsConfig(enabled=False)
        assert config.enabled is False

    def test_batch_size_bounds(self) -> None:
        """Test batch_size validation bounds."""
        # Min bound
        config_min = EventsConfig(batch_size=100)
        assert config_min.batch_size == 100

        # Max bound
        config_max = EventsConfig(batch_size=10000)
        assert config_max.batch_size == 10000

        # Below min
        with pytest.raises(ValueError):
            EventsConfig(batch_size=50)

        # Above max
        with pytest.raises(ValueError):
            EventsConfig(batch_size=20000)


# ============================================================================
# ApiSourceConfig Tests
# ============================================================================


class TestApiSourceConfig:
    """Tests for ApiSourceConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default API source configuration."""
        config = ApiSourceConfig(url="https://api.example.com")

        assert config.url == "https://api.example.com"
        assert config.enabled is True
        assert config.timeout == 30.0
        assert config.jmespath == "[*]"

    def test_custom_values(self) -> None:
        """Test custom API source configuration."""
        config = ApiSourceConfig(
            url="https://custom.api.com",
            enabled=False,
            timeout=60.0,
        )

        assert config.url == "https://custom.api.com"
        assert config.enabled is False
        assert config.timeout == 60.0

    def test_timeout_bounds(self) -> None:
        """Test timeout validation bounds."""
        # Min bound (connect_timeout must not exceed timeout)
        config_min = ApiSourceConfig(url="https://api.com", timeout=0.1, connect_timeout=0.1)
        assert config_min.timeout == 0.1

        # Max bound
        config_max = ApiSourceConfig(url="https://api.com", timeout=120.0)
        assert config_max.timeout == 120.0

    def test_custom_jmespath_expression(self) -> None:
        config = ApiSourceConfig(
            url="https://api.example.com",
            jmespath="data.relays[*].url",
        )
        assert config.jmespath == "data.relays[*].url"

    def test_invalid_jmespath_expression_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid JMESPath expression"):
            ApiSourceConfig(
                url="https://api.example.com",
                jmespath="[*",
            )

    def test_connect_timeout_exceeds_timeout_rejected(self) -> None:
        """Test that connect_timeout > timeout is rejected."""
        with pytest.raises(ValueError, match=r"connect_timeout.*must not exceed.*timeout"):
            ApiSourceConfig(url="https://api.com", timeout=10.0, connect_timeout=30.0)

    def test_connect_timeout_equals_timeout_accepted(self) -> None:
        """Test that connect_timeout == timeout is accepted."""
        config = ApiSourceConfig(url="https://api.com", timeout=10.0, connect_timeout=10.0)
        assert config.connect_timeout == 10.0


# ============================================================================
# ApiConfig Tests
# ============================================================================


class TestApiConfig:
    """Tests for ApiConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default API configuration."""
        config = ApiConfig()

        assert config.enabled is True
        assert len(config.sources) == 2
        assert config.delay_between_requests == 1.0
        assert config.verify_ssl is True

    def test_default_sources(self) -> None:
        """Test default API sources include nostr.watch."""
        config = ApiConfig()

        urls = [s.url for s in config.sources]
        assert "https://api.nostr.watch/v1/online" in urls
        assert "https://api.nostr.watch/v1/offline" in urls

    def test_custom_sources(self) -> None:
        """Test custom API sources."""
        config = ApiConfig(
            sources=[
                ApiSourceConfig(url="https://custom1.api.com"),
                ApiSourceConfig(url="https://custom2.api.com"),
            ]
        )

        assert len(config.sources) == 2
        assert config.sources[0].url == "https://custom1.api.com"

    def test_verify_ssl_disabled(self) -> None:
        """Test SSL verification can be disabled."""
        config = ApiConfig(verify_ssl=False)
        assert config.verify_ssl is False

    def test_max_response_size_default(self) -> None:
        """Test default max_response_size is 5 MB."""
        config = ApiConfig()
        assert config.max_response_size == 5_242_880

    def test_max_response_size_custom(self) -> None:
        """Test custom max_response_size."""
        config = ApiConfig(max_response_size=1_048_576)
        assert config.max_response_size == 1_048_576

    def test_max_response_size_bounds(self) -> None:
        """Test max_response_size validation bounds."""
        with pytest.raises(ValueError):
            ApiConfig(max_response_size=512)  # Below min (1024)

        with pytest.raises(ValueError):
            ApiConfig(max_response_size=100_000_000)  # Above max (50 MB)


# ============================================================================
# FinderConfig Tests
# ============================================================================


class TestFinderConfig:
    """Tests for FinderConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration (inherits from BaseServiceConfig)."""
        config = FinderConfig()

        assert config.interval == 300.0  # BaseServiceConfig default
        assert config.max_consecutive_failures == 5  # BaseServiceConfig default
        assert config.events.enabled is True
        assert config.api.enabled is True

    def test_custom_nested_config(self) -> None:
        """Test custom nested configuration."""
        config = FinderConfig(
            interval=7200.0,
            events=EventsConfig(enabled=False),
            api=ApiConfig(enabled=False),
        )

        assert config.interval == 7200.0
        assert config.events.enabled is False
        assert config.api.enabled is False

    def test_concurrency_config(self) -> None:
        """Test concurrency configuration."""
        config = FinderConfig(concurrency=ConcurrencyConfig(max_parallel_events=15))
        assert config.concurrency.max_parallel_events == 15
