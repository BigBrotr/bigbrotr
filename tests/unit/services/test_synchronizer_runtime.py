"""Unit tests for synchronizer runtime helpers."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.configs import ClearnetConfig, NetworksConfig, TorConfig
from bigbrotr.services.common.types import SyncCursor
from bigbrotr.services.synchronizer import SynchronizerConfig
from bigbrotr.services.synchronizer.runtime import (
    SyncBatchState,
    SyncCyclePlan,
    SyncPageContext,
    SyncWorkerContext,
    build_sync_cycle_plan,
    flush_sync_batch,
    synchronize_cursor_page,
    synchronize_worker,
)


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


class TestSynchronizeCursorPage:
    async def test_flushes_when_batch_limit_reached(self) -> None:
        relay = Relay("wss://relay.example.com")
        event = MagicMock(created_at=123, id="ab" * 32)

        async def iter_concurrent(
            items: list[SyncCursor],
            worker: object,
            *,
            max_concurrency: int,
        ):
            assert max_concurrency == 2
            for item in items:
                assert item.key == relay.url
                yield event, relay

        async def flush_batch(
            buffer_arg: list[MagicMock],
            pending_cursors_arg: dict[str, SyncCursor],
        ) -> int:
            buffer_arg.clear()
            pending_cursors_arg.clear()
            return 5

        inc_gauge = MagicMock()
        logger = MagicMock()
        buffer: list[MagicMock] = []
        pending_cursors: dict[str, SyncCursor] = {}

        with patch(
            "bigbrotr.services.synchronizer.runtime.EventRelay",
            return_value=MagicMock(),
        ):
            synced, timed_out = await synchronize_cursor_page(
                cursors=[
                    SyncCursor(key=relay.url, timestamp=100, id="cd" * 32),
                ],
                batch_state=SyncBatchState(
                    buffer=buffer,
                    pending_cursors=pending_cursors,
                ),
                plan=SyncCyclePlan(
                    networks=(NetworkType.CLEARNET,),
                    end_time=456,
                    total_relays=1,
                    batch_size=1,
                    max_concurrency=2,
                    page_size=2,
                    deadline=time.monotonic() + 60.0,
                ),
                context=SyncPageContext(
                    iter_concurrent=iter_concurrent,
                    worker=MagicMock(),
                    flush_batch=flush_batch,
                    inc_gauge=inc_gauge,
                    logger=logger,
                ),
            )

        assert synced == 5
        assert timed_out is False
        inc_gauge.assert_called_once_with("events_seen")
        assert buffer == []
        assert pending_cursors == {}
        logger.info.assert_not_called()

    async def test_logs_timeout_after_flush(self) -> None:
        relay = Relay("wss://relay.timeout.example")
        event = MagicMock(created_at=123, id="ef" * 32)

        async def iter_concurrent(
            items: list[SyncCursor],
            worker: object,
            *,
            max_concurrency: int,
        ):
            yield event, relay

        flush_batch = AsyncMock(return_value=3)
        logger = MagicMock()
        monotonic = MagicMock(side_effect=[200.0])

        with patch(
            "bigbrotr.services.synchronizer.runtime.EventRelay",
            return_value=MagicMock(),
        ):
            synced, timed_out = await synchronize_cursor_page(
                cursors=[SyncCursor(key=relay.url, timestamp=100, id="01" * 32)],
                batch_state=SyncBatchState(buffer=[], pending_cursors={}),
                plan=SyncCyclePlan(
                    networks=(NetworkType.CLEARNET,),
                    end_time=456,
                    total_relays=1,
                    batch_size=1,
                    max_concurrency=1,
                    page_size=1,
                    deadline=100.0,
                ),
                context=SyncPageContext(
                    iter_concurrent=iter_concurrent,
                    worker=MagicMock(),
                    flush_batch=flush_batch,
                    inc_gauge=MagicMock(),
                    logger=logger,
                ),
                monotonic=monotonic,
            )

        assert synced == 3
        assert timed_out is True
        logger.info.assert_called_once_with("sync_timeout", events_synced=3)


class TestSynchronizeWorker:
    async def test_yields_streamed_events(self) -> None:
        config = SynchronizerConfig()
        relay = Relay("wss://relay.example.com")
        cursor = SyncCursor(key=relay.url, timestamp=123, id="aa" * 32)
        event = MagicMock()
        logger = MagicMock()
        inc_gauge = MagicMock()
        semaphore = asyncio.Semaphore(1)
        client = object()
        client_manager = MagicMock()
        client_manager.get_relay_client = AsyncMock(return_value=client)

        async def stream_events_fn(*args: object):
            assert args[0] is client
            yield event

        items = [
            item
            async for item in synchronize_worker(
                context=SyncWorkerContext(
                    network_semaphores=MagicMock(get=MagicMock(return_value=semaphore)),
                    logger=logger,
                    is_running=lambda: True,
                    config=config,
                    client_manager=client_manager,
                    stream_events_fn=stream_events_fn,
                    inc_gauge=inc_gauge,
                ),
                cursor=cursor,
            )
        ]

        assert items == [(event, relay)]
        client_manager.get_relay_client.assert_awaited_once_with(relay)
        inc_gauge.assert_called_once_with("relays_seen")
        logger.warning.assert_not_called()
        logger.error.assert_not_called()

    async def test_logs_unknown_network_and_returns(self) -> None:
        config = SynchronizerConfig()
        relay = Relay("wss://relay.example.com")
        cursor = SyncCursor(key=relay.url, timestamp=123, id="bb" * 32)
        logger = MagicMock()
        inc_gauge = MagicMock()

        async def stream_events_fn(*args: object):
            if False:
                yield args

        items = [
            item
            async for item in synchronize_worker(
                context=SyncWorkerContext(
                    network_semaphores=MagicMock(get=MagicMock(return_value=None)),
                    logger=logger,
                    is_running=lambda: True,
                    config=config,
                    client_manager=MagicMock(),
                    stream_events_fn=stream_events_fn,
                    inc_gauge=inc_gauge,
                ),
                cursor=cursor,
            )
        ]

        assert items == []
        logger.warning.assert_called_once_with(
            "unknown_network",
            url=relay.url,
            network=relay.network.value,
        )
        inc_gauge.assert_not_called()
