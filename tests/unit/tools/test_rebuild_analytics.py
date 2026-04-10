"""Unit tests for the analytics rebuild tool."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, call

import pytest
import yaml
from tools import rebuild_analytics as rebuild

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType


if TYPE_CHECKING:
    from pathlib import Path


class TestParseArgs:
    def test_live_mode_requires_yes(self) -> None:
        with pytest.raises(SystemExit):
            rebuild.parse_args(["--deployment", "bigbrotr"])

    def test_dry_run_does_not_require_yes(self) -> None:
        args = rebuild.parse_args(["--deployment", "bigbrotr", "--dry-run"])

        assert args.deployment == "bigbrotr"
        assert args.dry_run is True
        assert args.yes is False

    def test_connection_overrides_are_parsed(self) -> None:
        args = rebuild.parse_args(
            [
                "--deployment",
                "bigbrotr",
                "--dry-run",
                "--host",
                "localhost",
                "--port",
                "6543",
                "--database",
                "scratch",
                "--user",
                "postgres",
            ]
        )

        assert args.host == "localhost"
        assert args.port == 6543
        assert args.database == "scratch"
        assert args.user == "postgres"


class TestRuntimeConfig:
    def test_connection_overrides_merge_on_top_of_deployment_yaml(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        config_path = tmp_path / "brotr.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "pool": {
                        "database": {
                            "host": "pgbouncer",
                            "database": "bigbrotr",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(rebuild, "_deployment_brotr_config", lambda _deployment: config_path)

        config = rebuild._runtime_config(
            deployment="bigbrotr",
            host="localhost",
            port=6543,
            database="scratch",
            user="postgres",
        )

        assert config["pool"]["database"] == {
            "host": "localhost",
            "port": 6543,
            "database": "scratch",
            "user": "postgres",
        }


class TestRebuildAnalytics:
    @pytest.mark.asyncio
    async def test_rebuild_orders_calls_and_resets_state(self) -> None:
        brotr = MagicMock()
        brotr.execute = AsyncMock()
        brotr.upsert_service_state = AsyncMock(
            return_value=len(rebuild.CURRENT_TABLES) + len(rebuild.ANALYTICS_TABLES)
        )
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

        refresh_incremental_target = AsyncMock(
            side_effect=range(1, len(rebuild.CURRENT_TARGETS) + len(rebuild.ANALYTICS_TARGETS) + 1)
        )
        refresh_periodic_target = AsyncMock()

        original_refresh_incremental_target = rebuild.refresh_incremental_target
        original_refresh_periodic_target = rebuild.refresh_periodic_target
        rebuild.refresh_incremental_target = refresh_incremental_target
        rebuild.refresh_periodic_target = refresh_periodic_target
        try:
            result = await rebuild.rebuild_analytics(brotr, until=1234)
        finally:
            rebuild.refresh_incremental_target = original_refresh_incremental_target
            rebuild.refresh_periodic_target = original_refresh_periodic_target

        assert result.until == 1234
        assert list(result.current_tables_refreshed) == rebuild.CURRENT_TABLES
        assert list(result.analytics_tables_refreshed) == rebuild.ANALYTICS_TABLES
        assert result.periodic_tasks == [target.value for target in rebuild.PERIODIC_TARGETS]
        assert result.refresher_checkpoints_upserted == (
            len(rebuild.CURRENT_TABLES) + len(rebuild.ANALYTICS_TABLES)
        )
        assert result.assertor_checkpoints_deleted == 1

        brotr.execute.assert_awaited_once_with(rebuild.TRUNCATE_SQL)
        refresh_incremental_target.assert_has_awaits(
            [
                *[call(brotr, target, 0, 1234) for target in rebuild.CURRENT_TARGETS],
                *[call(brotr, target, 0, 1234) for target in rebuild.ANALYTICS_TARGETS],
            ]
        )
        refresh_periodic_target.assert_has_awaits(
            [call(brotr, target) for target in rebuild.PERIODIC_TARGETS]
        )
        brotr.upsert_service_state.assert_awaited_once()
        checkpoint_rows = brotr.upsert_service_state.call_args.args[0]
        assert [row.state_key for row in checkpoint_rows] == [
            *rebuild.CURRENT_TABLES,
            *rebuild.ANALYTICS_TABLES,
        ]
        assert all(row.state_value["timestamp"] == 1234 for row in checkpoint_rows)
        brotr.delete_service_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_assertor_delete_when_no_checkpoints(self) -> None:
        brotr = MagicMock()
        brotr.execute = AsyncMock()
        brotr.upsert_service_state = AsyncMock(
            return_value=len(rebuild.CURRENT_TABLES) + len(rebuild.ANALYTICS_TABLES)
        )
        brotr.get_service_state = AsyncMock(return_value=[])
        brotr.delete_service_state = AsyncMock()

        original_refresh_incremental_target = rebuild.refresh_incremental_target
        original_refresh_periodic_target = rebuild.refresh_periodic_target
        rebuild.refresh_incremental_target = AsyncMock(return_value=0)
        rebuild.refresh_periodic_target = AsyncMock()
        try:
            result = await rebuild.rebuild_analytics(brotr, until=4321)
        finally:
            rebuild.refresh_incremental_target = original_refresh_incremental_target
            rebuild.refresh_periodic_target = original_refresh_periodic_target

        assert result.assertor_checkpoints_deleted == 0
        brotr.delete_service_state.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fail_fast_when_refresh_raises(self) -> None:
        brotr = MagicMock()
        brotr.execute = AsyncMock()
        brotr.upsert_service_state = AsyncMock()
        brotr.get_service_state = AsyncMock()
        brotr.delete_service_state = AsyncMock()

        refresh_incremental_target = AsyncMock(side_effect=[1, RuntimeError("boom")])
        refresh_periodic_target = AsyncMock()

        original_refresh_incremental_target = rebuild.refresh_incremental_target
        original_refresh_periodic_target = rebuild.refresh_periodic_target
        rebuild.refresh_incremental_target = refresh_incremental_target
        rebuild.refresh_periodic_target = refresh_periodic_target
        try:
            with pytest.raises(RuntimeError, match="boom"):
                await rebuild.rebuild_analytics(brotr, until=1234)
        finally:
            rebuild.refresh_incremental_target = original_refresh_incremental_target
            rebuild.refresh_periodic_target = original_refresh_periodic_target

        brotr.execute.assert_awaited_once_with(rebuild.TRUNCATE_SQL)
        refresh_periodic_target.assert_not_awaited()
        brotr.upsert_service_state.assert_not_awaited()
        brotr.delete_service_state.assert_not_awaited()
