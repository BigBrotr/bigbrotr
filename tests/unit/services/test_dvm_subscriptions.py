"""Unit tests for DVM request subscription helpers."""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.services.dvm.subscriptions import (
    RequestNotificationBuffer,
    start_request_subscription,
    stop_request_subscription,
)


class TestRequestNotificationBuffer:
    async def test_handle_enqueues_matching_subscription_events(self) -> None:
        queue: asyncio.Queue[object] = asyncio.Queue()
        logger = MagicMock()
        handler = RequestNotificationBuffer(
            subscription_id="sub-1",
            queue=queue,
            logger=logger,
        )
        event = object()

        handler.handle(MagicMock(), "sub-1", event)
        queued = await asyncio.wait_for(queue.get(), timeout=1.0)

        assert queued is event

    async def test_handle_ignores_other_subscriptions(self) -> None:
        queue: asyncio.Queue[object] = asyncio.Queue()
        handler = RequestNotificationBuffer(
            subscription_id="sub-1",
            queue=queue,
            logger=MagicMock(),
        )

        handler.handle(MagicMock(), "sub-2", object())

        assert queue.empty()

    async def test_handle_msg_logs_subscription_state_changes(self) -> None:
        queue: asyncio.Queue[object] = asyncio.Queue()
        logger = MagicMock()
        handler = RequestNotificationBuffer(
            subscription_id="sub-1",
            queue=queue,
            logger=logger,
        )
        relay_url = MagicMock()
        relay_url.__str__.return_value = "wss://relay.example.com"

        eose = MagicMock()
        eose.is_END_OF_STORED_EVENTS.return_value = True
        eose.is_CLOSED.return_value = False
        eose.is_NOTICE.return_value = False
        eose.subscription_id = "sub-1"

        closed = MagicMock()
        closed.is_END_OF_STORED_EVENTS.return_value = False
        closed.is_CLOSED.return_value = True
        closed.is_NOTICE.return_value = False
        closed.subscription_id = "sub-1"
        closed.message = "closed"

        notice = MagicMock()
        notice.is_END_OF_STORED_EVENTS.return_value = False
        notice.is_CLOSED.return_value = False
        notice.is_NOTICE.return_value = True
        notice.message = "notice"

        for relay_msg in (eose, closed, notice):
            msg = MagicMock()
            msg.as_enum.return_value = relay_msg
            handler.handle_msg(relay_url, msg)

        logger.debug.assert_any_call(
            "request_subscription_eose",
            relay="wss://relay.example.com",
            subscription_id="sub-1",
        )
        logger.warning.assert_any_call(
            "request_subscription_closed",
            relay="wss://relay.example.com",
            subscription_id="sub-1",
            message="closed",
        )
        logger.debug.assert_any_call(
            "request_subscription_notice",
            relay="wss://relay.example.com",
            message="notice",
        )


class TestStartRequestSubscription:
    async def test_starts_subscription_and_returns_state(self) -> None:
        client = MagicMock()

        async def _run_notifications(_handler: object) -> None:
            await asyncio.sleep(60)

        client.handle_notifications = AsyncMock(side_effect=_run_notifications)
        client.subscribe_to = AsyncMock(
            return_value=SimpleNamespace(
                id="sub-1",
                success=["wss://relay.example.com"],
                failed={},
            )
        )
        logger = MagicMock()

        try:
            state = await start_request_subscription(
                client=client,
                connected_relays=("wss://relay.example.com",),
                kind=5050,
                since=1234,
                logger=logger,
            )

            assert state.subscription_id == "sub-1"
            assert isinstance(state.queue, asyncio.Queue)
            assert state.task is not None
            client.subscribe_to.assert_awaited_once()
            logger.info.assert_called_once_with(
                "request_subscription_started",
                subscription_id="sub-1",
                relays=1,
                since=1234,
            )
        finally:
            state.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await state.task

    async def test_raises_when_no_relays_accept_subscription(self) -> None:
        client = MagicMock()
        client.subscribe_to = AsyncMock(
            return_value=SimpleNamespace(
                id="sub-1",
                success=[],
                failed={"wss://relay.example.com": "timeout"},
            )
        )
        logger = MagicMock()

        with pytest.raises(TimeoutError, match="could not subscribe to any relay"):
            await start_request_subscription(
                client=client,
                connected_relays=("wss://relay.example.com",),
                kind=5050,
                since=1234,
                logger=logger,
            )

        logger.warning.assert_called_once_with(
            "request_subscription_relay_failed",
            url="wss://relay.example.com",
            error="timeout",
        )


class TestStopRequestSubscription:
    async def test_noop_for_missing_task(self) -> None:
        await stop_request_subscription(None, logger=MagicMock())

    async def test_cancels_running_task(self) -> None:
        task = asyncio.create_task(asyncio.sleep(60))

        await stop_request_subscription(task, logger=MagicMock())

        assert task.cancelled()

    async def test_logs_failed_completed_task(self) -> None:
        logger = MagicMock()

        async def boom() -> None:
            raise RuntimeError("boom")

        task = asyncio.create_task(boom())
        with pytest.raises(RuntimeError):
            await task

        await stop_request_subscription(task, logger=logger)

        logger.warning.assert_called_once_with(
            "request_subscription_task_failed_on_shutdown",
            error="boom",
            error_type="RuntimeError",
        )
