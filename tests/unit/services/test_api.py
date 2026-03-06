"""Unit tests for the api service package."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from bigbrotr.core.brotr import Brotr
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.api.configs import ApiConfig
from bigbrotr.services.api.service import Api
from bigbrotr.services.common.catalog import (
    Catalog,
    CatalogError,
    ColumnSchema,
    QueryResult,
    TableSchema,
)
from bigbrotr.services.common.configs import TableConfig


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def api_config() -> ApiConfig:
    return ApiConfig(
        interval=60.0,
        host="127.0.0.1",
        port=9999,
        max_page_size=100,
        default_page_size=10,
        tables={
            "relay": TableConfig(enabled=True),
            "relay_stats": TableConfig(enabled=True),
        },
    )


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
        "relay_stats": TableSchema(
            name="relay_stats",
            columns=(
                ColumnSchema(name="url", pg_type="text", nullable=False),
                ColumnSchema(name="event_count", pg_type="bigint", nullable=False),
            ),
            primary_key=(),
            is_view=True,
        ),
        "service_state": TableSchema(
            name="service_state",
            columns=(ColumnSchema(name="service_name", pg_type="text", nullable=False),),
            primary_key=("service_name",),
            is_view=False,
        ),
    }
    return catalog


@pytest.fixture
def api_service(mock_brotr: Brotr, api_config: ApiConfig, sample_catalog: Catalog) -> Api:
    service = Api(brotr=mock_brotr, config=api_config)
    service._catalog = sample_catalog
    return service


@pytest.fixture
def test_client(api_service: Api) -> TestClient:
    app = api_service._build_app()
    return TestClient(app)


# ============================================================================
# Configs
# ============================================================================


class TestApiConfig:
    def test_default_values(self) -> None:
        config = ApiConfig()
        assert config.title == "BigBrotr API"
        assert config.host == "0.0.0.0"
        assert config.port == 8080
        assert config.max_page_size == 1000
        assert config.default_page_size == 100
        assert config.tables == {}
        assert config.cors_origins == []

    def test_custom_title(self) -> None:
        config = ApiConfig(title="LilBrotr API")
        assert config.title == "LilBrotr API"

    def test_custom_values(self) -> None:
        config = ApiConfig(
            host="127.0.0.1",
            port=9000,
            max_page_size=500,
            tables={"event": TableConfig(enabled=True)},
        )
        assert config.port == 9000
        assert config.max_page_size == 500
        assert config.tables["event"].enabled is True

    def test_inherits_base_service_config(self) -> None:
        config = ApiConfig(interval=120.0)
        assert config.interval == 120.0
        assert config.max_consecutive_failures == 5

    def test_request_timeout_default(self) -> None:
        config = ApiConfig()
        assert config.request_timeout == 30.0

    def test_request_timeout_custom(self) -> None:
        config = ApiConfig(request_timeout=60.0)
        assert config.request_timeout == 60.0

    def test_default_page_size_exceeds_max_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"default_page_size.*must not exceed.*max_page_size"):
            ApiConfig(default_page_size=500, max_page_size=100)

    def test_default_page_size_equals_max_accepted(self) -> None:
        config = ApiConfig(default_page_size=100, max_page_size=100)
        assert config.default_page_size == 100

    def test_empty_host_rejected(self) -> None:
        with pytest.raises(ValueError):
            ApiConfig(host="")

    def test_port_conflict_with_metrics_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"metrics\.port.*must differ.*HTTP port"):
            ApiConfig(port=8000, metrics={"enabled": True, "port": 8000})

    def test_port_conflict_ignored_when_metrics_disabled(self) -> None:
        config = ApiConfig(port=8000, metrics={"enabled": False, "port": 8000})
        assert config.port == 8000
        assert config.metrics.port == 8000

    def test_different_ports_accepted(self) -> None:
        config = ApiConfig(port=8080, metrics={"enabled": True, "port": 9090})
        assert config.port == 8080
        assert config.metrics.port == 9090


class TestApiConfigRoutePrefix:
    def test_default(self) -> None:
        assert ApiConfig().route_prefix == "/v1"

    def test_custom(self) -> None:
        assert ApiConfig(route_prefix="/api/v1").route_prefix == "/api/v1"

    def test_trailing_slash_stripped(self) -> None:
        assert ApiConfig(route_prefix="/v1/").route_prefix == "/v1"

    def test_leading_slash_added(self) -> None:
        assert ApiConfig(route_prefix="v1").route_prefix == "/v1"

    def test_both_slashes_normalized(self) -> None:
        assert ApiConfig(route_prefix="api/v2/").route_prefix == "/api/v2"

    def test_slash_only_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"route_prefix must not be empty"):
            ApiConfig(route_prefix="/")


# ============================================================================
# Api Service Tests
# ============================================================================


class TestApi:
    def test_service_name(self) -> None:
        assert Api.SERVICE_NAME == ServiceName.API

    def test_init(self, api_service: Api) -> None:
        assert api_service._requests_total == 0
        assert api_service._requests_failed == 0
        assert api_service._server_task is None


# ============================================================================
# FastAPI Endpoint Tests
# ============================================================================


class TestApiEndpoints:
    def test_health(self, test_client: TestClient) -> None:
        resp = test_client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_schema_list(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/schema")
        assert resp.status_code == 200
        data = resp.json()["data"]
        names = [t["name"] for t in data]
        assert "relay" in names
        assert "relay_stats" in names
        # service_state is disabled
        assert "service_state" not in names

    def test_schema_detail(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/schema/relay")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "relay"
        assert data["is_view"] is False
        assert len(data["columns"]) == 2
        assert data["primary_key"] == ["url"]

    def test_schema_detail_disabled_table(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/schema/service_state")
        assert resp.status_code == 404

    def test_schema_detail_nonexistent(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/schema/nonexistent")
        assert resp.status_code == 404

    def test_list_rows(self, test_client: TestClient, api_service: Api) -> None:
        mock_result = QueryResult(
            rows=[{"url": "wss://relay.example.com", "network": "clearnet"}],
            total=1,
            limit=10,
            offset=0,
        )
        with patch.object(
            api_service._catalog, "query", new_callable=AsyncMock, return_value=mock_result
        ):
            resp = test_client.get("/v1/relay?limit=10")

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == [{"url": "wss://relay.example.com", "network": "clearnet"}]
        assert body["meta"]["total"] == 1
        assert body["meta"]["table"] == "relay"

    def test_list_rows_with_filter_error(self, test_client: TestClient, api_service: Api) -> None:
        with patch.object(
            api_service._catalog,
            "query",
            new_callable=AsyncMock,
            side_effect=CatalogError("Unknown column: bad"),
        ):
            resp = test_client.get("/v1/relay?bad=value")
        assert resp.status_code == 400

    def test_get_row_by_pk(self, test_client: TestClient, api_service: Api) -> None:
        mock_row = {"url": "wss://relay.example.com", "network": "clearnet"}
        with patch.object(
            api_service._catalog,
            "get_by_pk",
            new_callable=AsyncMock,
            return_value=mock_row,
        ):
            resp = test_client.get("/v1/relay/wss://relay.example.com")

        assert resp.status_code == 200
        assert resp.json()["data"] == mock_row

    def test_get_row_by_pk_not_found(self, test_client: TestClient, api_service: Api) -> None:
        with patch.object(
            api_service._catalog,
            "get_by_pk",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = test_client.get("/v1/relay/wss://nonexistent")
        assert resp.status_code == 404

    def test_disabled_table_not_routed(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/service_state")
        assert resp.status_code in (404, 405)

    def test_view_has_no_pk_route(self, test_client: TestClient) -> None:
        # relay_stats has no PK so no detail route should exist
        resp = test_client.get("/v1/relay_stats/something")
        assert resp.status_code in (404, 405)

    def test_table_policy_bypass_rejected(self, test_client: TestClient, api_service: Api) -> None:
        with patch.object(
            api_service._catalog,
            "query",
            new_callable=AsyncMock,
            side_effect=CatalogError("Unknown column: _table"),
        ):
            resp = test_client.get("/v1/relay?_table=service_state")
        # _table is treated as a filter column (unknown), not as a route override
        assert resp.status_code == 400

    def test_invalid_limit_returns_400(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/relay?limit=not_a_number")
        assert resp.status_code == 400
        assert "Invalid limit" in resp.json()["error"]

    def test_invalid_offset_returns_400(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/relay?offset=abc")
        assert resp.status_code == 400
        assert "Invalid limit" in resp.json()["error"]


# ============================================================================
# Fallback Handler Tests
# ============================================================================


class TestApiFallbackHandler:
    def test_unhandled_exception_returns_json_500(
        self,
        test_client: TestClient,
        api_service: Api,
    ) -> None:
        with patch.object(
            api_service._catalog,
            "query",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected DB failure"),
        ):
            resp = test_client.get("/v1/relay?limit=10")

        assert resp.status_code == 500
        assert resp.json()["error"] == "Internal server error"

    def test_data_error_returns_400_via_catalog(
        self,
        test_client: TestClient,
        api_service: Api,
    ) -> None:
        with patch.object(
            api_service._catalog,
            "query",
            new_callable=AsyncMock,
            side_effect=CatalogError("Invalid filter value"),
        ):
            resp = test_client.get("/v1/relay?discovered_at=>=:abc")

        assert resp.status_code == 400
        assert "Invalid filter value" in resp.json()["error"]


# ============================================================================
# Timeout Tests
# ============================================================================


class TestApiEndpointTimeouts:
    def test_list_rows_query_timeout(self, test_client: TestClient, api_service: Api) -> None:
        async def slow_query(*args: object, **kwargs: object) -> None:
            import asyncio

            await asyncio.sleep(10)

        api_service._config.request_timeout = 0.01
        with patch.object(api_service._catalog, "query", side_effect=slow_query):
            resp = test_client.get("/v1/relay?limit=10")
        assert resp.status_code == 504
        assert "timeout" in resp.json()["error"].lower()

    def test_get_row_query_timeout(self, test_client: TestClient, api_service: Api) -> None:
        async def slow_pk(*args: object, **kwargs: object) -> None:
            import asyncio

            await asyncio.sleep(10)

        api_service._config.request_timeout = 0.01
        with patch.object(api_service._catalog, "get_by_pk", side_effect=slow_pk):
            resp = test_client.get("/v1/relay/wss://example.com")
        assert resp.status_code == 504
        assert "timeout" in resp.json()["error"].lower()


# ============================================================================
# Custom Route Prefix Tests
# ============================================================================


class TestApiBuildApp:
    def test_app_title_from_config(self, mock_brotr: object, sample_catalog: object) -> None:
        config = ApiConfig(title="LilBrotr API", tables={"relay": TableConfig(enabled=True)})
        service = Api(brotr=mock_brotr, config=config)  # type: ignore[arg-type]
        service._catalog = sample_catalog  # type: ignore[assignment]
        app = service._build_app()
        assert app.title == "LilBrotr API"

    def test_app_title_default(self, api_service: Api) -> None:
        app = api_service._build_app()
        assert app.title == "BigBrotr API"


class TestApiCustomPrefix:
    def test_routes_use_custom_prefix(self, mock_brotr: object, sample_catalog: object) -> None:
        config = ApiConfig(
            interval=60.0,
            host="127.0.0.1",
            port=9999,
            route_prefix="/api/v2",
            tables={"relay": TableConfig(enabled=True)},
        )
        service = Api(brotr=mock_brotr, config=config)  # type: ignore[arg-type]
        service._catalog = sample_catalog  # type: ignore[assignment]
        client = TestClient(service._build_app())

        assert client.get("/api/v2/schema").status_code == 200
        assert client.get("/api/v2/relay").status_code == 200
        # Default prefix must not respond
        assert client.get("/v1/schema").status_code in (404, 405)


# ============================================================================
# Run Cycle Tests
# ============================================================================


class TestApiRun:
    async def test_run_reports_metrics(self, api_service: Api) -> None:
        api_service._requests_total = 42
        api_service._requests_failed = 3

        with (
            patch.object(api_service, "inc_counter") as mock_counter,
            patch.object(api_service, "set_gauge") as mock_gauge,
        ):
            await api_service.run()

        mock_counter.assert_any_call("requests_total", 42)
        mock_counter.assert_any_call("requests_failed", 3)
        # relay + relay_stats enabled, service_state disabled
        mock_gauge.assert_any_call("tables_exposed", 2)

    async def test_run_resets_counters(self, api_service: Api) -> None:
        api_service._requests_total = 10
        api_service._requests_failed = 2

        with patch.object(api_service, "inc_counter"), patch.object(api_service, "set_gauge"):
            await api_service.run()

        assert api_service._requests_total == 0
        assert api_service._requests_failed == 0

    async def test_run_detects_crashed_server_task(self, api_service: Api) -> None:
        failed_task = MagicMock(spec=asyncio.Task)
        failed_task.done.return_value = True
        failed_task.cancelled.return_value = False
        failed_task.exception.return_value = OSError("bind failed")
        api_service._server_task = failed_task

        with pytest.raises(RuntimeError, match="HTTP server task has stopped unexpectedly"):
            await api_service.run()

    async def test_run_ok_when_server_task_running(self, api_service: Api) -> None:
        running_task = MagicMock(spec=asyncio.Task)
        running_task.done.return_value = False
        api_service._server_task = running_task

        with patch.object(api_service, "inc_counter"), patch.object(api_service, "set_gauge"):
            await api_service.run()
