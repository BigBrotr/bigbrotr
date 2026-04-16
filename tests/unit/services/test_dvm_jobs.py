"""Unit tests for DVM job execution helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from bigbrotr.services.common.catalog import CatalogError, QueryResult
from bigbrotr.services.common.configs import ReadModelPolicy
from bigbrotr.services.dvm.jobs import JobExecutionContext, JobRuntime, process_request_event


def _make_mock_event(
    *,
    event_id: str = "abc123",
    author_hex: str = "author_pubkey_hex",
    tags: list[list[str]] | None = None,
) -> MagicMock:
    event = MagicMock()
    event.id.return_value.to_hex.return_value = event_id
    event.author.return_value.to_hex.return_value = author_hex

    if tags is None:
        tags = [
            ["param", "read_model", "relays"],
            ["param", "limit", "10"],
        ]

    mock_tags = []
    for tag_values in tags:
        mock_tag = MagicMock()
        mock_tag.as_vec.return_value = tag_values
        mock_tags.append(mock_tag)

    tag_list = MagicMock()
    tag_list.to_vec.return_value = mock_tags
    event.tags.return_value = tag_list
    return event


@pytest.fixture
def job_context() -> JobExecutionContext:
    return JobExecutionContext(
        policies={
            "relays": ReadModelPolicy(enabled=True),
            "events": ReadModelPolicy(enabled=True, price=5000),
        },
        available_catalog_names={"relay", "event"},
        default_page_size=100,
        max_page_size=1000,
        request_kind=5050,
    )


class TestProcessRequestEvent:
    async def test_skips_deduplicated_event(self, job_context: JobExecutionContext) -> None:
        event = _make_mock_event(event_id="seen")
        logger = MagicMock()
        send_event = AsyncMock()
        query_entry = AsyncMock()
        processed_ids = {"seen"}

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=processed_ids,
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_entry=query_entry,
            ),
            context=job_context,
        )

        assert result == (0, 0, 0, 0)
        send_event.assert_not_awaited()
        query_entry.assert_not_awaited()
        logger.info.assert_not_called()

    async def test_skips_event_targeted_to_other_pubkey(
        self, job_context: JobExecutionContext
    ) -> None:
        event = _make_mock_event(
            tags=[
                ["param", "read_model", "relays"],
                ["p", "someone-else"],
            ]
        )

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=MagicMock(),
                send_event=AsyncMock(),
                query_entry=AsyncMock(),
            ),
            context=job_context,
        )

        assert result == (0, 0, 0, 0)

    async def test_returns_payment_required_for_insufficient_bid(
        self, job_context: JobExecutionContext
    ) -> None:
        event = _make_mock_event(
            event_id="needs-payment",
            tags=[
                ["param", "read_model", "events"],
                ["bid", "1000"],
            ],
        )
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_entry = AsyncMock()

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_entry=query_entry,
            ),
            context=job_context,
        )

        assert result == (1, 0, 0, 1)
        query_entry.assert_not_awaited()
        send_event.assert_awaited_once()
        logger.info.assert_any_call(
            "job_payment_required",
            event_id="needs-payment",
            price=5000,
            bid=1000,
        )

    async def test_executes_query_and_publishes_result(
        self, job_context: JobExecutionContext
    ) -> None:
        event = _make_mock_event(event_id="job-1")
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_result = QueryResult(
            rows=[{"url": "wss://relay.example.com"}], total=1, limit=10, offset=0
        )
        query_entry = AsyncMock(return_value=query_result)

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_entry=query_entry,
            ),
            context=job_context,
        )

        assert result == (1, 1, 0, 0)
        query_entry.assert_awaited_once()
        send_event.assert_awaited_once()
        logger.info.assert_any_call(
            "job_completed",
            event_id="job-1",
            read_model="relays",
            rows=1,
            duration_ms=pytest.approx(0.0, abs=1000.0),
        )

    @pytest.mark.parametrize("error_type", [CatalogError, OSError, TimeoutError])
    async def test_publishes_client_safe_error_for_known_failures(
        self,
        job_context: JobExecutionContext,
        error_type: type[Exception],
    ) -> None:
        event = _make_mock_event(event_id="job-error")
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_entry = AsyncMock(side_effect=error_type("boom"))

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_entry=query_entry,
            ),
            context=job_context,
        )

        assert result == (1, 0, 1, 0)
        send_event.assert_awaited_once()
        logger.error.assert_called_once_with("job_failed", event_id="job-error", error="boom")

    async def test_publishes_client_safe_error_for_postgres_failures(
        self, job_context: JobExecutionContext
    ) -> None:
        event = _make_mock_event(event_id="job-pg-error")
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_entry = AsyncMock(side_effect=asyncpg.PostgresError("pg-boom"))

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_entry=query_entry,
            ),
            context=job_context,
        )

        assert result == (1, 0, 1, 0)
        send_event.assert_awaited_once()
        logger.error.assert_called_once_with(
            "job_failed",
            event_id="job-pg-error",
            error="pg-boom",
        )
