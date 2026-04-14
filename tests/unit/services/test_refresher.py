"""Unit tests for the refresher service package."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, call, patch

import asyncpg
import pytest
from pydantic import ValidationError

from bigbrotr.core.brotr import Brotr, BrotrConfig
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.refresher import (
    AnalyticsRefreshConfig,
    AnalyticsRefreshTarget,
    CurrentRefreshConfig,
    CurrentRefreshTarget,
    PeriodicRefreshTarget,
    RefreshCycleResult,
    Refresher,
    RefresherConfig,
)
from bigbrotr.services.refresher.configs import (
    DEFAULT_ANALYTICS_TARGETS,
    DEFAULT_CURRENT_TARGETS,
    validate_refresh_dependencies,
)
from bigbrotr.services.refresher.queries import (
    WatermarkSource,
    get_event_relay_watermark,
    get_incremental_target_spec,
    get_max_generated_at,
    get_max_seen_at,
    get_periodic_target_spec,
    get_relay_metadata_watermark,
)


def _periodic_config(enabled: bool = False) -> dict[str, bool]:
    return {
        "rolling_windows": enabled,
        "relay_stats_metadata": enabled,
        "nip85_followers": enabled,
    }


def _refresher_config(
    *,
    current: list[str] | None = None,
    analytics: list[str] | None = None,
    periodic: bool = False,
    processing: dict[str, object] | None = None,
) -> RefresherConfig:
    return RefresherConfig.model_validate(
        {
            "metrics": {"enabled": False},
            "current": {"targets": [] if current is None else current},
            "analytics": {"targets": [] if analytics is None else analytics},
            "periodic": _periodic_config(periodic),
            "processing": processing or {},
        }
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


class TestRefreshTargetConfig:
    def test_default_values(self) -> None:
        config = RefresherConfig()

        assert config.current.targets == list(DEFAULT_CURRENT_TARGETS)
        assert config.analytics.targets == list(DEFAULT_ANALYTICS_TARGETS)
        assert config.periodic.enabled_targets() == list(PeriodicRefreshTarget)
        assert config.processing.max_duration is None
        assert config.processing.max_targets_per_cycle is None
        assert config.processing.continue_on_target_error is True
        assert config.cleanup.enabled is True

    def test_default_lists_are_independent_copies(self) -> None:
        config1 = RefresherConfig()
        config2 = RefresherConfig()

        assert config1.current.targets is not config2.current.targets
        assert config1.analytics.targets is not config2.analytics.targets

    def test_empty_targets_are_allowed(self) -> None:
        config = _refresher_config()

        assert config.current.targets == []
        assert config.analytics.targets == []
        assert config.periodic.enabled_targets() == []

    def test_targets_are_typed_and_canonically_ordered(self) -> None:
        config = RefresherConfig.model_validate(
            {
                "current": {
                    "targets": [
                        "contact_list_edges_current",
                        "events_replaceable_current",
                        "contact_lists_current",
                    ],
                },
                "analytics": {
                    "targets": [
                        "relay_stats",
                        "pubkey_relay_stats",
                        "pubkey_kind_stats",
                        "relay_kind_stats",
                        "daily_counts",
                        "pubkey_stats",
                    ],
                },
            }
        )

        assert config.current.targets == [
            CurrentRefreshTarget.EVENTS_REPLACEABLE_CURRENT,
            CurrentRefreshTarget.CONTACT_LISTS_CURRENT,
            CurrentRefreshTarget.CONTACT_LIST_EDGES_CURRENT,
        ]
        assert config.analytics.targets == [
            AnalyticsRefreshTarget.DAILY_COUNTS,
            AnalyticsRefreshTarget.PUBKEY_KIND_STATS,
            AnalyticsRefreshTarget.PUBKEY_RELAY_STATS,
            AnalyticsRefreshTarget.RELAY_KIND_STATS,
            AnalyticsRefreshTarget.PUBKEY_STATS,
            AnalyticsRefreshTarget.RELAY_STATS,
        ]

    def test_unknown_targets_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CurrentRefreshConfig(targets=["unknown_target"])  # type: ignore[list-item]

        with pytest.raises(ValidationError):
            AnalyticsRefreshConfig(targets=["unknown_target"])  # type: ignore[list-item]

    def test_duplicate_targets_are_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate refresher targets"):
            CurrentRefreshConfig(
                targets=[
                    CurrentRefreshTarget.EVENTS_REPLACEABLE_CURRENT,
                    CurrentRefreshTarget.EVENTS_REPLACEABLE_CURRENT,
                ],
            )

    def test_dependency_validation_accepts_complete_selection(self) -> None:
        validate_refresh_dependencies(
            current_targets=[
                CurrentRefreshTarget.RELAY_METADATA_CURRENT,
                CurrentRefreshTarget.EVENTS_REPLACEABLE_CURRENT,
                CurrentRefreshTarget.CONTACT_LISTS_CURRENT,
            ],
            analytics_targets=[AnalyticsRefreshTarget.RELAY_SOFTWARE_COUNTS],
        )

    def test_dependency_validation_rejects_missing_upstream(self) -> None:
        with pytest.raises(ValueError, match="contact_list_edges_current requires"):
            validate_refresh_dependencies(
                current_targets=[CurrentRefreshTarget.CONTACT_LIST_EDGES_CURRENT],
                analytics_targets=[],
            )

    def test_config_validation_rejects_missing_analytics_dependency(self) -> None:
        with pytest.raises(ValidationError, match="supported_nip_counts requires"):
            _refresher_config(analytics=["supported_nip_counts"])


class TestRefreshQueryRegistry:
    def test_incremental_registry_covers_all_targets(self) -> None:
        for target in (*DEFAULT_CURRENT_TARGETS, *DEFAULT_ANALYTICS_TARGETS):
            spec = get_incremental_target_spec(target)

            assert spec.target is target
            assert spec.sql_function == f"{target.value}_refresh"
            assert spec.metric_key == target.value

    @pytest.mark.parametrize(
        "target",
        [
            CurrentRefreshTarget.RELAY_METADATA_CURRENT,
            AnalyticsRefreshTarget.RELAY_SOFTWARE_COUNTS,
            AnalyticsRefreshTarget.SUPPORTED_NIP_COUNTS,
        ],
    )
    def test_metadata_targets_use_relay_metadata_watermark(
        self, target: CurrentRefreshTarget | AnalyticsRefreshTarget
    ) -> None:
        assert (
            get_incremental_target_spec(target).watermark_source is WatermarkSource.RELAY_METADATA
        )

    def test_event_targets_use_event_relay_watermark(self) -> None:
        assert (
            get_incremental_target_spec(
                CurrentRefreshTarget.EVENTS_REPLACEABLE_CURRENT
            ).watermark_source
            is WatermarkSource.EVENT_RELAY
        )

    def test_periodic_registry_maps_sql_functions(self) -> None:
        assert get_periodic_target_spec(PeriodicRefreshTarget.ROLLING_WINDOWS).sql_function == (
            "rolling_windows_refresh"
        )
        assert get_periodic_target_spec(
            PeriodicRefreshTarget.RELAY_STATS_METADATA
        ).sql_function == ("relay_stats_metadata_refresh")
        assert get_periodic_target_spec(PeriodicRefreshTarget.NIP85_FOLLOWERS).sql_function == (
            "nip85_follower_count_refresh"
        )

    async def test_watermark_queries_return_database_values(self) -> None:
        brotr = MagicMock(spec=Brotr)
        brotr.fetchval = AsyncMock(side_effect=[123, 456])

        assert await get_event_relay_watermark(brotr) == 123
        assert await get_relay_metadata_watermark(brotr) == 456

    async def test_incremental_watermarks_hold_checkpoint_without_new_rows(self) -> None:
        brotr = MagicMock(spec=Brotr)
        brotr.fetchval = AsyncMock(return_value=False)

        assert await get_max_seen_at(brotr, 100) == 100
        assert await get_max_generated_at(brotr, 200) == 200

    async def test_incremental_watermarks_advance_to_wall_clock_when_rows_exist(self) -> None:
        brotr = MagicMock(spec=Brotr)
        brotr.fetchval = AsyncMock(return_value=True)

        with patch("bigbrotr.services.refresher.queries.time.time", return_value=999):
            assert await get_max_seen_at(brotr, 100) == 999
            assert await get_max_generated_at(brotr, 200) == 999


class TestRefresherInit:
    def test_init_with_defaults(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(brotr=mock_refresher_brotr)

        assert refresher._brotr is mock_refresher_brotr
        assert refresher.SERVICE_NAME == "refresher"
        assert refresher.config.current.targets == list(DEFAULT_CURRENT_TARGETS)
        assert refresher.config.analytics.targets == list(DEFAULT_ANALYTICS_TARGETS)
        assert refresher._logger is not None

    def test_config_class_attribute(self) -> None:
        assert Refresher.CONFIG_CLASS is RefresherConfig


class TestRefresherCleanup:
    async def test_cleanup_no_stale(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(current=["events_replaceable_current"]),
        )

        result = await refresher.cleanup()

        assert result == 0

    async def test_cleanup_can_be_disabled(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=RefresherConfig.model_validate(
                {
                    "metrics": {"enabled": False},
                    "current": {"targets": ["events_replaceable_current"]},
                    "analytics": {"targets": []},
                    "periodic": _periodic_config(False),
                    "cleanup": {"enabled": False},
                }
            ),
        )

        result = await refresher.cleanup()

        assert result == 0
        mock_refresher_brotr.get_service_state.assert_not_awaited()

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
            config=_refresher_config(analytics=["pubkey_kind_stats"]),
        )

        result = await refresher.cleanup()

        assert result == 1
        mock_refresher_brotr.delete_service_state.assert_called_once()
        call_args = mock_refresher_brotr.delete_service_state.call_args.args
        assert call_args[2] == ["old_removed_table"]


class TestRefresherRun:
    async def test_run_delegates_to_refresh(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(brotr=mock_refresher_brotr, config=_refresher_config())

        with patch.object(
            refresher,
            "refresh",
            AsyncMock(return_value=RefreshCycleResult()),
        ) as mock_refresh:
            await refresher.run()

        mock_refresh.assert_awaited_once_with()

    async def test_uses_relay_metadata_watermark_for_metadata_targets(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(current=["relay_metadata_current"]),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_generated_at",
                AsyncMock(return_value=5),
            ) as mock_generated,
            patch(
                "bigbrotr.services.refresher.service.get_max_seen_at", AsyncMock(return_value=5)
            ) as mock_seen,
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(return_value=1),
            ),
            patch(
                "bigbrotr.services.refresher.service.get_relay_metadata_watermark",
                AsyncMock(return_value=5),
            ),
        ):
            await refresher.run()

        mock_generated.assert_awaited_once_with(mock_refresher_brotr, 0)
        mock_seen.assert_not_called()

    async def test_no_new_data_skips_incremental_sql(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(analytics=["pubkey_kind_stats"]),
        )

        with (
            patch("bigbrotr.services.refresher.service.get_max_seen_at", AsyncMock(return_value=0)),
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(),
            ) as mock_refresh,
            patch(
                "bigbrotr.services.refresher.service.get_event_relay_watermark",
                AsyncMock(return_value=0),
            ),
        ):
            result = await refresher.run()

        assert result is None
        mock_refresh.assert_not_awaited()
        mock_refresher_brotr.upsert_service_state.assert_not_awaited()

    async def test_new_data_triggers_current_and_analytics_refresh(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(
                current=["events_replaceable_current"],
                analytics=["pubkey_kind_stats"],
            ),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_seen_at",
                AsyncMock(side_effect=[11, 22]),
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(side_effect=[7, 9]),
            ) as mock_refresh,
            patch(
                "bigbrotr.services.refresher.service.get_event_relay_watermark",
                AsyncMock(return_value=22),
            ),
            patch.object(refresher._logger, "info") as mock_info,
        ):
            result = await refresher.refresh()

        assert mock_refresh.await_args_list == [
            call(mock_refresher_brotr, CurrentRefreshTarget.EVENTS_REPLACEABLE_CURRENT, 0, 11),
            call(mock_refresher_brotr, AnalyticsRefreshTarget.PUBKEY_KIND_STATS, 0, 22),
        ]
        assert mock_refresher_brotr.upsert_service_state.await_count == 2
        assert result.targets_total == 2
        assert result.targets_current_total == 1
        assert result.targets_analytics_total == 1
        assert result.targets_periodic_total == 0
        assert result.targets_refreshed == 2
        assert result.targets_failed == 0
        assert result.rows_refreshed == 16

        refresh_completed = [
            logged for logged in mock_info.call_args_list if logged.args[0] == "refresh_completed"
        ]
        assert len(refresh_completed) == 1
        assert refresh_completed[0].kwargs["refreshed"] == 2
        assert refresh_completed[0].kwargs["failed"] == 0

    async def test_refresh_failures_continue_to_later_targets(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(
                current=["events_replaceable_current"],
                analytics=["pubkey_kind_stats"],
            ),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_seen_at",
                AsyncMock(side_effect=[11, 22]),
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(side_effect=[asyncpg.PostgresError("boom"), 9]),
            ),
            patch(
                "bigbrotr.services.refresher.service.get_event_relay_watermark",
                AsyncMock(return_value=22),
            ),
            patch.object(refresher._logger, "error") as mock_error,
            patch.object(refresher._logger, "info") as mock_info,
        ):
            result = await refresher.refresh()

        error_events = [logged.args[0] for logged in mock_error.call_args_list]
        assert "incremental_refresh_failed" in error_events
        assert result.targets_refreshed == 1
        assert result.targets_failed == 1

        refresh_completed = [
            logged for logged in mock_info.call_args_list if logged.args[0] == "refresh_completed"
        ]
        assert len(refresh_completed) == 1
        assert refresh_completed[0].kwargs["refreshed"] == 1
        assert refresh_completed[0].kwargs["failed"] == 1

    async def test_fail_fast_mode_raises_after_first_target_failure(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(
                current=["events_replaceable_current"],
                analytics=["pubkey_kind_stats"],
                processing={"continue_on_target_error": False},
            ),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_seen_at",
                AsyncMock(return_value=11),
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(side_effect=asyncpg.PostgresError("boom")),
            ) as mock_refresh,
            patch(
                "bigbrotr.services.refresher.service.get_event_relay_watermark",
                AsyncMock(return_value=11),
            ),
            pytest.raises(RuntimeError, match="events_replaceable_current"),
        ):
            await refresher.refresh()

        assert mock_refresh.await_count == 1

    async def test_fail_fast_mode_raises_after_periodic_target_failure(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(
                periodic=True,
                processing={"continue_on_target_error": False},
            ),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.refresh_periodic_target",
                AsyncMock(side_effect=asyncpg.PostgresError("boom")),
            ) as mock_periodic,
            pytest.raises(RuntimeError, match="rolling_windows"),
        ):
            await refresher.refresh()

        assert mock_periodic.await_count == 1

    async def test_max_targets_per_cycle_stops_between_periodic_targets(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(
                periodic=True,
                processing={"max_targets_per_cycle": 1},
            ),
        )

        with patch(
            "bigbrotr.services.refresher.service.refresh_periodic_target",
            AsyncMock(),
        ) as mock_periodic:
            result = await refresher.refresh()

        assert result.targets_total == 3
        assert result.targets_attempted == 1
        assert result.targets_skipped == 2
        assert result.cutoff_reason == "max_targets_per_cycle"
        assert mock_periodic.await_count == 1

    async def test_periodic_failures_continue_when_configured(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(periodic=True),
        )

        with patch(
            "bigbrotr.services.refresher.service.refresh_periodic_target",
            AsyncMock(side_effect=[asyncpg.PostgresError("boom"), None, None]),
        ) as mock_periodic:
            result = await refresher.refresh()

        assert mock_periodic.await_count == 3
        assert result.targets_failed == 1
        assert result.targets_refreshed == 2

    async def test_max_targets_per_cycle_stops_before_later_targets(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(
                current=["events_replaceable_current"],
                analytics=["pubkey_kind_stats"],
                periodic=True,
                processing={"max_targets_per_cycle": 1},
            ),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_seen_at",
                AsyncMock(return_value=11),
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(return_value=7),
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_periodic_target",
                AsyncMock(),
            ) as mock_periodic,
            patch(
                "bigbrotr.services.refresher.service.get_event_relay_watermark",
                AsyncMock(return_value=11),
            ),
        ):
            result = await refresher.refresh()

        assert result.targets_total == 5
        assert result.targets_attempted == 1
        assert result.targets_skipped == 4
        assert result.cutoff_reason == "max_targets_per_cycle"
        mock_periodic.assert_not_awaited()

    def test_max_duration_budget_stops_when_elapsed(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(processing={"max_duration": 1.0}),
        )

        cutoff_reason = refresher._cycle_cutoff_reason(
            cycle_start=time.monotonic() - 2.0,
            attempted=0,
        )

        assert cutoff_reason == "max_duration"

    async def test_disabled_periodic_tasks_are_not_executed(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(brotr=mock_refresher_brotr, config=_refresher_config())

        with patch(
            "bigbrotr.services.refresher.service.refresh_periodic_target",
            AsyncMock(),
        ) as mock_periodic:
            result = await refresher.refresh()

        assert result.targets_total == 0
        mock_periodic.assert_not_awaited()

    async def test_watermark_lag_is_reported(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(analytics=["pubkey_kind_stats"]),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_seen_at", AsyncMock(return_value=50)
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(return_value=1),
            ),
            patch(
                "bigbrotr.services.refresher.service.get_event_relay_watermark",
                AsyncMock(return_value=55),
            ),
        ):
            result = await refresher.refresh()

        assert result.watermark_event_relay_lag_seconds == 5

    async def test_relay_metadata_watermark_lag_is_reported(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(current=["relay_metadata_current"]),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_generated_at",
                AsyncMock(return_value=50),
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(return_value=1),
            ),
            patch(
                "bigbrotr.services.refresher.service.get_relay_metadata_watermark",
                AsyncMock(return_value=55),
            ),
        ):
            result = await refresher.refresh()

        assert result.watermark_relay_metadata_lag_seconds == 5


class TestRefresherMetrics:
    async def test_gauges_reset_at_start(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(analytics=["pubkey_kind_stats"], periodic=True),
        )

        with (
            patch("bigbrotr.services.refresher.service.get_max_seen_at", AsyncMock(return_value=0)),
            patch("bigbrotr.services.refresher.service.refresh_incremental_target", AsyncMock()),
            patch("bigbrotr.services.refresher.service.refresh_periodic_target", AsyncMock()),
            patch(
                "bigbrotr.services.refresher.service.get_event_relay_watermark",
                AsyncMock(return_value=0),
            ),
            patch.object(refresher, "set_gauge") as mock_gauge,
        ):
            await refresher.run()

        first_four = mock_gauge.call_args_list[:4]
        assert first_four[0] == call("targets_total", 4)
        assert first_four[1] == call("targets_current_total", 0)
        assert first_four[2] == call("targets_analytics_total", 1)
        assert first_four[3] == call("targets_periodic_total", 3)
