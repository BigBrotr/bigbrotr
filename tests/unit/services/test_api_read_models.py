"""Unit tests for API read-model route handlers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Request

from bigbrotr.core.brotr import Brotr
from bigbrotr.services.api.read_models import ApiReadModelHandler
from bigbrotr.services.common.catalog import (
    Catalog,
    CatalogError,
    ColumnSchema,
    QueryResult,
    TableSchema,
)
from bigbrotr.services.common.configs import ReadModelPolicy
from bigbrotr.services.common.read_models import ReadModelSurface


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
def read_models_surface(sample_catalog: Catalog) -> ReadModelSurface:
    policies = {"relays": ReadModelPolicy(enabled=True)}
    surface = ReadModelSurface(policy_source=lambda: policies)
    surface.catalog = sample_catalog
    return surface


@pytest.fixture
def handler(mock_brotr: Brotr, read_models_surface: ReadModelSurface) -> ApiReadModelHandler:
    read_model = read_models_surface.enabled_entries("api")["relays"]
    return ApiReadModelHandler(
        brotr=mock_brotr,
        read_models=read_models_surface,
        read_model_id="relays",
        read_model=read_model,
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


class TestApiReadModelHandler:
    async def test_list_rows_success(self, handler: ApiReadModelHandler) -> None:
        mock_result = QueryResult(
            rows=[{"url": "wss://relay.example.com", "network": "clearnet"}],
            total=None,
            limit=10,
            offset=0,
            next_cursor="opaque-token",
        )
        request = _build_request("/v1/relays", query_string="limit=10")

        with patch.object(
            handler.read_models.catalog,
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

    async def test_list_rows_invalid_query_returns_400(self, handler: ApiReadModelHandler) -> None:
        request = _build_request("/v1/relays", query_string="limit=bad")

        response = await handler.list_rows(request)

        assert response.status_code == 400
        assert b"Invalid limit or offset" in response.body

    async def test_list_rows_catalog_error_returns_400(self, handler: ApiReadModelHandler) -> None:
        request = _build_request("/v1/relays", query_string="network=clearnet")

        with patch.object(
            handler.read_models.catalog,
            "query",
            new_callable=AsyncMock,
            side_effect=CatalogError("Unknown column: network"),
        ):
            response = await handler.list_rows(request)

        assert response.status_code == 400
        assert b"Unknown column: network" in response.body

    async def test_list_rows_timeout_returns_504(
        self,
        mock_brotr: Brotr,
        read_models_surface: ReadModelSurface,
    ) -> None:
        read_model = read_models_surface.enabled_entries("api")["relays"]
        handler = ApiReadModelHandler(
            brotr=mock_brotr,
            read_models=read_models_surface,
            read_model_id="relays",
            read_model=read_model,
            default_page_size=10,
            max_page_size=100,
            request_timeout=0.01,
        )
        request = _build_request("/v1/relays", query_string="limit=10")

        async def slow_query(*args: object, **kwargs: object) -> None:
            await asyncio.sleep(10)

        with patch.object(handler.read_models.catalog, "query", side_effect=slow_query):
            response = await handler.list_rows(request)

        assert response.status_code == 504
        assert b"Query timeout" in response.body

    async def test_get_row_success(self, handler: ApiReadModelHandler) -> None:
        request = _build_request(
            "/v1/relays/wss://relay.example.com",
            path_params={"url": "wss://relay.example.com"},
        )

        with patch.object(
            handler.read_models.catalog,
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

    async def test_get_row_timeout_returns_504(
        self,
        mock_brotr: Brotr,
        read_models_surface: ReadModelSurface,
    ) -> None:
        read_model = read_models_surface.enabled_entries("api")["relays"]
        handler = ApiReadModelHandler(
            brotr=mock_brotr,
            read_models=read_models_surface,
            read_model_id="relays",
            read_model=read_model,
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
            handler.read_models.catalog,
            "get_by_pk",
            side_effect=slow_get_by_pk,
        ):
            response = await handler.get_row(request)

        assert response.status_code == 504
        assert b"Query timeout" in response.body
