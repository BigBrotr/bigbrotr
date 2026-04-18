"""Unit tests for DVM job execution helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from bigbrotr.services.common.catalog import CatalogError, QueryResult
from bigbrotr.services.common.configs import ReadModelPolicy
from bigbrotr.services.common.read_models import ReadCore
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
    read_core = ReadCore(
        policy_source=lambda: {
            "relays": ReadModelPolicy(enabled=True),
            "events": ReadModelPolicy(enabled=True, price=5000),
        }
    )
    read_core.catalog._tables = {"relay": MagicMock(), "event": MagicMock()}
    return JobExecutionContext(
        read_core=read_core,
        exposure_policy={
            "relays": ReadModelPolicy(enabled=True),
            "events": ReadModelPolicy(enabled=True, price=5000),
        },
        default_page_size=100,
        max_page_size=1000,
        request_kind=5050,
    )


class TestProcessRequestEvent:
    async def test_skips_deduplicated_event(self, job_context: JobExecutionContext) -> None:
        event = _make_mock_event(event_id="seen")
        logger = MagicMock()
        send_event = AsyncMock()
        query_resource = AsyncMock()
        processed_ids = {"seen"}

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=processed_ids,
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
            ),
            context=job_context,
        )

        assert result == (0, 0, 0, 0)
        send_event.assert_not_awaited()
        query_resource.assert_not_awaited()
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
                query_resource=AsyncMock(),
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
        query_resource = AsyncMock()

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
            ),
            context=job_context,
        )

        assert result == (1, 0, 0, 1)
        query_resource.assert_not_awaited()
        send_event.assert_awaited_once()
        logger.info.assert_any_call(
            "job_payment_required",
            event_id="needs-payment",
            price=5000,
            bid=1000,
        )

    @patch("bigbrotr.services.dvm.jobs.parse_job_params")
    async def test_accepts_string_bid_from_preparsed_job_params(
        self,
        mock_parse_job_params: MagicMock,
        job_context: JobExecutionContext,
    ) -> None:
        event = _make_mock_event(event_id="job-string-bid")
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_result = QueryResult(rows=[], total=1, limit=10, offset=0)
        query_resource = AsyncMock(return_value=query_result)
        mock_parse_job_params.return_value = {
            "read_model": "events",
            "bid": " 5000 ",
        }

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
            ),
            context=job_context,
        )

        assert result == (1, 1, 0, 0)
        query_resource.assert_awaited_once()
        send_event.assert_awaited_once()

    async def test_executes_query_and_publishes_result(
        self, job_context: JobExecutionContext
    ) -> None:
        event = _make_mock_event(event_id="job-1")
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_result = QueryResult(
            rows=[{"url": "wss://relay.example.com"}], total=1, limit=10, offset=0
        )
        query_resource = AsyncMock(return_value=query_result)

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
            ),
            context=job_context,
        )

        assert result == (1, 1, 0, 0)
        query_resource.assert_awaited_once()
        send_event.assert_awaited_once()
        logger.info.assert_any_call(
            "job_completed",
            event_id="job-1",
            resource_id="relays",
            rows=1,
            duration_ms=pytest.approx(0.0, abs=1000.0),
        )

    async def test_executes_query_for_whitespace_padded_read_model(
        self, job_context: JobExecutionContext
    ) -> None:
        event = _make_mock_event(
            event_id="job-read-model-whitespace",
            tags=[
                ["param", "read_model", "  relays  "],
                ["param", "limit", "10"],
            ],
        )
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_result = QueryResult(
            rows=[{"url": "wss://relay.example.com"}], total=1, limit=10, offset=0
        )
        query_resource = AsyncMock(return_value=query_result)

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
            ),
            context=job_context,
        )

        assert result == (1, 1, 0, 0)
        query_resource.assert_awaited_once()
        send_event.assert_awaited_once()
        logger.info.assert_any_call(
            "job_received",
            event_id="job-read-model-whitespace",
            requested_read_model_id="relays",
            customer="author_pubkey_hex",
        )
        logger.info.assert_any_call(
            "job_completed",
            event_id="job-read-model-whitespace",
            resource_id="relays",
            rows=1,
            duration_ms=pytest.approx(0.0, abs=1000.0),
        )

    async def test_executes_query_for_whitespace_padded_param_key(
        self, job_context: JobExecutionContext
    ) -> None:
        event = _make_mock_event(
            event_id="job-read-model-key-whitespace",
            tags=[
                ["param", " read_model ", "relays"],
                ["param", " limit ", "10"],
            ],
        )
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_result = QueryResult(
            rows=[{"url": "wss://relay.example.com"}], total=1, limit=10, offset=0
        )
        query_resource = AsyncMock(return_value=query_result)

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
            ),
            context=job_context,
        )

        assert result == (1, 1, 0, 0)
        query_resource.assert_awaited_once()
        send_event.assert_awaited_once()
        logger.info.assert_any_call(
            "job_received",
            event_id="job-read-model-key-whitespace",
            requested_read_model_id="relays",
            customer="author_pubkey_hex",
        )

    @patch("bigbrotr.services.dvm.jobs.parse_job_params")
    async def test_accepts_boolean_include_total_from_preparsed_job_params(
        self,
        mock_parse_job_params: MagicMock,
        job_context: JobExecutionContext,
    ) -> None:
        event = _make_mock_event(event_id="job-bool-include-total")
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_result = QueryResult(rows=[], total=1, limit=10, offset=0)
        query_resource = AsyncMock(return_value=query_result)
        mock_parse_job_params.return_value = {
            "read_model": "relays",
            "include_total": True,
        }

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
            ),
            context=job_context,
        )

        assert result == (1, 1, 0, 0)
        assert query_resource.await_args.args[1].include_total is True

    @patch("bigbrotr.services.dvm.jobs.parse_job_params")
    async def test_normalizes_whitespace_padded_keys_from_preparsed_job_params(
        self,
        mock_parse_job_params: MagicMock,
        job_context: JobExecutionContext,
    ) -> None:
        event = _make_mock_event(event_id="job-preparsed-key-whitespace")
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_result = QueryResult(rows=[], total=1, limit=10, offset=0)
        query_resource = AsyncMock(return_value=query_result)
        mock_parse_job_params.return_value = {
            " read_model ": " relays ",
            " limit ": "10",
            " include_total ": True,
        }

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
            ),
            context=job_context,
        )

        assert result == (1, 1, 0, 0)
        assert query_resource.await_args.args[1].limit == 10
        assert query_resource.await_args.args[1].include_total is True
        logger.info.assert_any_call(
            "job_received",
            event_id="job-preparsed-key-whitespace",
            requested_read_model_id="relays",
            customer="author_pubkey_hex",
        )

    @patch("bigbrotr.services.dvm.jobs.parse_job_params")
    async def test_rejects_non_string_read_model_from_preparsed_job_params(
        self,
        mock_parse_job_params: MagicMock,
        job_context: JobExecutionContext,
    ) -> None:
        event = _make_mock_event(event_id="job-invalid-read-model-type")
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_resource = AsyncMock()
        mock_parse_job_params.return_value = {
            "read_model": 123,
        }

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
            ),
            context=job_context,
        )

        assert result == (1, 0, 1, 0)
        query_resource.assert_not_awaited()
        send_event.assert_awaited_once()
        logger.info.assert_any_call(
            "job_received",
            event_id="job-invalid-read-model-type",
            requested_read_model_id="123",
            customer="author_pubkey_hex",
        )

    @patch("bigbrotr.services.dvm.jobs.parse_job_params")
    async def test_rejects_invalid_cursor_type_from_preparsed_job_params(
        self,
        mock_parse_job_params: MagicMock,
        job_context: JobExecutionContext,
    ) -> None:
        event = _make_mock_event(event_id="job-invalid-cursor")
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_resource = AsyncMock()
        mock_parse_job_params.return_value = {
            "read_model": "relays",
            "cursor": 123,
        }

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
            ),
            context=job_context,
        )

        assert result == (1, 0, 1, 0)
        query_resource.assert_not_awaited()
        send_event.assert_awaited_once()

    @patch("bigbrotr.services.dvm.jobs.parse_job_params")
    async def test_rejects_boolean_limit_from_preparsed_job_params(
        self,
        mock_parse_job_params: MagicMock,
        job_context: JobExecutionContext,
    ) -> None:
        event = _make_mock_event(event_id="job-bool-limit")
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_resource = AsyncMock()
        mock_parse_job_params.return_value = {
            "read_model": "relays",
            "limit": True,
        }

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
            ),
            context=job_context,
        )

        assert result == (1, 0, 1, 0)
        query_resource.assert_not_awaited()
        send_event.assert_awaited_once()

    @patch("bigbrotr.services.dvm.jobs.parse_job_params")
    async def test_rejects_invalid_sort_type_from_preparsed_job_params(
        self,
        mock_parse_job_params: MagicMock,
        job_context: JobExecutionContext,
    ) -> None:
        event = _make_mock_event(event_id="job-invalid-sort")
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_resource = AsyncMock()
        mock_parse_job_params.return_value = {
            "read_model": "relays",
            "sort": 123,
        }

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
            ),
            context=job_context,
        )

        assert result == (1, 0, 1, 0)
        query_resource.assert_not_awaited()
        send_event.assert_awaited_once()

    @patch("bigbrotr.services.dvm.jobs.parse_job_params")
    async def test_rejects_invalid_filter_type_from_preparsed_job_params(
        self,
        mock_parse_job_params: MagicMock,
        job_context: JobExecutionContext,
    ) -> None:
        event = _make_mock_event(event_id="job-invalid-filter")
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_resource = AsyncMock()
        mock_parse_job_params.return_value = {
            "read_model": "relays",
            "filter": 123,
        }

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
            ),
            context=job_context,
        )

        assert result == (1, 0, 1, 0)
        query_resource.assert_not_awaited()
        send_event.assert_awaited_once()

    async def test_rejects_malformed_compact_filter_from_job_params(
        self,
        job_context: JobExecutionContext,
    ) -> None:
        event = _make_mock_event(
            event_id="job-invalid-filter-fragment",
            tags=[
                ["param", "read_model", "relays"],
                ["param", "filter", "network=clearnet,invalid"],
            ],
        )
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_resource = AsyncMock()

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
            ),
            context=job_context,
        )

        assert result == (1, 0, 1, 0)
        query_resource.assert_not_awaited()
        send_event.assert_awaited_once()

    @pytest.mark.parametrize("error_type", [CatalogError, OSError, TimeoutError])
    async def test_publishes_client_safe_error_for_known_failures(
        self,
        job_context: JobExecutionContext,
        error_type: type[Exception],
    ) -> None:
        event = _make_mock_event(event_id="job-error")
        logger = MagicMock()
        send_event = AsyncMock(return_value=(("wss://relay.example.com",), {}))
        query_resource = AsyncMock(side_effect=error_type("boom"))

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
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
        query_resource = AsyncMock(side_effect=asyncpg.PostgresError("pg-boom"))

        result = await process_request_event(
            event=event,
            pubkey_hex="service-pubkey",
            processed_ids=set(),
            runtime=JobRuntime(
                logger=logger,
                send_event=send_event,
                query_resource=query_resource,
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
