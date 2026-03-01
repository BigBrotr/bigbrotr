"""Unit tests for services.api.configs module.

Tests:
- ApiConfig defaults and validation
"""

from __future__ import annotations

import pytest

from bigbrotr.services.api.configs import ApiConfig
from bigbrotr.services.common.configs import TableConfig


class TestApiConfig:
    """Tests for ApiConfig Pydantic model."""

    def test_default_values(self) -> None:
        config = ApiConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 8080
        assert config.max_page_size == 1000
        assert config.default_page_size == 100
        assert config.tables == {}
        assert config.cors_origins == []

    def test_custom_values(self) -> None:
        config = ApiConfig(
            host="127.0.0.1",
            port=9000,
            max_page_size=500,
            tables={"event": TableConfig(enabled=True)},
        )
        assert config.port == 9000
        assert config.max_page_size == 500
        assert config.tables["event"].enabled is True

    def test_inherits_base_service_config(self) -> None:
        config = ApiConfig(interval=120.0)
        assert config.interval == 120.0
        assert config.max_consecutive_failures == 5

    def test_request_timeout_default(self) -> None:
        config = ApiConfig()
        assert config.request_timeout == 30.0

    def test_request_timeout_custom(self) -> None:
        config = ApiConfig(request_timeout=60.0)
        assert config.request_timeout == 60.0

    def test_default_page_size_exceeds_max_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"default_page_size.*must not exceed.*max_page_size"):
            ApiConfig(default_page_size=500, max_page_size=100)

    def test_default_page_size_equals_max_accepted(self) -> None:
        config = ApiConfig(default_page_size=100, max_page_size=100)
        assert config.default_page_size == 100

    def test_empty_host_rejected(self) -> None:
        """Test that empty host string is rejected."""
        with pytest.raises(ValueError):
            ApiConfig(host="")
