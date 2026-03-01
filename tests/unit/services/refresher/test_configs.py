"""Unit tests for services.refresher.configs module.

Tests:
- RefreshConfig defaults, custom views, validation
- RefresherConfig defaults, nested config, base config inheritance
"""

from __future__ import annotations

import pytest

from bigbrotr.services.refresher import RefreshConfig, RefresherConfig
from bigbrotr.services.refresher.configs import DEFAULT_VIEWS


class TestRefreshConfig:
    """Tests for RefreshConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default refresh configuration contains all views."""
        config = RefreshConfig()

        assert config.views == DEFAULT_VIEWS
        assert len(config.views) == 11

    def test_default_views_dependency_order(self) -> None:
        """Test default views respect dependency ordering."""
        config = RefreshConfig()
        views = config.views

        rml_idx = views.index("relay_metadata_latest")
        rsc_idx = views.index("relay_software_counts")
        snc_idx = views.index("supported_nip_counts")

        assert rml_idx < rsc_idx
        assert rml_idx < snc_idx

    def test_custom_views(self) -> None:
        """Test custom view list."""
        config = RefreshConfig(views=["relay_metadata_latest", "event_stats"])

        assert config.views == ["relay_metadata_latest", "event_stats"]
        assert len(config.views) == 2

    def test_empty_views_rejected(self) -> None:
        """Test empty views list raises validation error."""
        with pytest.raises(ValueError, match="views list must not be empty"):
            RefreshConfig(views=[])

    def test_valid_view_names_accepted(self) -> None:
        """Test valid SQL identifier view names pass validation."""
        config = RefreshConfig(views=["relay_stats", "event_daily_counts"])
        assert config.views == ["relay_stats", "event_daily_counts"]

    def test_invalid_view_names_rejected(self) -> None:
        """Test invalid view names raise validation error."""
        with pytest.raises(ValueError, match="invalid view names"):
            RefreshConfig(views=["relay-stats", "INVALID", "DROP TABLE"])

    def test_default_views_is_independent_copy(self) -> None:
        """Test each config gets an independent copy of DEFAULT_VIEWS."""
        config1 = RefreshConfig()
        config2 = RefreshConfig()

        assert config1.views is not config2.views
        assert config1.views == config2.views


class TestRefresherConfig:
    """Tests for RefresherConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration inherits from BaseServiceConfig."""
        config = RefresherConfig()

        assert config.refresh.views == DEFAULT_VIEWS
        assert config.interval == 3600.0
        assert config.max_consecutive_failures == 5

    def test_custom_nested_config(self) -> None:
        """Test custom nested configuration."""
        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats"]),
        )

        assert config.refresh.views == ["event_stats"]

    def test_interval_from_base_config(self) -> None:
        """Test interval can be customized."""
        config = RefresherConfig(interval=3600.0)
        assert config.interval == 3600.0

    def test_max_consecutive_failures_from_base_config(self) -> None:
        """Test max_consecutive_failures can be customized."""
        config = RefresherConfig(max_consecutive_failures=10)
        assert config.max_consecutive_failures == 10

    def test_metrics_config_from_base(self) -> None:
        """Test metrics config is inherited from base."""
        config = RefresherConfig()
        assert hasattr(config, "metrics")
        assert config.metrics.enabled is False

    def test_from_dict_nested(self) -> None:
        """Test creating config from dictionary."""
        data = {
            "refresh": {"views": ["event_stats", "relay_stats"]},
            "interval": 1800.0,
        }
        config = RefresherConfig(**data)
        assert config.refresh.views == ["event_stats", "relay_stats"]
        assert config.interval == 1800.0
