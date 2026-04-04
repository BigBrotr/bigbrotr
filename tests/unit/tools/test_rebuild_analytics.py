"""Unit tests for the analytics rebuild tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest
from tools import rebuild_analytics as rebuild

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType


class TestParseArgs:
    def test_live_mode_requires_yes(self) -> None:
        with pytest.raises(SystemExit):
            rebuild.parse_args(["--deployment", "bigbrotr"])

    def test_dry_run_does_not_require_yes(self) -> None:
        args = rebuild.parse_args(["--deployment", "bigbrotr", "--dry-run"])
        assert args.deployment == "bigbrotr"
        assert args.dry_run is True
        assert args.yes is False


class TestRebuildAnalytics:
    @pytest.mark.asyncio
    async def test_rebuild_orders_calls_and_resets_state(self) -> None:
        brotr = MagicMock()
        brotr.refresh_materialized_view = AsyncMock()
        brotr.execute = AsyncMock()
        brotr.upsert_service_state = AsyncMock(return_value=len(rebuild.SUMMARY_TABLES))
        brotr.get_service_state = AsyncMock(
            return_value=[
                ServiceState(
                    service_name=ServiceName.ASSERTOR,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key="user:" + "aa" * 32,
                    state_value={"hash": "deadbeef"},
                )
            ]
        )
        brotr.delete_service_state = AsyncMock(return_value=1)

        refresh_summary = AsyncMock(side_effect=range(1, len(rebuild.SUMMARY_TABLES) + 1))
        refresh_rolling_windows = AsyncMock()
        refresh_relay_metadata = AsyncMock()
        refresh_nip85_followers = AsyncMock()

        original_refresh_summary = rebuild.refresh_summary
        original_refresh_rolling_windows = rebuild.refresh_rolling_windows
        original_refresh_relay_metadata = rebuild.refresh_relay_metadata
        original_refresh_nip85_followers = rebuild.refresh_nip85_followers
        rebuild.refresh_summary = refresh_summary
        rebuild.refresh_rolling_windows = refresh_rolling_windows
        rebuild.refresh_relay_metadata = refresh_relay_metadata
        rebuild.refresh_nip85_followers = refresh_nip85_followers
        try:
            result = await rebuild.rebuild_analytics(brotr, until=1234)
        finally:
            rebuild.refresh_summary = original_refresh_summary
            rebuild.refresh_rolling_windows = original_refresh_rolling_windows
            rebuild.refresh_relay_metadata = original_refresh_relay_metadata
            rebuild.refresh_nip85_followers = original_refresh_nip85_followers

        assert result.until == 1234
        assert result.matviews_refreshed == rebuild.MATVIEWS
        assert result.periodic_tasks == [
            "rolling_windows",
            "relay_stats_metadata",
            "nip85_followers",
        ]
        assert result.refresher_checkpoints_upserted == len(rebuild.SUMMARY_TABLES)
        assert result.assertor_checkpoints_deleted == 1

        brotr.refresh_materialized_view.assert_has_awaits([call(view) for view in rebuild.MATVIEWS])
        brotr.execute.assert_awaited_once_with(rebuild.TRUNCATE_SQL)
        refresh_summary.assert_has_awaits(
            [call(brotr, table, 0, 1234) for table in rebuild.SUMMARY_TABLES]
        )
        refresh_rolling_windows.assert_awaited_once_with(brotr)
        refresh_relay_metadata.assert_awaited_once_with(brotr)
        refresh_nip85_followers.assert_awaited_once_with(brotr)
        brotr.upsert_service_state.assert_awaited_once()
        checkpoint_rows = brotr.upsert_service_state.call_args.args[0]
        assert [row.state_key for row in checkpoint_rows] == rebuild.SUMMARY_TABLES
        assert all(row.state_value["timestamp"] == 1234 for row in checkpoint_rows)
        brotr.delete_service_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_assertor_delete_when_no_checkpoints(self) -> None:
        brotr = MagicMock()
        brotr.refresh_materialized_view = AsyncMock()
        brotr.execute = AsyncMock()
        brotr.upsert_service_state = AsyncMock(return_value=len(rebuild.SUMMARY_TABLES))
        brotr.get_service_state = AsyncMock(return_value=[])
        brotr.delete_service_state = AsyncMock()

        original_refresh_summary = rebuild.refresh_summary
        original_refresh_rolling_windows = rebuild.refresh_rolling_windows
        original_refresh_relay_metadata = rebuild.refresh_relay_metadata
        original_refresh_nip85_followers = rebuild.refresh_nip85_followers
        rebuild.refresh_summary = AsyncMock(return_value=0)
        rebuild.refresh_rolling_windows = AsyncMock()
        rebuild.refresh_relay_metadata = AsyncMock()
        rebuild.refresh_nip85_followers = AsyncMock()
        try:
            result = await rebuild.rebuild_analytics(brotr, until=4321)
        finally:
            rebuild.refresh_summary = original_refresh_summary
            rebuild.refresh_rolling_windows = original_refresh_rolling_windows
            rebuild.refresh_relay_metadata = original_refresh_relay_metadata
            rebuild.refresh_nip85_followers = original_refresh_nip85_followers

        assert result.assertor_checkpoints_deleted == 0
        brotr.delete_service_state.assert_not_awaited()
