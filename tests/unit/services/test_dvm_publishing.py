"""Unit tests for DVM publishing helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.services.dvm.publishing import AnnouncementContext, publish_announcement, send_event


def _make_send_output(
    success_relays: tuple[str, ...] = ("wss://relay.example.com",),
    failed_relays: dict[str, str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="event-id",
        success=list(success_relays),
        failed=failed_relays or {},
    )


class TestSendEvent:
    async def test_noop_without_client(self) -> None:
        assert await send_event(client=None, builder=object()) == ((), {})

    async def test_raises_when_success_required_but_no_relay_accepts(self) -> None:
        client = MagicMock()
        client.send_event_builder = AsyncMock(
            return_value=_make_send_output(
                success_relays=(),
                failed_relays={"wss://relay.example.com": "rejected"},
            )
        )

        with pytest.raises(OSError, match="not accepted by any relay"):
            await send_event(client=client, builder=object(), require_success=True)


class TestPublishAnnouncement:
    async def test_noop_without_client(self) -> None:
        await publish_announcement(
            client=None,
            logger=MagicMock(),
            context=AnnouncementContext(
                d_tag="bigbrotr-dvm",
                kind=5050,
                name="BigBrotr DVM",
                about="Read-only access",
                read_models=["relays"],
            ),
        )

    async def test_logs_warning_when_unaccepted(self) -> None:
        client = MagicMock()
        client.send_event_builder = AsyncMock(
            return_value=_make_send_output(
                success_relays=(),
                failed_relays={"wss://relay.example.com": "rejected"},
            )
        )
        logger = MagicMock()

        await publish_announcement(
            client=client,
            logger=logger,
            context=AnnouncementContext(
                d_tag="bigbrotr-dvm",
                kind=5050,
                name="BigBrotr DVM",
                about="Read-only access",
                read_models=["relays"],
            ),
        )

        logger.warning.assert_called_once_with(
            "announcement_publish_failed",
            kind=31990,
            error="no relays accepted announcement",
            failed_relays={"wss://relay.example.com": "rejected"},
        )
