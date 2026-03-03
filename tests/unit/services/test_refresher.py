"""Unit tests for the refresher service package."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr, BrotrConfig
from bigbrotr.services.refresher import RefreshConfig, Refresher, RefresherConfig
from bigbrotr.services.refresher.configs import DEFAULT_VIEWS


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_refresher_brotr(mock_brotr: Brotr) -> Brotr:
    mock_brotr.refresh_materialized_view = AsyncMock()  # type: ignore[method-assign]

    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.timeouts = MagicMock()
    mock_config.timeouts.refresh = None
    mock_brotr._config = mock_config

    return mock_brotr


# ============================================================================
# Configs — RefreshConfig
# ============================================================================


class TestRefreshConfig:
    def test_default_values(self) -> None:
        config = RefreshConfig()

        assert config.views == DEFAULT_VIEWS
        assert len(config.views) == 11

    def test_default_views_dependency_order(self) -> None:
        config = RefreshConfig()
        views = config.views

        rml_idx = views.index("relay_metadata_latest")
        rsc_idx = views.index("relay_software_counts")
        snc_idx = views.index("supported_nip_counts")

        assert rml_idx < rsc_idx
        assert rml_idx < snc_idx

    def test_custom_views(self) -> None:
        config = RefreshConfig(views=["relay_metadata_latest", "event_stats"])

        assert config.views == ["relay_metadata_latest", "event_stats"]
        assert len(config.views) == 2

    def test_empty_views_rejected(self) -> None:
        with pytest.raises(ValueError, match="views list must not be empty"):
            RefreshConfig(views=[])

    def test_valid_view_names_accepted(self) -> None:
        config = RefreshConfig(views=["relay_stats", "event_daily_counts"])
        assert config.views == ["relay_stats", "event_daily_counts"]

    def test_invalid_view_names_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid view names"):
            RefreshConfig(views=["relay-stats", "INVALID", "DROP TABLE"])

    def test_default_views_is_independent_copy(self) -> None:
        config1 = RefreshConfig()
        config2 = RefreshConfig()

        assert config1.views is not config2.views
        assert config1.views == config2.views


# ============================================================================
# Configs — RefresherConfig
# ============================================================================


class TestRefresherConfig:
    def test_default_values(self) -> None:
        config = RefresherConfig()

        assert config.refresh.views == DEFAULT_VIEWS
        assert config.interval == 3600.0
        assert config.max_consecutive_failures == 5

    def test_custom_nested_config(self) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats"]),
        )

        assert config.refresh.views == ["event_stats"]

    def test_interval_from_base_config(self) -> None:
        config = RefresherConfig(interval=3600.0)
        assert config.interval == 3600.0

    def test_max_consecutive_failures_from_base_config(self) -> None:
        config = RefresherConfig(max_consecutive_failures=10)
        assert config.max_consecutive_failures == 10

    def test_metrics_config_from_base(self) -> None:
        config = RefresherConfig()
        assert hasattr(config, "metrics")
        assert config.metrics.enabled is False

    def test_from_dict_nested(self) -> None:
        data = {
            "refresh": {"views": ["event_stats", "relay_stats"]},
            "interval": 1800.0,
        }
        config = RefresherConfig(**data)
        assert config.refresh.views == ["event_stats", "relay_stats"]
        assert config.interval == 1800.0


# ============================================================================
# Service — RefresherInit
# ============================================================================


class TestRefresherInit:
    def test_init_with_defaults(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(brotr=mock_refresher_brotr)

        assert refresher._brotr is mock_refresher_brotr
        assert refresher.SERVICE_NAME == "refresher"
        assert refresher.config.refresh.views == DEFAULT_VIEWS

    def test_init_with_custom_config(self, mock_refresher_brotr: Brotr) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        assert refresher.config.refresh.views == ["event_stats"]

    def test_from_dict(self, mock_refresher_brotr: Brotr) -> None:
        data = {
            "refresh": {"views": ["relay_metadata_latest", "event_stats"]},
        }
        refresher = Refresher.from_dict(data, brotr=mock_refresher_brotr)

        assert refresher.config.refresh.views == ["relay_metadata_latest", "event_stats"]

    def test_service_name_class_attribute(self, mock_refresher_brotr: Brotr) -> None:
        assert Refresher.SERVICE_NAME == "refresher"
        refresher = Refresher(brotr=mock_refresher_brotr)
        assert refresher.SERVICE_NAME == "refresher"

    def test_config_class_attribute(self, mock_refresher_brotr: Brotr) -> None:
        assert RefresherConfig == Refresher.CONFIG_CLASS

    def test_logger_initialized(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(brotr=mock_refresher_brotr)
        assert refresher._logger is not None


# ============================================================================
# Service — RefresherRun
# ============================================================================


class TestRefresherRun:
    async def test_run_refreshes_all_views(self, mock_refresher_brotr: Brotr) -> None:
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
        refresher = Refresher(brotr=mock_refresher_brotr)

        await refresher.run()

        assert mock_refresher_brotr.refresh_materialized_view.call_count == 11

    async def test_run_logs_per_view(self, mock_refresher_brotr: Brotr) -> None:
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

    async def test_run_continues_on_failure(self, mock_refresher_brotr: Brotr) -> None:
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                None,
                asyncpg.PostgresError("view_error"),
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
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=asyncpg.PostgresError("refresh_timeout")
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
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=asyncpg.PostgresError("db_error")
        )

        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats", "relay_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher._logger, "info") as mock_log:
            await refresher.run()

            cycle_completed_calls = [
                call for call in mock_log.call_args_list if call[0][0] == "refresh_completed"
            ]
            assert len(cycle_completed_calls) == 1
            assert cycle_completed_calls[0][1]["refreshed"] == 0
            assert cycle_completed_calls[0][1]["failed"] == 2

    async def test_run_logs_refresh_completed(self, mock_refresher_brotr: Brotr) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher._logger, "info") as mock_log:
            await refresher.run()

            log_messages = [call[0][0] for call in mock_log.call_args_list]
            assert "refresh_completed" in log_messages

    async def test_run_refresh_completed_counts(self, mock_refresher_brotr: Brotr) -> None:
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=[None, asyncpg.PostgresError("error"), None]
        )

        config = RefresherConfig(
            refresh=RefreshConfig(views=["relay_metadata_latest", "event_stats", "relay_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher._logger, "info") as mock_log:
            await refresher.run()

            cycle_completed_calls = [
                call for call in mock_log.call_args_list if call[0][0] == "refresh_completed"
            ]
            assert cycle_completed_calls[0][1]["refreshed"] == 2
            assert cycle_completed_calls[0][1]["failed"] == 1


# ============================================================================
# Metrics
# ============================================================================


class TestRefresherMetrics:
    async def test_set_gauge_refreshed(self, mock_refresher_brotr: Brotr) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats", "relay_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher, "set_gauge") as mock_gauge:
            await refresher.run()

            gauge_calls = {call[0][0]: call[0][1] for call in mock_gauge.call_args_list}
            assert gauge_calls["views_refreshed"] == 2

    async def test_set_gauge_failed(self, mock_refresher_brotr: Brotr) -> None:
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=asyncpg.PostgresError("error")
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
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=[None, asyncpg.PostgresError("error"), None]
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

    async def test_inc_counter_refreshed(self, mock_refresher_brotr: Brotr) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats", "relay_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher, "inc_counter") as mock_counter:
            await refresher.run()

        mock_counter.assert_any_call("total_views_refreshed", 2)

    async def test_inc_counter_failed(self, mock_refresher_brotr: Brotr) -> None:
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=asyncpg.PostgresError("error")
        )

        config = RefresherConfig(
            refresh=RefreshConfig(views=["event_stats"]),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher, "inc_counter") as mock_counter:
            await refresher.run()

        mock_counter.assert_any_call("total_views_failed", 1)
