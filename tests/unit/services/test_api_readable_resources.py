"""Unit tests for API readable-resource route handlers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from bigbrotr.core.brotr import Brotr
from bigbrotr.services.api.readable_resources import ApiReadableResourceHandler
from bigbrotr.services.common.catalog import (
    Catalog,
    CatalogError,
    ColumnSchema,
    QueryResult,
    TableSchema,
)
from bigbrotr.services.common.configs import ReadModelPolicy
from bigbrotr.services.common.read_models import ReadCore


@pytest.fixture
def sample_catalog() -> Catalog:
    catalog = Catalog()
    catalog._tables = {
        "relay": TableSchema(
            name="relay",
            columns=(
                ColumnSchema(name="url", pg_type="text", nullable=False),
                ColumnSchema(name="network", pg_type="text", nullable=False),
            ),
            primary_key=("url",),
            is_view=False,
        ),
    }
    return catalog


@pytest.fixture
def read_core(sample_catalog: Catalog) -> ReadCore:
    policies = {"relays": ReadModelPolicy(enabled=True)}
    core = ReadCore(policy_source=lambda: policies)
    core.catalog = sample_catalog
    return core


@pytest.fixture
def handler(mock_brotr: Brotr, read_core: ReadCore) -> ApiReadableResourceHandler:
    resource = read_core.enabled_resources("api")["relays"]
    return ApiReadableResourceHandler(
        brotr=mock_brotr,
        read_core=read_core,
        resource_id="relays",
        resource=resource,
        default_page_size=10,
        max_page_size=100,
        request_timeout=1.0,
    )


def _build_request(
    path: str,
    *,
    query_string: str = "",
    path_params: dict[str, str] | None = None,
) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": query_string.encode(),
        "path_params": path_params or {},
        "headers": [],
    }
    return Request(scope)


class TestApiReadableResourceHandler:
    async def test_list_rows_success(self, handler: ApiReadableResourceHandler) -> None:
        mock_result = QueryResult(
            rows=[{"url": "wss://relay.example.com", "network": "clearnet"}],
            total=None,
            limit=10,
            offset=0,
            next_cursor="opaque-token",
        )
        request = _build_request("/v1/relays", query_string="limit=10")

        with patch.object(
            handler.read_core.catalog,
            "query",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_query:
            response = await handler.list_rows(request)

        assert response.status_code == 200
        assert response.body == (
            b'{"data":[{"url":"wss://relay.example.com","network":"clearnet"}],'
            b'"meta":{"limit":10,"offset":0,"read_model":"relays","next_cursor":"opaque-token"}}'
        )
        _, kwargs = mock_query.call_args
        assert kwargs["limit"] == 10
        assert kwargs["prefer_keyset"] is True

    async def test_list_rows_invalid_query_returns_400(
        self, handler: ApiReadableResourceHandler
    ) -> None:
        request = _build_request("/v1/relays", query_string="limit=bad")

        response = await handler.list_rows(request)

        assert response.status_code == 400
        assert b"Invalid limit or offset" in response.body

    async def test_list_rows_catalog_error_returns_400(
        self, handler: ApiReadableResourceHandler
    ) -> None:
        request = _build_request("/v1/relays", query_string="network=clearnet")

        with patch.object(
            handler.read_core.catalog,
            "query",
            new_callable=AsyncMock,
            side_effect=CatalogError("Unknown column: network"),
        ):
            response = await handler.list_rows(request)

        assert response.status_code == 400
        assert b"Unknown column: network" in response.body

    async def test_list_rows_read_core_contract_error_returns_400(self) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay_stats": TableSchema(
                name="relay_stats",
                columns=(ColumnSchema(name="url", pg_type="text", nullable=False),),
                primary_key=(),
                is_view=True,
            )
        }
        policies = {"relay-stats": ReadModelPolicy(enabled=True)}
        read_core = ReadCore(policy_source=lambda: policies)
        read_core.catalog = catalog
        handler = ApiReadableResourceHandler(
            brotr=MagicMock(),
            read_core=read_core,
            resource_id="relay-stats",
            resource=read_core.enabled_resources("api")["relay-stats"],
            default_page_size=10,
            max_page_size=100,
            request_timeout=1.0,
        )
        request = _build_request("/v1/relay-stats", query_string="cursor=opaque-token")

        with patch.object(
            handler.read_core.catalog,
            "query",
            new_callable=AsyncMock,
        ) as mock_query:
            response = await handler.list_rows(request)

        assert response.status_code == 400
        assert b"Cursor pagination is not supported for this readable resource" in response.body
        mock_query.assert_not_awaited()

    async def test_list_rows_timeout_returns_504(
        self,
        mock_brotr: Brotr,
        read_core: ReadCore,
    ) -> None:
        resource = read_core.enabled_resources("api")["relays"]
        handler = ApiReadableResourceHandler(
            brotr=mock_brotr,
            read_core=read_core,
            resource_id="relays",
            resource=resource,
            default_page_size=10,
            max_page_size=100,
            request_timeout=0.01,
        )
        request = _build_request("/v1/relays", query_string="limit=10")

        async def slow_query(*args: object, **kwargs: object) -> None:
            await asyncio.sleep(10)

        with patch.object(handler.read_core.catalog, "query", side_effect=slow_query):
            response = await handler.list_rows(request)

        assert response.status_code == 504
        assert b"Query timeout" in response.body

    async def test_get_row_success(self, handler: ApiReadableResourceHandler) -> None:
        request = _build_request(
            "/v1/relays/wss://relay.example.com",
            path_params={"url": "wss://relay.example.com"},
        )

        with patch.object(
            handler.read_core.catalog,
            "get_by_pk",
            new_callable=AsyncMock,
            return_value={"url": "wss://relay.example.com", "network": "clearnet"},
        ) as mock_get_by_pk:
            response = await handler.get_row(request)

        assert response.status_code == 200
        assert response.body == (b'{"data":{"url":"wss://relay.example.com","network":"clearnet"}}')
        mock_get_by_pk.assert_awaited_once_with(
            handler.brotr,
            "relay",
            {"url": "wss://relay.example.com"},
        )

    async def test_get_row_invalid_typed_pk_returns_400_before_db_execution(
        self,
        mock_brotr: Brotr,
    ) -> None:
        catalog = Catalog()
        catalog._tables = {
            "daily_counts": TableSchema(
                name="daily_counts",
                columns=(
                    ColumnSchema(
                        name="day",
                        pg_type="timestamp with time zone",
                        nullable=False,
                    ),
                    ColumnSchema(name="event_count", pg_type="bigint", nullable=False),
                ),
                primary_key=("day",),
                is_view=True,
            )
        }
        policies = {"daily-counts": ReadModelPolicy(enabled=True)}
        read_core = ReadCore(policy_source=lambda: policies)
        read_core.catalog = catalog
        handler = ApiReadableResourceHandler(
            brotr=mock_brotr,
            read_core=read_core,
            resource_id="daily-counts",
            resource=read_core.enabled_resources("api")["daily-counts"],
            default_page_size=10,
            max_page_size=100,
            request_timeout=1.0,
        )
        mock_brotr.fetchrow = AsyncMock(return_value=None)  # type: ignore[method-assign]
        request = _build_request(
            "/v1/daily-counts/not-a-timestamp",
            path_params={"day": "not-a-timestamp"},
        )

        response = await handler.get_row(request)

        assert response.status_code == 400
        assert b"Invalid parameter value for column day" in response.body
        mock_brotr.fetchrow.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_get_row_timeout_returns_504(
        self,
        mock_brotr: Brotr,
        read_core: ReadCore,
    ) -> None:
        resource = read_core.enabled_resources("api")["relays"]
        handler = ApiReadableResourceHandler(
            brotr=mock_brotr,
            read_core=read_core,
            resource_id="relays",
            resource=resource,
            default_page_size=10,
            max_page_size=100,
            request_timeout=0.01,
        )
        request = _build_request(
            "/v1/relays/wss://relay.example.com",
            path_params={"url": "wss://relay.example.com"},
        )

        async def slow_get_by_pk(*args: object, **kwargs: object) -> None:
            await asyncio.sleep(10)

        with patch.object(
            handler.read_core.catalog,
            "get_by_pk",
            side_effect=slow_get_by_pk,
        ):
            response = await handler.get_row(request)

        assert response.status_code == 504
        assert b"Query timeout" in response.body
