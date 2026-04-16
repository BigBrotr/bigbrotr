"""Unit tests for monitor chunk processing helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

from bigbrotr.models import Relay
from bigbrotr.services.monitor import CheckResult, MetadataFlags
from bigbrotr.services.monitor.processing import (
    MonitorChunkContext,
    MonitorChunkPersistence,
    MonitorWorkerContext,
    log_chunk_outcome,
    monitor_chunk,
    monitor_worker,
    persist_chunk_outcome,
    start_monitor_progress,
)
from bigbrotr.services.monitor.utils import MonitorChunkOutcome


def _relay(url: str = "wss://relay.example.com") -> Relay:
    return Relay.parse(url)


class _SemaphoreMap:
    def __init__(self, semaphore: asyncio.Semaphore | None) -> None:
        self._semaphore = semaphore

    def get(self, _network) -> asyncio.Semaphore | None:
        return self._semaphore


class TestMonitorWorker:
    async def test_unknown_network_yields_failure(self) -> None:
        relay = _relay()
        logger = MagicMock()
        context = MonitorWorkerContext(
            network_semaphores=_SemaphoreMap(None),
            logger=logger,
            check_relay=AsyncMock(),
            publish_discovery=AsyncMock(),
        )

        results = [item async for item in monitor_worker(context=context, relay=relay)]

        assert results == [(relay, None)]
        context.check_relay.assert_not_awaited()
        context.publish_discovery.assert_not_awaited()
        logger.warning.assert_called_once_with(
            "unknown_network",
            url=relay.url,
            network=relay.network.value,
        )

    async def test_successful_result_publishes_discovery(self) -> None:
        relay = _relay()
        result = CheckResult(nip11_info=MagicMock())
        check_relay = AsyncMock(return_value=result)
        publish_discovery = AsyncMock()
        context = MonitorWorkerContext(
            network_semaphores=_SemaphoreMap(asyncio.Semaphore(1)),
            logger=MagicMock(),
            check_relay=check_relay,
            publish_discovery=publish_discovery,
        )

        results = [item async for item in monitor_worker(context=context, relay=relay)]

        assert results == [(relay, result)]
        check_relay.assert_awaited_once_with(relay)
        publish_discovery.assert_awaited_once_with(relay, result)


class TestMonitorChunk:
    async def test_classifies_results_and_updates_gauges(self) -> None:
        relay_ok = _relay("wss://relay-ok.example.com")
        relay_fail = _relay("wss://relay-fail.example.com")
        result = CheckResult(nip11_info=MagicMock())

        async def iter_concurrent(items, worker, *, max_concurrency):
            assert items == [relay_ok, relay_fail]
            assert worker is not None
            assert max_concurrency == 3
            yield relay_ok, result
            yield relay_fail, None

        inc_gauge = MagicMock()
        outcome = await monitor_chunk(
            context=MonitorChunkContext(
                iter_concurrent=iter_concurrent,
                worker=AsyncMock(),
                inc_gauge=inc_gauge,
            ),
            relays=[relay_ok, relay_fail],
            max_concurrency=3,
        )

        assert outcome == MonitorChunkOutcome(
            successful=((relay_ok, result),),
            failed=(relay_fail,),
        )
        assert inc_gauge.call_args_list == [call("succeeded"), call("failed")]


class TestMonitorPersistence:
    async def test_persist_chunk_outcome_stores_metadata_and_checkpoints(self) -> None:
        relay = _relay()
        nip11_info = MagicMock()
        nip11_info.to_dict.return_value = {"name": "relay"}
        result = CheckResult(generated_at=123, nip11_info=nip11_info)
        insert_relay_metadata_fn = AsyncMock(return_value=1)
        upsert_monitor_checkpoints_fn = AsyncMock()

        await persist_chunk_outcome(
            context=MonitorChunkPersistence(
                brotr=AsyncMock(),
                store=MetadataFlags(
                    nip11_info=True,
                    nip66_rtt=False,
                    nip66_ssl=False,
                    nip66_geo=False,
                    nip66_net=False,
                    nip66_dns=False,
                    nip66_http=False,
                ),
                insert_relay_metadata=insert_relay_metadata_fn,
                upsert_monitor_checkpoints=upsert_monitor_checkpoints_fn,
            ),
            chunk_outcome=MonitorChunkOutcome(successful=((relay, result),)),
            checked_at=456,
        )

        insert_relay_metadata_fn.assert_awaited_once()
        metadata = insert_relay_metadata_fn.await_args.args[1]
        assert len(metadata) == 1
        assert metadata[0].relay == relay
        assert metadata[0].generated_at == 123
        upsert_monitor_checkpoints_fn.assert_awaited_once()
        assert upsert_monitor_checkpoints_fn.await_args.args[1] == [relay]
        assert upsert_monitor_checkpoints_fn.await_args.args[2] == 456


class TestMonitorProgressLogging:
    def test_start_monitor_progress_initializes_gauges(self) -> None:
        set_gauge = MagicMock()

        progress = start_monitor_progress(total=7, set_gauge=set_gauge)

        assert progress.total == 7
        assert set_gauge.call_args_list == [
            call("total", 7),
            call("succeeded", 0),
            call("failed", 0),
        ]

    def test_log_chunk_outcome_uses_remaining_budget(self) -> None:
        logger = MagicMock()
        outcome = MonitorChunkOutcome(
            successful=((_relay(), CheckResult(nip11_info=MagicMock())),),
            failed=(_relay("wss://relay-fail.example.com"),),
        )

        log_chunk_outcome(
            logger=logger,
            chunk_outcome=outcome,
            total=10,
            succeeded=4,
            failed=1,
        )

        logger.info.assert_called_once_with(
            "chunk_completed",
            succeeded=1,
            failed=1,
            remaining=5,
        )
