"""Unit tests for services.dvm.configs module.

Tests:
- DvmConfig defaults and validation
"""

from __future__ import annotations

import pytest

from bigbrotr.services.common.configs import TableConfig
from bigbrotr.services.dvm.configs import DvmConfig


class TestDvmConfig:
    """Tests for DvmConfig Pydantic model."""

    def test_default_values(self) -> None:
        config = DvmConfig(relays=["wss://relay.example.com"])
        assert config.kind == 5050
        assert config.max_page_size == 1000
        assert config.announce is True
        assert config.tables == {}
        assert config.fetch_timeout == 30.0

    def test_custom_fetch_timeout(self) -> None:
        config = DvmConfig(relays=["wss://relay.example.com"], fetch_timeout=60.0)
        assert config.fetch_timeout == 60.0

    def test_requires_relays(self) -> None:
        with pytest.raises(ValueError):
            DvmConfig(relays=[])

    def test_kind_range(self) -> None:
        with pytest.raises(ValueError):
            DvmConfig(relays=["wss://x"], kind=4000)

    def test_custom_tables(self) -> None:
        config = DvmConfig(
            relays=["wss://relay.example.com"],
            tables={"relay": TableConfig(enabled=True, price=1000)},
        )
        assert config.tables["relay"].price == 1000
        assert config.tables["relay"].enabled is True

    def test_inherits_base_service_config(self) -> None:
        config = DvmConfig(relays=["wss://relay.example.com"], interval=120.0)
        assert config.interval == 120.0

    def test_invalid_relay_url_rejected(self) -> None:
        """Test that invalid relay URLs are rejected."""
        with pytest.raises(ValueError, match="Invalid relay URL"):
            DvmConfig(relays=["not_a_url"])

    def test_valid_relay_urls_accepted(self) -> None:
        """Test that valid WebSocket relay URLs are accepted."""
        config = DvmConfig(relays=["wss://relay.damus.io", "wss://nos.lol"])
        assert len(config.relays) == 2
