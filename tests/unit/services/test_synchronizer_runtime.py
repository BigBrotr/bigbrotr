"""Unit tests for synchronizer runtime helpers."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.configs import ClearnetConfig, NetworksConfig, TorConfig
from bigbrotr.services.common.types import SyncCursor
from bigbrotr.services.synchronizer import SynchronizerConfig
from bigbrotr.services.synchronizer.runtime import build_sync_cycle_plan, flush_sync_batch


@pytest.fixture
def semaphore_budget() -> MagicMock:
    budget = MagicMock()
    budget.max_concurrency.return_value = 3
    return budget


@pytest.fixture
def runtime_brotr() -> MagicMock:
    return MagicMock()


class TestBuildSyncCyclePlan:
    async def test_returns_none_when_no_networks_enabled(
        self,
        runtime_brotr: MagicMock,
        semaphore_budget: MagicMock,
    ) -> None:
        config = SynchronizerConfig(
            networks=NetworksConfig(
                clearnet=ClearnetConfig(enabled=False),
                tor=TorConfig(enabled=False),
            )
        )

        plan = await build_sync_cycle_plan(
            brotr=runtime_brotr,
            config=config,
            network_semaphores=semaphore_budget,
        )

        assert plan is None
        semaphore_budget.max_concurrency.assert_not_called()

    async def test_computes_budget_and_deadline(
        self,
        runtime_brotr: MagicMock,
        semaphore_budget: MagicMock,
    ) -> None:
        config = SynchronizerConfig(
            processing={"batch_size": 250},
            timeouts={"max_duration": 600.0},
        )
        start = time.monotonic()

        with patch(
            "bigbrotr.services.synchronizer.runtime.count_cursors_to_sync",
            new_callable=AsyncMock,
            return_value=11,
        ) as mock_count:
            plan = await build_sync_cycle_plan(
                brotr=runtime_brotr,
                config=config,
                network_semaphores=semaphore_budget,
            )

        assert plan is not None
        assert plan.networks == (NetworkType.CLEARNET,)
        assert plan.total_relays == 11
        assert plan.batch_size == 250
        assert plan.max_concurrency == 3
        assert plan.page_size == 250
        assert start + 599.0 <= plan.deadline <= time.monotonic() + 601.0
        mock_count.assert_awaited_once_with(
            runtime_brotr,
            plan.end_time,
            [NetworkType.CLEARNET],
        )
        semaphore_budget.max_concurrency.assert_called_once_with([NetworkType.CLEARNET])


class TestFlushSyncBatch:
    async def test_persists_and_clears_state(self, runtime_brotr: MagicMock) -> None:
        buffer = [MagicMock(), MagicMock()]
        pending_cursors = {
            "wss://relay.example.com": SyncCursor(
                key="wss://relay.example.com",
                timestamp=123,
                id="ab" * 32,
            )
        }

        with (
            patch(
                "bigbrotr.services.synchronizer.runtime.insert_event_relays",
                new_callable=AsyncMock,
                return_value=7,
            ) as mock_insert,
            patch(
                "bigbrotr.services.synchronizer.runtime.upsert_sync_cursors",
                new_callable=AsyncMock,
            ) as mock_upsert,
        ):
            result = await flush_sync_batch(runtime_brotr, buffer, pending_cursors)

        assert result == 7
        assert buffer == []
        assert pending_cursors == {}
        mock_insert.assert_awaited_once()
        mock_upsert.assert_awaited_once()

    async def test_empty_batch_is_noop(self, runtime_brotr: MagicMock) -> None:
        buffer: list[MagicMock] = []
        pending_cursors: dict[str, SyncCursor] = {}

        with (
            patch(
                "bigbrotr.services.synchronizer.runtime.insert_event_relays",
                new_callable=AsyncMock,
            ) as mock_insert,
            patch(
                "bigbrotr.services.synchronizer.runtime.upsert_sync_cursors",
                new_callable=AsyncMock,
            ) as mock_upsert,
        ):
            result = await flush_sync_batch(runtime_brotr, buffer, pending_cursors)

        assert result == 0
        mock_insert.assert_not_awaited()
        mock_upsert.assert_not_awaited()
