"""Unit tests for Finder API runtime helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.models import Relay
from bigbrotr.services.common.types import ApiCheckpoint
from bigbrotr.services.finder import ApiSourceConfig
from bigbrotr.services.finder.api_runtime import (
    ApiDiscoveryPersistenceContext,
    ApiDiscoveryWorkerContext,
    build_api_source_attempts,
    find_from_api_worker,
    persist_api_discovery_results,
)


@pytest.fixture
def runtime_brotr() -> MagicMock:
    return MagicMock()


class TestBuildApiSourceAttempts:
    def test_skips_sources_until_fractional_cooldown_elapses(self) -> None:
        source = ApiSourceConfig(url="https://api.example.com", expression="[*]")
        logger = MagicMock()

        attempts = build_api_source_attempts(
            [source],
            {source.url: ApiCheckpoint(key=source.url, timestamp=6_400)},
            cooldown=3600.9,
            now=10_000,
            logger=logger,
        )

        assert attempts == ()
        assert logger.debug.call_args is not None
        assert logger.debug.call_args.kwargs["seconds_left"] == pytest.approx(0.9)


class TestFindFromApiWorker:
    async def test_loads_checkpoints_and_streams_attempts(self, runtime_brotr: MagicMock) -> None:
        source = ApiSourceConfig(url="https://api.example.com", expression="[*]")
        relay = Relay("wss://relay.example.com")
        checkpoint = ApiCheckpoint(key=source.url, timestamp=123)
        fetch_checkpoints = AsyncMock(return_value=[checkpoint])
        logger = MagicMock()

        async def fetch_api_fn(*args: object) -> list[Relay]:
            return [relay]

        class _Session:
            async def __aenter__(self) -> _Session:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

        items = [
            item
            async for item in find_from_api_worker(
                sources=[source],
                context=ApiDiscoveryWorkerContext(
                    brotr=runtime_brotr,
                    cooldown=0,
                    current_time=lambda: 1_000,
                    max_response_size=1024,
                    request_delay=0.0,
                    is_running=lambda: True,
                    wait=AsyncMock(return_value=False),
                    fetch_api_fn=fetch_api_fn,
                    client_session_factory=_Session,
                    recoverable_errors=(TimeoutError, OSError, ValueError),
                    checkpoint_timestamp=lambda: 456,
                    logger=logger,
                    fetch_api_checkpoints_fn=fetch_checkpoints,
                ),
            )
        ]

        assert items == [([relay], ApiCheckpoint(key=source.url, timestamp=456))]
        fetch_checkpoints.assert_awaited_once_with(runtime_brotr, [source.url])

    async def test_later_source_can_become_due_during_request_delay(
        self,
        runtime_brotr: MagicMock,
    ) -> None:
        sources = [
            ApiSourceConfig(url="https://api1.example.com", expression="[*]"),
            ApiSourceConfig(url="https://api2.example.com", expression="[*]"),
        ]
        relay = Relay("wss://relay.example.com")
        fetch_checkpoints = AsyncMock(
            return_value=[
                ApiCheckpoint(key="https://api1.example.com", timestamp=0),
                ApiCheckpoint(key="https://api2.example.com", timestamp=95),
            ]
        )
        fetch_api_fn = AsyncMock(return_value=[relay])
        wait = AsyncMock(return_value=False)
        current_times = iter((100.0, 106.0))

        class _Session:
            async def __aenter__(self) -> _Session:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

        items = [
            item
            async for item in find_from_api_worker(
                sources=sources,
                context=ApiDiscoveryWorkerContext(
                    brotr=runtime_brotr,
                    cooldown=10.0,
                    current_time=lambda: next(current_times),
                    max_response_size=1024,
                    request_delay=1.0,
                    is_running=lambda: True,
                    wait=wait,
                    fetch_api_fn=fetch_api_fn,
                    client_session_factory=_Session,
                    recoverable_errors=(TimeoutError, OSError, ValueError),
                    checkpoint_timestamp=lambda: 456,
                    logger=MagicMock(),
                    fetch_api_checkpoints_fn=fetch_checkpoints,
                ),
            )
        ]

        assert items == [
            ([relay], ApiCheckpoint(key="https://api1.example.com", timestamp=456)),
            ([relay], ApiCheckpoint(key="https://api2.example.com", timestamp=456)),
        ]
        assert fetch_api_fn.await_count == 2
        wait.assert_awaited_once_with(1.0)

    async def test_stops_when_wait_requests_shutdown(self, runtime_brotr: MagicMock) -> None:
        sources = [
            ApiSourceConfig(url="https://api1.example.com", expression="[*]"),
            ApiSourceConfig(url="https://api2.example.com", expression="[*]"),
        ]
        relay = Relay("wss://relay.example.com")
        fetch_checkpoints = AsyncMock(
            return_value=[ApiCheckpoint(key=source.url, timestamp=0) for source in sources]
        )
        fetch_api_fn = AsyncMock(return_value=[relay])
        wait = AsyncMock(return_value=True)

        class _Session:
            async def __aenter__(self) -> _Session:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

        items = [
            item
            async for item in find_from_api_worker(
                sources=sources,
                context=ApiDiscoveryWorkerContext(
                    brotr=runtime_brotr,
                    cooldown=0,
                    current_time=lambda: 1_000,
                    max_response_size=1024,
                    request_delay=1.0,
                    is_running=lambda: True,
                    wait=wait,
                    fetch_api_fn=fetch_api_fn,
                    client_session_factory=_Session,
                    recoverable_errors=(TimeoutError, OSError, ValueError),
                    checkpoint_timestamp=lambda: 456,
                    logger=MagicMock(),
                    fetch_api_checkpoints_fn=fetch_checkpoints,
                ),
            )
        ]

        assert len(items) == 1
        fetch_api_fn.assert_awaited_once()
        wait.assert_awaited_once_with(1.0)


class TestPersistApiDiscoveryResults:
    async def test_persists_and_clears_state(self, runtime_brotr: MagicMock) -> None:
        relay = Relay("wss://relay.example.com")
        checkpoint = ApiCheckpoint(key="https://api.example.com", timestamp=123)
        buffer = [relay]
        pending_checkpoints = [checkpoint]
        calls: list[str] = []

        async def upsert(*args: object) -> None:
            calls.append("upsert")

        async def insert_relays(*args: object) -> int:
            calls.append("insert")
            return 1

        set_gauge = MagicMock()

        found = await persist_api_discovery_results(
            buffer=buffer,
            pending_checkpoints=pending_checkpoints,
            context=ApiDiscoveryPersistenceContext(
                brotr=runtime_brotr,
                upsert_api_checkpoints_fn=upsert,
                insert_relays_fn=insert_relays,
                set_gauge=set_gauge,
            ),
        )

        assert found == 1
        assert buffer == []
        assert pending_checkpoints == []
        assert calls == ["insert", "upsert"]
        set_gauge.assert_called_once_with("candidates_found_from_api", 1)

    async def test_empty_checkpoints_still_inserts_relays(self, runtime_brotr: MagicMock) -> None:
        relay = Relay("wss://relay.example.com")
        upsert = AsyncMock()
        insert_relays = AsyncMock(return_value=1)

        found = await persist_api_discovery_results(
            buffer=[relay],
            pending_checkpoints=[],
            context=ApiDiscoveryPersistenceContext(
                brotr=runtime_brotr,
                upsert_api_checkpoints_fn=upsert,
                insert_relays_fn=insert_relays,
                set_gauge=MagicMock(),
            ),
        )

        assert found == 1
        upsert.assert_not_awaited()
        insert_relays.assert_awaited_once()

    async def test_insert_failure_does_not_advance_checkpoints(
        self, runtime_brotr: MagicMock
    ) -> None:
        relay = Relay("wss://relay.example.com")
        checkpoint = ApiCheckpoint(key="https://api.example.com", timestamp=123)
        buffer = [relay]
        pending_checkpoints = [checkpoint]
        upsert = AsyncMock()
        insert_relays = AsyncMock(side_effect=RuntimeError("insert failed"))
        set_gauge = MagicMock()

        with pytest.raises(RuntimeError, match="insert failed"):
            await persist_api_discovery_results(
                buffer=buffer,
                pending_checkpoints=pending_checkpoints,
                context=ApiDiscoveryPersistenceContext(
                    brotr=runtime_brotr,
                    upsert_api_checkpoints_fn=upsert,
                    insert_relays_fn=insert_relays,
                    set_gauge=set_gauge,
                ),
            )

        assert buffer == [relay]
        assert pending_checkpoints == [checkpoint]
        upsert.assert_not_awaited()
        set_gauge.assert_not_called()
