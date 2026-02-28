"""Unit tests for services.api.service module.

Tests:
- ApiConfig defaults and validation
- Api service initialization
- Api._is_table_enabled policy checks
- Api._build_app route registration
- FastAPI endpoints via TestClient
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from bigbrotr.core.brotr import Brotr
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.api.service import Api, ApiConfig
from bigbrotr.services.common.catalog import (
    Catalog,
    ColumnSchema,
    QueryResult,
    TablePolicy,
    TableSchema,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def api_config() -> ApiConfig:
    """Minimal API config for testing."""
    return ApiConfig(
        interval=60.0,
        host="127.0.0.1",
        port=9999,
        max_page_size=100,
        default_page_size=10,
        tables={"service_state": TablePolicy(enabled=False)},
    )


@pytest.fixture
def sample_catalog() -> Catalog:
    """Catalog pre-populated with test tables."""
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
    """Api service with mocked catalog."""
    service = Api(brotr=mock_brotr, config=api_config)
    service._catalog = sample_catalog
    return service


@pytest.fixture
def test_client(api_service: Api) -> TestClient:
    """FastAPI TestClient from the Api service."""
    app = api_service._build_app()
    return TestClient(app)


# ============================================================================
# ApiConfig Tests
# ============================================================================


class TestApiConfig:
    """Tests for ApiConfig Pydantic model."""

    def test_default_values(self) -> None:
        config = ApiConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 8080
        assert config.max_page_size == 1000
        assert config.default_page_size == 100
        assert config.tables == {}
        assert config.cors_origins == []

    def test_custom_values(self) -> None:
        config = ApiConfig(
            host="127.0.0.1",
            port=9000,
            max_page_size=500,
            tables={"event": TablePolicy(enabled=False)},
        )
        assert config.port == 9000
        assert config.max_page_size == 500
        assert config.tables["event"].enabled is False

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


# ============================================================================
# Api Service Tests
# ============================================================================


class TestApi:
    """Tests for Api service class."""

    def test_service_name(self) -> None:
        assert Api.SERVICE_NAME == ServiceName.API

    def test_init(self, api_service: Api) -> None:
        assert api_service._requests_total == 0
        assert api_service._requests_failed == 0
        assert api_service._server_task is None

    def test_is_table_enabled_default(self, api_service: Api) -> None:
        assert api_service._is_table_enabled("relay") is True

    def test_is_table_enabled_disabled(self, api_service: Api) -> None:
        assert api_service._is_table_enabled("service_state") is False

    def test_is_table_enabled_not_in_policy(self, api_service: Api) -> None:
        assert api_service._is_table_enabled("relay_stats") is True


# ============================================================================
# FastAPI Endpoint Tests
# ============================================================================


class TestApiEndpoints:
    """Tests for auto-generated FastAPI endpoints."""

    def test_health(self, test_client: TestClient) -> None:
        resp = test_client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_schema_list(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/v1/schema")
        assert resp.status_code == 200
        data = resp.json()["data"]
        names = [t["name"] for t in data]
        assert "relay" in names
        assert "relay_stats" in names
        # service_state is disabled
        assert "service_state" not in names

    def test_schema_detail(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/v1/schema/relay")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "relay"
        assert data["is_view"] is False
        assert len(data["columns"]) == 2
        assert data["primary_key"] == ["url"]

    def test_schema_detail_disabled_table(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/v1/schema/service_state")
        assert resp.status_code == 404

    def test_schema_detail_nonexistent(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/v1/schema/nonexistent")
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
            resp = test_client.get("/api/v1/relay?limit=10")

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
            side_effect=ValueError("Unknown column: bad"),
        ):
            resp = test_client.get("/api/v1/relay?bad=value")
        assert resp.status_code == 400

    def test_get_row_by_pk(self, test_client: TestClient, api_service: Api) -> None:
        mock_row = {"url": "wss://relay.example.com", "network": "clearnet"}
        with patch.object(
            api_service._catalog,
            "get_by_pk",
            new_callable=AsyncMock,
            return_value=mock_row,
        ):
            resp = test_client.get("/api/v1/relay/wss://relay.example.com")

        assert resp.status_code == 200
        assert resp.json()["data"] == mock_row

    def test_get_row_by_pk_not_found(self, test_client: TestClient, api_service: Api) -> None:
        with patch.object(
            api_service._catalog,
            "get_by_pk",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = test_client.get("/api/v1/relay/wss://nonexistent")
        assert resp.status_code == 404

    def test_disabled_table_not_routed(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/v1/service_state")
        assert resp.status_code in (404, 405)

    def test_view_has_no_pk_route(self, test_client: TestClient) -> None:
        # relay_stats has no PK so no detail route should exist
        resp = test_client.get("/api/v1/relay_stats/something")
        assert resp.status_code in (404, 405)

    def test_table_policy_bypass_rejected(self, test_client: TestClient, api_service: Api) -> None:
        """Query parameter _table cannot override table name to bypass policy."""
        with patch.object(
            api_service._catalog,
            "query",
            new_callable=AsyncMock,
            side_effect=ValueError("Unknown column: _table"),
        ):
            resp = test_client.get("/api/v1/relay?_table=service_state")
        # _table is treated as a filter column (unknown), not as a route override
        assert resp.status_code == 400

    def test_invalid_limit_returns_400(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/v1/relay?limit=not_a_number")
        assert resp.status_code == 400
        assert "Invalid limit" in resp.json()["error"]

    def test_invalid_offset_returns_400(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/v1/relay?offset=abc")
        assert resp.status_code == 400
        assert "Invalid limit" in resp.json()["error"]


# ============================================================================
# Run Cycle Tests
# ============================================================================


class TestApiFallbackHandler:
    """Tests for the fallback exception handler (non-JSON 500s)."""

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
            resp = test_client.get("/api/v1/relay?limit=10")

        assert resp.status_code == 500
        assert resp.json()["error"] == "Internal server error"

    def test_data_error_returns_400_via_catalog(
        self,
        test_client: TestClient,
        api_service: Api,
    ) -> None:
        """asyncpg.DataError is converted to ValueError by Catalog, yielding 400."""
        with patch.object(
            api_service._catalog,
            "query",
            new_callable=AsyncMock,
            side_effect=ValueError("Invalid filter value: invalid input syntax for type bigint"),
        ):
            resp = test_client.get("/api/v1/relay?discovered_at=>=:abc")

        assert resp.status_code == 400
        assert "Invalid filter value" in resp.json()["error"]


class TestApiEndpointTimeouts:
    """Tests for per-route query timeouts."""

    def test_list_rows_query_timeout(self, test_client: TestClient, api_service: Api) -> None:
        async def slow_query(*args: object, **kwargs: object) -> None:
            import asyncio

            await asyncio.sleep(10)

        api_service._config.request_timeout = 0.01
        with patch.object(api_service._catalog, "query", side_effect=slow_query):
            resp = test_client.get("/api/v1/relay?limit=10")
        assert resp.status_code == 504
        assert "timeout" in resp.json()["error"].lower()

    def test_get_row_query_timeout(self, test_client: TestClient, api_service: Api) -> None:
        async def slow_pk(*args: object, **kwargs: object) -> None:
            import asyncio

            await asyncio.sleep(10)

        api_service._config.request_timeout = 0.01
        with patch.object(api_service._catalog, "get_by_pk", side_effect=slow_pk):
            resp = test_client.get("/api/v1/relay/wss://example.com")
        assert resp.status_code == 504
        assert "timeout" in resp.json()["error"].lower()


class TestApiRun:
    """Tests for Api.run() cycle."""

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
