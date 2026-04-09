"""Unit tests for the refresher service package."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr, BrotrConfig
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.refresher import RefreshConfig, Refresher, RefresherConfig
from bigbrotr.services.refresher.configs import (
    DEFAULT_ANALYTICS_TABLES,
    DEFAULT_CURRENT_TABLES,
    resolve_analytics_table_order,
    resolve_current_table_order,
    validate_refresh_dependencies,
)


@pytest.fixture
def mock_refresher_brotr(mock_brotr: Brotr) -> Brotr:
    mock_brotr.get_service_state = AsyncMock(return_value=[])  # type: ignore[method-assign]
    mock_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]
    mock_brotr.delete_service_state = AsyncMock(return_value=0)  # type: ignore[method-assign]
    mock_brotr.fetchval = AsyncMock(return_value=0)  # type: ignore[method-assign]
    mock_brotr.execute = AsyncMock()  # type: ignore[method-assign]

    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.timeouts = MagicMock()
    mock_config.timeouts.refresh = None
    mock_brotr._config = mock_config

    return mock_brotr


class TestRefreshConfig:
    def test_default_values(self) -> None:
        config = RefreshConfig()

        assert config.current_tables == DEFAULT_CURRENT_TABLES
        assert config.analytics_tables == DEFAULT_ANALYTICS_TABLES

    def test_default_lists_are_independent_copies(self) -> None:
        config1 = RefreshConfig()
        config2 = RefreshConfig()

        assert config1.current_tables is not config2.current_tables
        assert config1.analytics_tables is not config2.analytics_tables

    def test_empty_lists_are_allowed(self) -> None:
        config = RefreshConfig(current_tables=[], analytics_tables=[])

        assert config.current_tables == []
        assert config.analytics_tables == []

    @pytest.mark.parametrize(
        "name",
        [
            "relay_stats",
            "daily_counts",
            "a",
            "_private_table",
            "table123",
        ],
    )
    def test_valid_names_are_accepted(self, name: str) -> None:
        config = RefreshConfig(current_tables=[name], analytics_tables=[name])

        assert config.current_tables == [name]
        assert config.analytics_tables == [name]

    @pytest.mark.parametrize(
        "name",
        [
            "relay-stats",
            "UPPERCASE",
            "DROP TABLE",
            "123starts_with_digit",
            "has.dot",
            "semi;colon",
        ],
    )
    def test_invalid_names_are_rejected(self, name: str) -> None:
        with pytest.raises(ValueError, match="invalid"):
            RefreshConfig(current_tables=[name])

        with pytest.raises(ValueError, match="invalid"):
            RefreshConfig(analytics_tables=[name])

    def test_current_table_order_resolution_is_canonical(self) -> None:
        ordered = resolve_current_table_order(
            [
                "contact_list_edges_current",
                "events_replaceable_current",
                "relay_metadata_current",
                "contact_lists_current",
            ]
        )

        assert ordered == [
            "relay_metadata_current",
            "events_replaceable_current",
            "contact_lists_current",
            "contact_list_edges_current",
        ]

    def test_analytics_table_order_resolution_is_canonical(self) -> None:
        ordered = resolve_analytics_table_order(
            [
                "relay_stats",
                "pubkey_relay_stats",
                "pubkey_stats",
                "daily_counts",
                "pubkey_kind_stats",
            ]
        )

        assert ordered == [
            "daily_counts",
            "pubkey_kind_stats",
            "pubkey_relay_stats",
            "pubkey_stats",
            "relay_stats",
        ]

    def test_dependency_validation_accepts_complete_selection(self) -> None:
        validate_refresh_dependencies(
            current_tables=["events_replaceable_current", "contact_lists_current"],
            analytics_tables=["relay_metadata_current", "relay_software_counts"],
        )

    def test_dependency_validation_rejects_missing_upstream(self) -> None:
        with pytest.raises(ValueError, match="contact_list_edges_current requires"):
            validate_refresh_dependencies(
                current_tables=["contact_list_edges_current"],
                analytics_tables=[],
            )


class TestRefresherConfig:
    def test_default_values(self) -> None:
        config = RefresherConfig()

        assert config.refresh.current_tables == DEFAULT_CURRENT_TABLES
        assert config.refresh.analytics_tables == DEFAULT_ANALYTICS_TABLES
        assert config.interval == 86400.0
        assert config.max_consecutive_failures == 5

    def test_custom_nested_config(self) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(
                current_tables=["events_replaceable_current"],
                analytics_tables=["pubkey_stats"],
            ),
        )

        assert config.refresh.current_tables == ["events_replaceable_current"]
        assert config.refresh.analytics_tables == ["pubkey_stats"]

    def test_from_dict_nested(self) -> None:
        config = RefresherConfig(
            refresh={
                "current_tables": ["events_replaceable_current"],
                "analytics_tables": ["pubkey_stats", "kind_stats"],
            },
            interval=1800.0,
        )

        assert config.refresh.current_tables == ["events_replaceable_current"]
        assert config.refresh.analytics_tables == ["pubkey_stats", "kind_stats"]
        assert config.interval == 1800.0


class TestRefresherInit:
    def test_init_with_defaults(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(brotr=mock_refresher_brotr)

        assert refresher._brotr is mock_refresher_brotr
        assert refresher.SERVICE_NAME == "refresher"
        assert refresher.config.refresh.current_tables == DEFAULT_CURRENT_TABLES
        assert refresher.config.refresh.analytics_tables == DEFAULT_ANALYTICS_TABLES
        assert refresher._logger is not None

    def test_init_with_custom_config(self, mock_refresher_brotr: Brotr) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(
                current_tables=["events_replaceable_current"],
                analytics_tables=["daily_counts", "pubkey_kind_stats"],
            ),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        assert refresher.config.refresh.current_tables == ["events_replaceable_current"]
        assert refresher.config.refresh.analytics_tables == ["daily_counts", "pubkey_kind_stats"]

    def test_init_reorders_known_tables_canonically(self, mock_refresher_brotr: Brotr) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(
                current_tables=[
                    "contact_list_edges_current",
                    "events_replaceable_current",
                    "contact_lists_current",
                ],
                analytics_tables=[
                    "relay_stats",
                    "pubkey_relay_stats",
                    "pubkey_kind_stats",
                    "relay_kind_stats",
                    "daily_counts",
                    "pubkey_stats",
                ],
            ),
        )

        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        assert refresher.config.refresh.current_tables == [
            "events_replaceable_current",
            "contact_lists_current",
            "contact_list_edges_current",
        ]
        assert refresher.config.refresh.analytics_tables == [
            "daily_counts",
            "pubkey_kind_stats",
            "pubkey_relay_stats",
            "relay_kind_stats",
            "pubkey_stats",
            "relay_stats",
        ]

    def test_init_rejects_missing_current_dependency(self, mock_refresher_brotr: Brotr) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(
                current_tables=["contact_list_edges_current"],
                analytics_tables=[],
            ),
        )

        with pytest.raises(ValueError, match="contact_list_edges_current requires"):
            Refresher(brotr=mock_refresher_brotr, config=config)

    def test_init_rejects_missing_analytics_dependency(self, mock_refresher_brotr: Brotr) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(
                current_tables=[],
                analytics_tables=["supported_nip_counts"],
            ),
        )

        with pytest.raises(ValueError, match="supported_nip_counts requires"):
            Refresher(brotr=mock_refresher_brotr, config=config)

    def test_config_class_attribute(self) -> None:
        assert Refresher.CONFIG_CLASS is RefresherConfig


class TestRefresherCleanup:
    async def test_cleanup_no_stale(self, mock_refresher_brotr: Brotr) -> None:
        mock_refresher_brotr.get_service_state = AsyncMock(return_value=[])  # type: ignore[method-assign]
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=RefresherConfig(
                refresh=RefreshConfig(
                    current_tables=["events_replaceable_current"],
                    analytics_tables=[],
                )
            ),
        )

        result = await refresher.cleanup()

        assert result == 0

    async def test_cleanup_removes_stale_checkpoints(self, mock_refresher_brotr: Brotr) -> None:
        stale = ServiceState(
            service_name=ServiceName.REFRESHER,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="old_removed_table",
            state_value={"timestamp": 100},
        )
        current = ServiceState(
            service_name=ServiceName.REFRESHER,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="pubkey_kind_stats",
            state_value={"timestamp": 200},
        )
        mock_refresher_brotr.get_service_state = AsyncMock(  # type: ignore[method-assign]
            return_value=[stale, current]
        )
        mock_refresher_brotr.delete_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=RefresherConfig(
                refresh=RefreshConfig(
                    current_tables=[],
                    analytics_tables=["pubkey_kind_stats"],
                )
            ),
        )

        result = await refresher.cleanup()

        assert result == 1
        mock_refresher_brotr.delete_service_state.assert_called_once()
        call_kwargs = mock_refresher_brotr.delete_service_state.call_args.kwargs
        assert call_kwargs["state_keys"] == ["old_removed_table"]


class TestRefresherRun:
    async def test_uses_relay_metadata_watermark_for_metadata_tables(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=RefresherConfig(
                refresh=RefreshConfig(
                    current_tables=["relay_metadata_current"],
                    analytics_tables=[],
                )
            ),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_generated_at",
                AsyncMock(return_value=5),
            ) as mock_generated,
            patch(
                "bigbrotr.services.refresher.service.get_max_seen_at", AsyncMock(return_value=5)
            ) as mock_seen,
            patch("bigbrotr.services.refresher.service.refresh_summary", AsyncMock(return_value=1)),
            patch("bigbrotr.services.refresher.service.refresh_rolling_windows", AsyncMock()),
            patch("bigbrotr.services.refresher.service.refresh_relay_metadata", AsyncMock()),
            patch("bigbrotr.services.refresher.service.refresh_nip85_followers", AsyncMock()),
        ):
            await refresher.run()

        mock_generated.assert_awaited_once_with(mock_refresher_brotr, 0)
        mock_seen.assert_not_called()

    async def test_no_new_data_skips_incremental_refresh(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=RefresherConfig(
                refresh=RefreshConfig(
                    current_tables=[],
                    analytics_tables=["pubkey_kind_stats"],
                )
            ),
        )

        with (
            patch("bigbrotr.services.refresher.service.get_max_seen_at", AsyncMock(return_value=0)),
            patch(
                "bigbrotr.services.refresher.service.refresh_summary", AsyncMock()
            ) as mock_refresh,
            patch("bigbrotr.services.refresher.service.refresh_rolling_windows", AsyncMock()),
            patch("bigbrotr.services.refresher.service.refresh_relay_metadata", AsyncMock()),
            patch("bigbrotr.services.refresher.service.refresh_nip85_followers", AsyncMock()),
        ):
            await refresher.run()

        mock_refresh.assert_not_awaited()
        mock_refresher_brotr.upsert_service_state.assert_not_awaited()

    async def test_new_data_triggers_current_and_analytics_refresh(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=RefresherConfig(
                refresh=RefreshConfig(
                    current_tables=["events_replaceable_current"],
                    analytics_tables=["pubkey_kind_stats"],
                )
            ),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_seen_at",
                AsyncMock(side_effect=[11, 22]),
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_summary", AsyncMock(side_effect=[7, 9])
            ) as mock_refresh,
            patch("bigbrotr.services.refresher.service.refresh_rolling_windows", AsyncMock()),
            patch("bigbrotr.services.refresher.service.refresh_relay_metadata", AsyncMock()),
            patch("bigbrotr.services.refresher.service.refresh_nip85_followers", AsyncMock()),
            patch.object(refresher._logger, "info") as mock_info,
        ):
            await refresher.run()

        assert mock_refresh.await_args_list == [
            call(mock_refresher_brotr, "events_replaceable_current", 0, 11),
            call(mock_refresher_brotr, "pubkey_kind_stats", 0, 22),
        ]
        assert mock_refresher_brotr.upsert_service_state.await_count == 2

        refresh_completed = [
            call for call in mock_info.call_args_list if call.args[0] == "refresh_completed"
        ]
        assert len(refresh_completed) == 1
        assert refresh_completed[0].kwargs["refreshed"] == 5
        assert refresh_completed[0].kwargs["failed"] == 0

    async def test_refresh_failures_continue_to_later_targets(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=RefresherConfig(
                refresh=RefreshConfig(
                    current_tables=["events_replaceable_current"],
                    analytics_tables=["pubkey_kind_stats"],
                )
            ),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_seen_at",
                AsyncMock(side_effect=[11, 22]),
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_summary",
                AsyncMock(side_effect=[asyncpg.PostgresError("boom"), 9]),
            ),
            patch("bigbrotr.services.refresher.service.refresh_rolling_windows", AsyncMock()),
            patch("bigbrotr.services.refresher.service.refresh_relay_metadata", AsyncMock()),
            patch("bigbrotr.services.refresher.service.refresh_nip85_followers", AsyncMock()),
            patch.object(refresher._logger, "error") as mock_error,
            patch.object(refresher._logger, "info") as mock_info,
        ):
            await refresher.run()

        error_events = [call.args[0] for call in mock_error.call_args_list]
        assert "current_refresh_failed" in error_events

        refresh_completed = [
            call for call in mock_info.call_args_list if call.args[0] == "refresh_completed"
        ]
        assert len(refresh_completed) == 1
        assert refresh_completed[0].kwargs["refreshed"] == 4
        assert refresh_completed[0].kwargs["failed"] == 1


class TestRefresherMetrics:
    async def test_gauges_reset_at_start(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=RefresherConfig(
                refresh=RefreshConfig(
                    current_tables=[],
                    analytics_tables=["pubkey_kind_stats"],
                )
            ),
        )

        with (
            patch("bigbrotr.services.refresher.service.get_max_seen_at", AsyncMock(return_value=0)),
            patch("bigbrotr.services.refresher.service.refresh_summary", AsyncMock()),
            patch("bigbrotr.services.refresher.service.refresh_rolling_windows", AsyncMock()),
            patch("bigbrotr.services.refresher.service.refresh_relay_metadata", AsyncMock()),
            patch("bigbrotr.services.refresher.service.refresh_nip85_followers", AsyncMock()),
            patch.object(refresher, "set_gauge") as mock_gauge,
        ):
            await refresher.run()

        first_three = mock_gauge.call_args_list[:3]
        assert first_three[0] == call("targets_total", 4)
        assert first_three[1] == call("targets_refreshed", 0)
        assert first_three[2] == call("targets_failed", 0)
