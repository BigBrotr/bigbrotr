"""Unit tests for the refresher service package."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, call, patch

import asyncpg
import pytest
from pydantic import ValidationError

from bigbrotr.core.brotr import Brotr
from bigbrotr.core.brotr_config import BrotrConfig
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.state_store import ServiceStateStore
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
    get_event_observation_watermark,
    get_incremental_target_spec,
    get_max_associated_at,
    get_max_observed_at,
    get_periodic_target_spec,
    get_relay_document_watermark,
)
from bigbrotr.services.refresher.service import RefreshCycleTotals, RefreshTargetResult


def _periodic_config(enabled: bool = False) -> dict[str, bool]:
    return {
        "rolling_windows": enabled,
        "relay_stats_document": enabled,
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
        assert config.processing.max_source_window == 86_400
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
                        "replaceable_event_current",
                    ],
                },
                "analytics": {
                    "targets": [
                        "contact_list_edges_current",
                        "relay_stats",
                        "contact_lists_current",
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
            CurrentRefreshTarget.REPLACEABLE_EVENT_CURRENT,
        ]
        assert config.analytics.targets == [
            AnalyticsRefreshTarget.DAILY_COUNTS,
            AnalyticsRefreshTarget.PUBKEY_KIND_STATS,
            AnalyticsRefreshTarget.PUBKEY_RELAY_STATS,
            AnalyticsRefreshTarget.RELAY_KIND_STATS,
            AnalyticsRefreshTarget.PUBKEY_STATS,
            AnalyticsRefreshTarget.RELAY_STATS,
            AnalyticsRefreshTarget.CONTACT_LISTS_CURRENT,
            AnalyticsRefreshTarget.CONTACT_LIST_EDGES_CURRENT,
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
                    CurrentRefreshTarget.REPLACEABLE_EVENT_CURRENT,
                    CurrentRefreshTarget.REPLACEABLE_EVENT_CURRENT,
                ],
            )

    def test_dependency_validation_accepts_complete_selection(self) -> None:
        validate_refresh_dependencies(
            current_targets=[
                CurrentRefreshTarget.RELAY_DOCUMENT_CURRENT,
                CurrentRefreshTarget.REPLACEABLE_EVENT_CURRENT,
            ],
            analytics_targets=[
                AnalyticsRefreshTarget.RELAY_SOFTWARE_COUNTS,
                AnalyticsRefreshTarget.CONTACT_LISTS_CURRENT,
            ],
        )

    def test_dependency_validation_rejects_missing_upstream(self) -> None:
        with pytest.raises(ValueError, match="contact_list_edges_current requires"):
            validate_refresh_dependencies(
                current_targets=[],
                analytics_targets=[AnalyticsRefreshTarget.CONTACT_LIST_EDGES_CURRENT],
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
            CurrentRefreshTarget.RELAY_DOCUMENT_CURRENT,
            AnalyticsRefreshTarget.RELAY_SOFTWARE_COUNTS,
            AnalyticsRefreshTarget.SUPPORTED_NIP_COUNTS,
        ],
    )
    def test_document_targets_use_relay_document_watermark(
        self, target: CurrentRefreshTarget | AnalyticsRefreshTarget
    ) -> None:
        assert (
            get_incremental_target_spec(target).watermark_source is WatermarkSource.RELAY_DOCUMENT
        )

    def test_event_targets_use_event_observation_watermark(self) -> None:
        assert (
            get_incremental_target_spec(
                CurrentRefreshTarget.REPLACEABLE_EVENT_CURRENT
            ).watermark_source
            is WatermarkSource.EVENT_OBSERVATION
        )

    def test_periodic_registry_maps_sql_functions(self) -> None:
        assert get_periodic_target_spec(PeriodicRefreshTarget.ROLLING_WINDOWS).sql_function == (
            "rolling_windows_refresh"
        )
        assert get_periodic_target_spec(
            PeriodicRefreshTarget.RELAY_STATS_DOCUMENT
        ).sql_function == ("relay_stats_document_refresh")
        assert get_periodic_target_spec(PeriodicRefreshTarget.NIP85_FOLLOWERS).sql_function == (
            "nip85_follower_count_refresh"
        )

    async def test_watermark_queries_return_database_values(self) -> None:
        brotr = MagicMock(spec=Brotr)
        brotr.fetchval = AsyncMock(side_effect=[123, 456])

        assert await get_event_observation_watermark(brotr) == 123
        assert await get_relay_document_watermark(brotr) == 456

    async def test_incremental_watermarks_hold_checkpoint_without_new_rows(self) -> None:
        brotr = MagicMock(spec=Brotr)
        brotr.fetchrow = AsyncMock(
            side_effect=[
                {"min_observed_at": None, "max_observed_at": None},
                {"min_associated_at": None, "max_associated_at": None},
            ]
        )

        assert await get_max_observed_at(brotr, 100) == 100
        assert await get_max_associated_at(brotr, 200) == 200

    async def test_incremental_watermarks_advance_to_source_max_when_rows_exist(self) -> None:
        brotr = MagicMock(spec=Brotr)
        brotr.fetchrow = AsyncMock(
            side_effect=[
                {"min_observed_at": 125, "max_observed_at": 150},
                {"min_associated_at": 225, "max_associated_at": 250},
            ]
        )

        assert await get_max_observed_at(brotr, 100) == 150
        assert await get_max_associated_at(brotr, 200) == 250

    async def test_incremental_watermarks_respect_bounded_source_window(self) -> None:
        brotr = MagicMock(spec=Brotr)
        brotr.fetchrow = AsyncMock(
            side_effect=[
                {"min_observed_at": 100, "max_observed_at": 250},
                {"min_associated_at": 200, "max_associated_at": 400},
            ]
        )

        assert await get_max_observed_at(brotr, 0, 25) == 125
        assert await get_max_associated_at(brotr, 0, 50) == 250


class TestRefresherInit:
    def test_init_with_defaults(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(brotr=mock_refresher_brotr)

        assert refresher._brotr is mock_refresher_brotr
        assert refresher.SERVICE_NAME == "refresher"
        assert refresher.config.current.targets == list(DEFAULT_CURRENT_TARGETS)
        assert refresher.config.analytics.targets == list(DEFAULT_ANALYTICS_TARGETS)
        assert refresher._logger is not None

    def test_state_store_is_initialized_once(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(brotr=mock_refresher_brotr)

        assert isinstance(refresher._state_store, ServiceStateStore)
        assert refresher._state_store._brotr is mock_refresher_brotr

    def test_config_class_attribute(self) -> None:
        assert Refresher.CONFIG_CLASS is RefresherConfig


class TestRefresherCleanup:
    async def test_cleanup_no_stale(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(current=["replaceable_event_current"]),
        )

        result = await refresher.cleanup()

        assert result == 0

    async def test_cleanup_can_be_disabled(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=RefresherConfig.model_validate(
                {
                    "metrics": {"enabled": False},
                    "current": {"targets": ["replaceable_event_current"]},
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
            owner=ServiceName.REFRESHER,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="old_removed_table",
            state_value={"timestamp": 100},
        )
        current = ServiceState(
            owner=ServiceName.REFRESHER,
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

    def test_build_refresh_cycle_plan_collects_targets_and_totals(
        self,
        mock_refresher_brotr: Brotr,
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(
                current=["replaceable_event_current"],
                analytics=["pubkey_kind_stats"],
                periodic=True,
            ),
        )

        plan = refresher._build_refresh_cycle_plan(cycle_start=123.0)

        assert plan.cycle_start == 123.0
        assert [target.value for target in plan.incremental_targets] == [
            "replaceable_event_current",
            "pubkey_kind_stats",
        ]
        assert [target.value for target in plan.periodic_targets] == [
            "rolling_windows",
            "relay_stats_document",
            "nip85_followers",
        ]
        assert plan.totals == RefreshCycleTotals(
            total=5,
            current=1,
            analytics=1,
            periodic=3,
        )

    async def test_uses_relay_document_watermark_for_document_targets(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(current=["relay_document_current"]),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_associated_at",
                AsyncMock(return_value=5),
            ) as mock_associated,
            patch(
                "bigbrotr.services.refresher.service.get_max_observed_at", AsyncMock(return_value=5)
            ) as mock_seen,
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(return_value=1),
            ),
            patch(
                "bigbrotr.services.refresher.service.get_relay_document_watermark",
                AsyncMock(return_value=5),
            ),
        ):
            await refresher.run()

        mock_associated.assert_awaited_once_with(mock_refresher_brotr, 0, 86_400)
        mock_seen.assert_not_called()

    async def test_passes_configured_source_window_to_event_watermark_query(
        self,
        mock_refresher_brotr: Brotr,
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(
                analytics=["pubkey_kind_stats"],
                processing={"max_source_window": 25},
            ),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_observed_at",
                AsyncMock(return_value=125),
            ) as mock_seen,
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(return_value=1),
            ),
            patch(
                "bigbrotr.services.refresher.service.get_event_observation_watermark",
                AsyncMock(return_value=125),
            ),
        ):
            await refresher.run()

        mock_seen.assert_awaited_once_with(mock_refresher_brotr, 0, 25)

    async def test_run_incremental_cycle_targets_updates_source_checkpoints(
        self,
        mock_refresher_brotr: Brotr,
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(current=["replaceable_event_current"]),
        )
        plan = refresher._build_refresh_cycle_plan(cycle_start=123.0)
        target_results: list[RefreshTargetResult] = []
        source_checkpoints: dict[WatermarkSource, int] = {}
        result = RefreshTargetResult(
            name="replaceable_event_current",
            target_group="current",
            rows=4,
        )

        with patch.object(
            refresher,
            "_run_incremental_target",
            AsyncMock(
                return_value=(
                    result,
                    WatermarkSource.EVENT_OBSERVATION,
                    11,
                )
            ),
        ) as mock_run:
            cutoff_reason = await refresher._run_incremental_cycle_targets(
                plan=plan,
                target_results=target_results,
                source_checkpoints=source_checkpoints,
            )

        assert cutoff_reason is None
        mock_run.assert_awaited_once_with(CurrentRefreshTarget.REPLACEABLE_EVENT_CURRENT)
        assert target_results == [result]
        assert source_checkpoints == {WatermarkSource.EVENT_OBSERVATION: 11}

    async def test_run_periodic_cycle_targets_respects_cutoff_budget(
        self,
        mock_refresher_brotr: Brotr,
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(periodic=True, processing={"max_targets_per_cycle": 1}),
        )
        plan = refresher._build_refresh_cycle_plan(cycle_start=123.0)
        target_results = [
            RefreshTargetResult(name="already-run", target_group="incremental", rows=1),
        ]

        with patch.object(refresher, "_run_periodic_target", AsyncMock()) as mock_periodic:
            cutoff_reason = await refresher._run_periodic_cycle_targets(
                plan=plan,
                target_results=target_results,
                source_checkpoints={},
            )

        assert cutoff_reason == "max_targets_per_cycle"
        mock_periodic.assert_not_awaited()

    async def test_no_new_data_skips_incremental_sql(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(analytics=["pubkey_kind_stats"]),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_observed_at", AsyncMock(return_value=0)
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(),
            ) as mock_refresh,
            patch(
                "bigbrotr.services.refresher.service.get_event_observation_watermark",
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
                current=["replaceable_event_current"],
                analytics=["pubkey_kind_stats"],
            ),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_observed_at",
                AsyncMock(side_effect=[11, 22]),
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(side_effect=[7, 9]),
            ) as mock_refresh,
            patch(
                "bigbrotr.services.refresher.service.get_event_observation_watermark",
                AsyncMock(return_value=22),
            ),
            patch.object(refresher._logger, "info") as mock_info,
        ):
            result = await refresher.refresh()

        assert mock_refresh.await_args_list == [
            call(mock_refresher_brotr, CurrentRefreshTarget.REPLACEABLE_EVENT_CURRENT, 0, 11),
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
        assert refresh_completed[0].kwargs["event_watermark_lag_seconds"] == 0
        assert refresh_completed[0].kwargs["event_backlog_remaining"] is False
        assert refresh_completed[0].kwargs["document_watermark_lag_seconds"] == 0
        assert refresh_completed[0].kwargs["document_backlog_remaining"] is False

    async def test_refresh_failures_continue_to_later_targets(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(
                current=["replaceable_event_current"],
                analytics=["pubkey_kind_stats"],
            ),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_observed_at",
                AsyncMock(side_effect=[11, 22]),
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(side_effect=[asyncpg.PostgresError("boom"), 9]),
            ),
            patch(
                "bigbrotr.services.refresher.service.get_event_observation_watermark",
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
        assert refresh_completed[0].kwargs["event_watermark_lag_seconds"] == 0
        assert refresh_completed[0].kwargs["event_backlog_remaining"] is False

    async def test_fail_fast_mode_raises_after_first_target_failure(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(
                current=["replaceable_event_current"],
                analytics=["pubkey_kind_stats"],
                processing={"continue_on_target_error": False},
            ),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_observed_at",
                AsyncMock(return_value=11),
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(side_effect=asyncpg.PostgresError("boom")),
            ) as mock_refresh,
            patch(
                "bigbrotr.services.refresher.service.get_event_observation_watermark",
                AsyncMock(return_value=11),
            ),
            pytest.raises(RuntimeError, match="replaceable_event_current"),
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
                current=["replaceable_event_current"],
                analytics=["pubkey_kind_stats"],
                periodic=True,
                processing={"max_targets_per_cycle": 1},
            ),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_observed_at",
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
                "bigbrotr.services.refresher.service.get_event_observation_watermark",
                AsyncMock(return_value=11),
            ),
        ):
            result = await refresher.refresh()

        assert result.targets_total == 5
        assert result.targets_attempted == 1
        assert result.targets_skipped == 4
        assert result.cutoff_reason == "max_targets_per_cycle"
        mock_periodic.assert_not_awaited()

    async def test_max_duration_budget_stops_periodic_targets_when_elapsed(
        self,
        mock_refresher_brotr: Brotr,
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(periodic=True, processing={"max_duration": 1.0}),
        )
        plan = refresher._build_refresh_cycle_plan(cycle_start=time.monotonic() - 2.0)

        with patch.object(refresher, "_run_periodic_target", AsyncMock()) as mock_periodic:
            cutoff_reason = await refresher._run_periodic_cycle_targets(
                plan=plan,
                target_results=[],
                source_checkpoints={},
            )

        assert cutoff_reason == "max_duration"
        mock_periodic.assert_not_awaited()

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
                "bigbrotr.services.refresher.service.get_max_observed_at",
                AsyncMock(return_value=50),
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(return_value=1),
            ),
            patch(
                "bigbrotr.services.refresher.service.get_event_observation_watermark",
                AsyncMock(return_value=55),
            ),
        ):
            result = await refresher.refresh()

        assert result.watermark_event_observation_lag_seconds == 5
        assert result.event_observation_backlog_remaining is True

    async def test_relay_document_watermark_lag_is_reported(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(current=["relay_document_current"]),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_associated_at",
                AsyncMock(return_value=50),
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(return_value=1),
            ),
            patch(
                "bigbrotr.services.refresher.service.get_relay_document_watermark",
                AsyncMock(return_value=55),
            ),
        ):
            result = await refresher.refresh()

        assert result.watermark_relay_document_lag_seconds == 5
        assert result.relay_document_backlog_remaining is True


class TestRefresherMetrics:
    async def test_gauges_reset_at_start(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(analytics=["pubkey_kind_stats"], periodic=True),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_observed_at", AsyncMock(return_value=0)
            ),
            patch("bigbrotr.services.refresher.service.refresh_incremental_target", AsyncMock()),
            patch("bigbrotr.services.refresher.service.refresh_periodic_target", AsyncMock()),
            patch(
                "bigbrotr.services.refresher.service.get_event_observation_watermark",
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
        assert call("watermark_event_observation_backlog_remaining", 0) in mock_gauge.call_args_list
        assert call("watermark_relay_document_backlog_remaining", 0) in mock_gauge.call_args_list

    async def test_backlog_gauges_reflect_remaining_source_lag(
        self,
        mock_refresher_brotr: Brotr,
    ) -> None:
        refresher = Refresher(
            brotr=mock_refresher_brotr,
            config=_refresher_config(analytics=["pubkey_kind_stats"]),
        )

        with (
            patch(
                "bigbrotr.services.refresher.service.get_max_observed_at",
                AsyncMock(return_value=50),
            ),
            patch(
                "bigbrotr.services.refresher.service.refresh_incremental_target",
                AsyncMock(return_value=1),
            ),
            patch(
                "bigbrotr.services.refresher.service.get_event_observation_watermark",
                AsyncMock(return_value=55),
            ),
            patch.object(refresher, "set_gauge") as mock_gauge,
        ):
            await refresher.refresh()

        emitted = {call_item.args[0]: call_item.args[1] for call_item in mock_gauge.call_args_list}
        assert emitted["watermark_event_observation_lag_seconds"] == 5
        assert emitted["watermark_event_observation_backlog_remaining"] == 1
        assert emitted["watermark_relay_document_backlog_remaining"] == 0
