"""
Unit tests for services.refresher module.

Tests:
- Configuration models (RefreshConfig, RefresherConfig)
- Refresher service initialization
- View refresh execution and ordering
- Error handling and resilience
- Prometheus metrics reporting
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.core.brotr import Brotr, BrotrConfig
from bigbrotr.services.refresher import (
    RefreshConfig,
    Refresher,
    RefresherConfig,
)
from bigbrotr.services.refresher.configs import DEFAULT_VIEWS


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_refresher_brotr(mock_brotr: Brotr) -> Brotr:
    """Create a Brotr mock configured for refresher tests."""
    mock_brotr.refresh_materialized_view = AsyncMock()  # type: ignore[method-assign]

    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.timeouts = MagicMock()
    mock_config.timeouts.refresh = None
    mock_brotr._config = mock_config

    return mock_brotr


# ============================================================================
# RefreshConfig Tests
# ============================================================================


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

    def test_default_views_is_independent_copy(self) -> None:
        """Test each config gets an independent copy of DEFAULT_VIEWS."""
        config1 = RefreshConfig()
        config2 = RefreshConfig()

        assert config1.views is not config2.views
        assert config1.views == config2.views


# ============================================================================
# RefresherConfig Tests
# ============================================================================


class TestRefresherConfig:
    """Tests for RefresherConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration inherits from BaseServiceConfig."""
        config = RefresherConfig()

        assert config.refresh.views == DEFAULT_VIEWS
        assert config.interval == 300.0
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


# ============================================================================
# Refresher Initialization Tests
# ============================================================================


class TestRefresherInit:
    """Tests for Refresher initialization."""

    def test_init_with_defaults(self, mock_refresher_brotr: Brotr) -> None:
        """Test initialization with default config."""
        refresher = Refresher(brotr=mock_refresher_brotr)

        assert refresher._brotr is mock_refresher_brotr
        assert refresher.SERVICE_NAME == "refresher"
        assert refresher.config.refresh.views == DEFAULT_VIEWS

    def test_init_with_custom_config(self, mock_refresher_brotr: Brotr) -> None:
        """Test initialization with custom config."""
        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        assert refresher.config.refresh.views == ["event_stats"]

    def test_from_dict(self, mock_refresher_brotr: Brotr) -> None:
        """Test factory method from_dict."""
        data = {
            "refresh": {"views": ["relay_metadata_latest", "event_stats"]},
        }
        refresher = Refresher.from_dict(data, brotr=mock_refresher_brotr)

        assert refresher.config.refresh.views == ["relay_metadata_latest", "event_stats"]

    def test_service_name_class_attribute(self, mock_refresher_brotr: Brotr) -> None:
        """Test SERVICE_NAME class attribute."""
        assert Refresher.SERVICE_NAME == "refresher"
        refresher = Refresher(brotr=mock_refresher_brotr)
        assert refresher.SERVICE_NAME == "refresher"

    def test_config_class_attribute(self, mock_refresher_brotr: Brotr) -> None:
        """Test CONFIG_CLASS class attribute."""
        assert RefresherConfig == Refresher.CONFIG_CLASS

    def test_logger_initialized(self, mock_refresher_brotr: Brotr) -> None:
        """Test logger is initialized."""
        refresher = Refresher(brotr=mock_refresher_brotr)
        assert refresher._logger is not None


# ============================================================================
# Run Tests
# ============================================================================


class TestRefresherRun:
    """Tests for Refresher.run() method."""

    async def test_run_refreshes_all_views(self, mock_refresher_brotr: Brotr) -> None:
        """Test run refreshes all configured views in order."""
        config = RefresherConfig(
            refresh=RefreshConfig(views=["relay_metadata_latest", "event_stats", "relay_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        await refresher.run()

        assert mock_refresher_brotr.refresh_materialized_view.call_count == 3
        calls = [
            call[0][0] for call in mock_refresher_brotr.refresh_materialized_view.call_args_list
        ]
        assert calls == ["relay_metadata_latest", "event_stats", "relay_stats"]

    async def test_run_refreshes_all_default_views(self, mock_refresher_brotr: Brotr) -> None:
        """Test run with default config refreshes all 11 views."""
        refresher = Refresher(brotr=mock_refresher_brotr)

        await refresher.run()

        assert mock_refresher_brotr.refresh_materialized_view.call_count == 11

    async def test_run_logs_per_view_duration(self, mock_refresher_brotr: Brotr) -> None:
        """Test run logs duration for each view."""
        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher._logger, "info") as mock_log:
            await refresher.run()

            view_refreshed_calls = [
                call for call in mock_log.call_args_list if call[0][0] == "view_refreshed"
            ]
            assert len(view_refreshed_calls) == 1
            assert view_refreshed_calls[0][1]["view"] == "event_stats"
            assert "duration" in view_refreshed_calls[0][1]

    async def test_run_continues_on_failure(self, mock_refresher_brotr: Brotr) -> None:
        """Test run continues refreshing after a view fails."""
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                None,
                Exception("view_error"),
                None,
            ]
        )

        config = RefresherConfig(
            refresh=RefreshConfig(views=["relay_metadata_latest", "event_stats", "relay_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        await refresher.run()

        assert mock_refresher_brotr.refresh_materialized_view.call_count == 3

    async def test_run_logs_failure(self, mock_refresher_brotr: Brotr) -> None:
        """Test run logs error when a view refresh fails."""
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=Exception("refresh_timeout")
        )

        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher._logger, "error") as mock_error:
            await refresher.run()

            mock_error.assert_called_once()
            assert mock_error.call_args[0][0] == "view_refresh_failed"
            assert mock_error.call_args[1]["view"] == "event_stats"
            assert "refresh_timeout" in mock_error.call_args[1]["error"]

    async def test_run_all_fail(self, mock_refresher_brotr: Brotr) -> None:
        """Test run completes even when all views fail."""
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=Exception("db_error")
        )

        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats", "relay_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher._logger, "info") as mock_log:
            await refresher.run()

            cycle_completed_calls = [
                call for call in mock_log.call_args_list if call[0][0] == "cycle_completed"
            ]
            assert len(cycle_completed_calls) == 1
            assert cycle_completed_calls[0][1]["refreshed"] == 0
            assert cycle_completed_calls[0][1]["failed"] == 2

    async def test_run_logs_cycle_started_and_completed(self, mock_refresher_brotr: Brotr) -> None:
        """Test run logs cycle start and completion."""
        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher._logger, "info") as mock_log:
            await refresher.run()

            log_messages = [call[0][0] for call in mock_log.call_args_list]
            assert "cycle_started" in log_messages
            assert "cycle_completed" in log_messages

    async def test_run_cycle_completed_counts(self, mock_refresher_brotr: Brotr) -> None:
        """Test cycle_completed log contains correct refreshed/failed counts."""
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=[None, Exception("error"), None]
        )

        config = RefresherConfig(
            refresh=RefreshConfig(views=["relay_metadata_latest", "event_stats", "relay_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher._logger, "info") as mock_log:
            await refresher.run()

            cycle_completed_calls = [
                call for call in mock_log.call_args_list if call[0][0] == "cycle_completed"
            ]
            assert cycle_completed_calls[0][1]["refreshed"] == 2
            assert cycle_completed_calls[0][1]["failed"] == 1


# ============================================================================
# Metrics Tests
# ============================================================================


class TestRefresherMetrics:
    """Tests for Refresher Prometheus metrics."""

    async def test_set_gauge_refreshed(self, mock_refresher_brotr: Brotr) -> None:
        """Test views_refreshed gauge is set after run."""
        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats", "relay_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher, "set_gauge") as mock_gauge:
            await refresher.run()

            gauge_calls = {call[0][0]: call[0][1] for call in mock_gauge.call_args_list}
            assert gauge_calls["views_refreshed"] == 2

    async def test_set_gauge_failed(self, mock_refresher_brotr: Brotr) -> None:
        """Test views_failed gauge is set after run with failures."""
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=Exception("error")
        )

        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher, "set_gauge") as mock_gauge:
            await refresher.run()

            gauge_calls = {call[0][0]: call[0][1] for call in mock_gauge.call_args_list}
            assert gauge_calls["views_failed"] == 1
            assert gauge_calls["views_refreshed"] == 0

    async def test_set_gauge_mixed(self, mock_refresher_brotr: Brotr) -> None:
        """Test gauges with mixed success and failure."""
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=[None, Exception("error"), None]
        )

        config = RefresherConfig(
            refresh=RefreshConfig(views=["relay_metadata_latest", "event_stats", "relay_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher, "set_gauge") as mock_gauge:
            await refresher.run()

            gauge_calls = {call[0][0]: call[0][1] for call in mock_gauge.call_args_list}
            assert gauge_calls["views_refreshed"] == 2
            assert gauge_calls["views_failed"] == 1
