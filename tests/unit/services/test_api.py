"""Unit tests for the api service package."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

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
from bigbrotr.services.common.configs import ReadModelPolicy


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
        read_models={
            "relays": ReadModelPolicy(enabled=True),
            "relay-stats": ReadModelPolicy(enabled=True),
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
            columns=(ColumnSchema(name="owner", pg_type="text", nullable=False),),
            primary_key=("owner",),
            is_view=False,
        ),
    }
    return catalog


@pytest.fixture
def composite_pk_catalog() -> Catalog:
    catalog = Catalog()
    catalog._tables = {
        "relay_document": TableSchema(
            name="relay_document",
            columns=(
                ColumnSchema(name="relay_url", pg_type="text", nullable=False),
                ColumnSchema(name="document_id", pg_type="bytea", nullable=False),
                ColumnSchema(name="role", pg_type="text", nullable=False),
            ),
            primary_key=("relay_url", "document_id", "role"),
            is_view=False,
        ),
    }
    return catalog


@pytest.fixture
def api_service(mock_brotr: Brotr, api_config: ApiConfig, sample_catalog: Catalog) -> Api:
    service = Api(brotr=mock_brotr, config=api_config)
    service._read_core.catalog = sample_catalog
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
        assert config.read_models == {}
        assert config.cors_origins == []
        assert config.request_timeout == 30.0

    def test_custom_values(self) -> None:
        config = ApiConfig(
            title="LilBrotr API",
            host="127.0.0.1",
            port=9000,
            max_page_size=500,
            request_timeout=60.0,
            read_models={"events": ReadModelPolicy(enabled=True)},
        )
        assert config.title == "LilBrotr API"
        assert config.port == 9000
        assert config.max_page_size == 500
        assert config.request_timeout == 60.0
        assert config.read_models["events"].enabled is True

    def test_whitespace_only_title_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"title must not be blank"):
            ApiConfig(title="   ")

    def test_padded_title_is_trimmed(self) -> None:
        config = ApiConfig(title="  LilBrotr API  ")
        assert config.title == "LilBrotr API"

    def test_whitespace_only_cors_origin_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"cors_origins\[0\] must not be blank"):
            ApiConfig(cors_origins=["   "])

    def test_padded_cors_origin_is_trimmed(self) -> None:
        config = ApiConfig(cors_origins=[" https://example.com "])
        assert config.cors_origins == ["https://example.com"]

    def test_duplicate_cors_origins_are_deduplicated(self) -> None:
        config = ApiConfig(
            cors_origins=[
                "https://example.com",
                " https://example.com ",
                "https://relay.example",
                "https://example.com",
            ]
        )
        assert config.cors_origins == [
            "https://example.com",
            "https://relay.example",
        ]

    def test_exposure_policy_aliases_read_models(self) -> None:
        config = ApiConfig(read_models={"relays": ReadModelPolicy(enabled=True)})
        assert config.exposure_policy == config.read_models

    @pytest.mark.parametrize("value", ["true", 1])
    def test_rejects_boolean_read_model_enabled_aliases(self, value: object) -> None:
        with pytest.raises(ValidationError, match=r"enabled: expected boolean, got"):
            ApiConfig(read_models={"relays": {"enabled": value}})

    def test_read_models_require_canonical_names(self) -> None:
        with pytest.raises(
            ValueError,
            match=r"read_models contains non-public API read models: event",
        ):
            ApiConfig(read_models={"event": ReadModelPolicy(enabled=True)})

        with pytest.raises(
            ValueError,
            match=r"read_models contains non-public API read models: relay",
        ):
            ApiConfig(read_models={"relay": ReadModelPolicy(enabled=True)})

    def test_tables_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="Use read_models instead of tables"):
            ApiConfig(tables={"relay": ReadModelPolicy(enabled=True)})

    def test_inherits_base_service_config(self) -> None:
        config = ApiConfig(interval=120.0)
        assert config.interval == 120.0
        assert config.max_consecutive_failures == 5

    def test_default_page_size_exceeds_max_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"default_page_size.*must not exceed.*max_page_size"):
            ApiConfig(default_page_size=500, max_page_size=100)

    def test_default_page_size_equals_max_accepted(self) -> None:
        config = ApiConfig(default_page_size=100, max_page_size=100)
        assert config.default_page_size == 100

    def test_rejects_boolean_default_page_size_alias(self) -> None:
        with pytest.raises(ValueError, match="default_page_size: expected integer, got bool"):
            ApiConfig(default_page_size=True)

    @pytest.mark.parametrize("value", ["100", 100.0])
    def test_rejects_non_integer_default_page_size_aliases(self, value: object) -> None:
        with pytest.raises(ValueError, match=r"default_page_size: expected integer, got"):
            ApiConfig(default_page_size=value)

    def test_rejects_boolean_max_page_size_alias(self) -> None:
        with pytest.raises(ValueError, match="max_page_size: expected integer, got bool"):
            ApiConfig(max_page_size=True)

    @pytest.mark.parametrize("value", ["1000", 1000.0])
    def test_rejects_non_integer_max_page_size_aliases(self, value: object) -> None:
        with pytest.raises(ValueError, match=r"max_page_size: expected integer, got"):
            ApiConfig(max_page_size=value)

    def test_rejects_boolean_request_timeout_alias(self) -> None:
        with pytest.raises(ValueError, match="request_timeout: expected number, got bool"):
            ApiConfig(request_timeout=True)

    @pytest.mark.parametrize("value", ["30", "30.0"])
    def test_rejects_non_numeric_request_timeout_aliases(self, value: object) -> None:
        with pytest.raises(ValueError, match=r"request_timeout: expected number, got"):
            ApiConfig(request_timeout=value)

    def test_rejects_boolean_port_alias(self) -> None:
        with pytest.raises(ValueError, match="port: expected integer, got bool"):
            ApiConfig(port=True)

    @pytest.mark.parametrize("value", ["8000", 8000.0])
    def test_rejects_non_integer_port_aliases(self, value: object) -> None:
        with pytest.raises(ValueError, match=r"port: expected integer, got"):
            ApiConfig(port=value)

    def test_empty_host_rejected(self) -> None:
        with pytest.raises(ValueError):
            ApiConfig(host="")

    def test_whitespace_only_host_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"host must not be blank"):
            ApiConfig(host="   ")

    def test_padded_host_is_trimmed(self) -> None:
        config = ApiConfig(host=" 127.0.0.1 ")
        assert config.host == "127.0.0.1"

    def test_port_conflict_with_metrics_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"metrics\.port.*must differ.*HTTP port"):
            ApiConfig(port=8000, metrics={"enabled": True, "port": 8000})

    def test_port_conflict_ignored_when_metrics_disabled(self) -> None:
        config = ApiConfig(port=8000, metrics={"enabled": False, "port": 8000})
        assert config.port == 8000

    def test_different_ports_accepted(self) -> None:
        config = ApiConfig(port=8080, metrics={"enabled": True, "port": 9090})
        assert config.port == 8080
        assert config.metrics.port == 9090

    @pytest.mark.parametrize("value", ["true", 1, 0])
    def test_metrics_enabled_aliases_rejected(self, value: object) -> None:
        with pytest.raises(ValueError, match=r"enabled: expected bool, got"):
            ApiConfig(metrics={"enabled": value})

    @pytest.mark.parametrize("value", ["9090", 9090.0, True])
    def test_metrics_port_aliases_rejected(self, value: object) -> None:
        with pytest.raises(ValueError, match=r"port: expected integer, got"):
            ApiConfig(metrics={"port": value})

    def test_internal_read_model_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"non-public API read models: service_state"):
            ApiConfig(read_models={"service_state": ReadModelPolicy(enabled=True)})


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

    def test_whitespace_is_trimmed_before_slash_normalization(self) -> None:
        assert ApiConfig(route_prefix=" /api/v2/ ").route_prefix == "/api/v2"

    def test_slash_only_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"route_prefix must not be empty"):
            ApiConfig(route_prefix="/")

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"route_prefix must not be empty"):
            ApiConfig(route_prefix="   ")


# ============================================================================
# App Construction
# ============================================================================


class TestApiBuildApp:
    def test_app_title_from_config(self, mock_brotr: Brotr, sample_catalog: Catalog) -> None:
        config = ApiConfig(
            title="LilBrotr API",
            read_models={"relays": ReadModelPolicy(enabled=True)},
        )
        service = Api(brotr=mock_brotr, config=config)
        service._read_core.catalog = sample_catalog
        app = service._build_app()
        assert app.title == "LilBrotr API"

    def test_app_title_uses_canonicalized_config(
        self, mock_brotr: Brotr, sample_catalog: Catalog
    ) -> None:
        config = ApiConfig(
            title="  LilBrotr API  ",
            read_models={"relays": ReadModelPolicy(enabled=True)},
        )
        service = Api(brotr=mock_brotr, config=config)
        service._read_core.catalog = sample_catalog
        app = service._build_app()
        assert app.title == "LilBrotr API"

    def test_app_title_default(self, api_service: Api) -> None:
        app = api_service._build_app()
        assert app.title == "BigBrotr API"

    def test_cors_middleware_added_with_origins(
        self, mock_brotr: Brotr, sample_catalog: Catalog
    ) -> None:
        config = ApiConfig(
            cors_origins=["https://example.com"],
            read_models={"relays": ReadModelPolicy(enabled=True)},
        )
        service = Api(brotr=mock_brotr, config=config)
        service._read_core.catalog = sample_catalog
        app = service._build_app()
        middleware_classes = [type(m).__name__ for m in app.user_middleware]
        assert "Middleware" in str(middleware_classes) or len(app.user_middleware) > 0

    def test_cors_middleware_uses_canonicalized_origins(
        self, mock_brotr: Brotr, sample_catalog: Catalog
    ) -> None:
        config = ApiConfig(
            cors_origins=[" https://example.com "],
            read_models={"relays": ReadModelPolicy(enabled=True)},
        )
        service = Api(brotr=mock_brotr, config=config)
        service._read_core.catalog = sample_catalog
        app = service._build_app()

        cors_middleware = next(
            middleware
            for middleware in app.user_middleware
            if "CORSMiddleware" in str(middleware.cls)
        )
        assert cors_middleware.kwargs["allow_origins"] == ["https://example.com"]

    def test_cors_middleware_uses_deduplicated_origins(
        self, mock_brotr: Brotr, sample_catalog: Catalog
    ) -> None:
        config = ApiConfig(
            cors_origins=[
                "https://example.com",
                " https://example.com ",
                "https://relay.example",
                "https://example.com",
            ],
            read_models={"relays": ReadModelPolicy(enabled=True)},
        )
        service = Api(brotr=mock_brotr, config=config)
        service._read_core.catalog = sample_catalog
        app = service._build_app()

        cors_middleware = next(
            middleware
            for middleware in app.user_middleware
            if "CORSMiddleware" in str(middleware.cls)
        )
        assert cors_middleware.kwargs["allow_origins"] == [
            "https://example.com",
            "https://relay.example",
        ]

    def test_no_cors_middleware_without_origins(self, api_service: Api) -> None:
        app = api_service._build_app()
        has_cors = any("CORSMiddleware" in str(m) for m in app.user_middleware)
        assert not has_cors

    def test_routes_use_custom_prefix(self, mock_brotr: Brotr, sample_catalog: Catalog) -> None:
        config = ApiConfig(
            interval=60.0,
            host="127.0.0.1",
            port=9999,
            route_prefix="/api/v2",
            read_models={"relays": ReadModelPolicy(enabled=True)},
        )
        service = Api(brotr=mock_brotr, config=config)
        service._read_core.catalog = sample_catalog
        client = TestClient(service._build_app())

        assert client.get("/api/v2/read-models").status_code == 200
        assert client.get("/api/v2/relays").status_code == 200
        assert client.get("/v1/read-models").status_code in (404, 405)

    def test_routes_use_canonicalized_custom_prefix(
        self, mock_brotr: Brotr, sample_catalog: Catalog
    ) -> None:
        config = ApiConfig(
            route_prefix=" /api/v2/ ",
            read_models={"relays": ReadModelPolicy(enabled=True)},
        )
        service = Api(brotr=mock_brotr, config=config)
        service._read_core.catalog = sample_catalog
        client = TestClient(service._build_app())

        assert client.get("/api/v2/read-models").status_code == 200
        assert client.get("/api/v2/relays").status_code == 200

    def test_composite_pk_route_generated(
        self, mock_brotr: Brotr, composite_pk_catalog: Catalog
    ) -> None:
        config = ApiConfig(read_models={"relay-document-history": ReadModelPolicy(enabled=True)})
        service = Api(brotr=mock_brotr, config=config)
        service._read_core.catalog = composite_pk_catalog
        app = service._build_app()
        paths = [r.path for r in app.routes]
        assert any("relay_url" in p and "document_id" in p and "role" in p for p in paths)

    def test_disabled_read_model_not_routed(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/service_state")
        assert resp.status_code in (404, 405)

    def test_configured_internal_read_model_still_not_routed(
        self, mock_brotr: Brotr, sample_catalog: Catalog
    ) -> None:
        with pytest.raises(ValueError, match=r"non-public API read models: service_state"):
            ApiConfig(
                read_models={
                    "relays": ReadModelPolicy(enabled=True),
                    "service_state": ReadModelPolicy(enabled=True),
                }
            )

    def test_view_has_no_pk_route(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/relay-stats/something")
        assert resp.status_code in (404, 405)

    def test_enabled_read_model_names_follow_registry(self, api_service: Api) -> None:
        assert api_service._read_core.enabled_resource_ids("api") == ["relay-stats", "relays"]


# ============================================================================
# Route Tests — Health & Schema
# ============================================================================


class TestHealthRoute:
    def test_returns_ok(self, test_client: TestClient) -> None:
        resp = test_client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestReadModelRoutes:
    def test_list_read_models(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/read-models")
        assert resp.status_code == 200
        data = resp.json()["data"]
        names = [t["id"] for t in data]
        assert "relays" in names
        assert "relay-stats" in names
        assert "service_state" not in names
        relay = next(item for item in data if item["id"] == "relays")
        assert relay["path"] == "/v1/relays"
        assert relay["field_count"] == 2
        assert relay["default_pagination_mode"] == "cursor"
        assert relay["supports_identity_lookup"] is True
        assert relay["supports_cursor_pagination"] is True

        relay_stats = next(item for item in data if item["id"] == "relay-stats")
        assert relay_stats["default_pagination_mode"] == "offset"
        assert relay_stats["supports_identity_lookup"] is False
        assert relay_stats["supports_cursor_pagination"] is False

    def test_read_model_detail(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/read-models/relays")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["id"] == "relays"
        assert data["path"] == "/v1/relays"
        assert len(data["fields"]) == 2
        assert data["identity_fields"] == ["url"]
        assert data["pagination"] == {
            "default_mode": "cursor",
            "supports_cursor": True,
            "supports_offset": True,
            "supports_total_opt_in": True,
            "cursor_param": "cursor",
            "meta_cursor_field": "next_cursor",
        }

    @pytest.mark.parametrize("read_model", ["service_state", "nonexistent"])
    def test_read_model_detail_not_found(self, test_client: TestClient, read_model: str) -> None:
        resp = test_client.get(f"/v1/read-models/{read_model}")
        assert resp.status_code == 404


# ============================================================================
# Route Tests — Read Model Data
# ============================================================================


class TestListRowsRoute:
    def test_success(self, test_client: TestClient, api_service: Api) -> None:
        mock_result = QueryResult(
            rows=[{"url": "wss://relay.example.com", "network": "clearnet"}],
            total=None,
            limit=10,
            offset=0,
            next_cursor="opaque-token",
        )
        with patch.object(
            api_service._read_core.catalog,
            "query",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = test_client.get("/v1/relays?limit=10")

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == [{"url": "wss://relay.example.com", "network": "clearnet"}]
        assert "total" not in body["meta"]
        assert body["meta"]["next_cursor"] == "opaque-token"
        assert body["meta"]["read_model"] == "relays"

    def test_legacy_alias_path_is_not_exposed(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/relay?limit=10")

        assert resp.status_code == 404

    def test_include_total_param(self, test_client: TestClient, api_service: Api) -> None:
        mock_result = QueryResult(rows=[], total=5, limit=10, offset=0)
        with patch.object(
            api_service._read_core.catalog,
            "query",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_query:
            resp = test_client.get("/v1/relays?include_total=true")

        assert resp.status_code == 200
        _, kwargs = mock_query.call_args
        assert kwargs["include_total"] is True
        assert resp.json()["meta"]["total"] == 5

    def test_with_sort_param(self, test_client: TestClient, api_service: Api) -> None:
        mock_result = QueryResult(rows=[], total=None, limit=10, offset=0)
        with patch.object(
            api_service._read_core.catalog,
            "query",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_query:
            resp = test_client.get("/v1/relays?sort=url:asc")

        assert resp.status_code == 200
        _, kwargs = mock_query.call_args
        assert kwargs["sort"] == "url:asc"
        assert kwargs["include_total"] is False
        assert kwargs["cursor"] is None

    def test_blank_sort_param_is_treated_as_absent(
        self,
        test_client: TestClient,
        api_service: Api,
    ) -> None:
        mock_result = QueryResult(rows=[], total=None, limit=10, offset=0)
        with patch.object(
            api_service._read_core.catalog,
            "query",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_query:
            resp = test_client.get("/v1/relays?sort=%20%20%20")

        assert resp.status_code == 200
        _, kwargs = mock_query.call_args
        assert kwargs["sort"] is None

    def test_with_cursor_param(self, test_client: TestClient, api_service: Api) -> None:
        mock_result = QueryResult(rows=[], total=None, limit=10, offset=0)
        with patch.object(
            api_service._read_core.catalog,
            "query",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_query:
            resp = test_client.get("/v1/relays?cursor=opaque-token")

        assert resp.status_code == 200
        _, kwargs = mock_query.call_args
        assert kwargs["cursor"] == "opaque-token"

    def test_cursor_and_offset_returns_400(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/relays?cursor=opaque-token&offset=1")
        assert resp.status_code == 400
        assert "cursor pagination" in resp.json()["error"].lower()

    def test_catalog_error_returns_400(self, test_client: TestClient, api_service: Api) -> None:
        with patch.object(
            api_service._read_core.catalog,
            "query",
            new_callable=AsyncMock,
            side_effect=CatalogError("Unknown column: bad"),
        ) as mock_query:
            resp = test_client.get("/v1/relays?bad=value")
        assert resp.status_code == 400
        assert resp.json()["error"] == "Unsupported filter fields for relays: bad"
        mock_query.assert_not_awaited()

    def test_whitespace_padded_filter_key_is_normalized(
        self,
        test_client: TestClient,
        api_service: Api,
    ) -> None:
        mock_result = QueryResult(rows=[], total=None, limit=10, offset=0)
        with patch.object(
            api_service._read_core.catalog,
            "query",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_query:
            resp = test_client.get("/v1/relays?%20network%20=%20clearnet%20")

        assert resp.status_code == 200
        _, kwargs = mock_query.call_args
        assert kwargs["filters"] == {"network": "clearnet"}

    def test_whitespace_padded_reserved_keys_are_normalized(
        self,
        test_client: TestClient,
        api_service: Api,
    ) -> None:
        mock_result = QueryResult(rows=[], total=1, limit=5, offset=0)
        with patch.object(
            api_service._read_core.catalog,
            "query",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_query:
            resp = test_client.get(
                "/v1/relays?%20limit%20=5&%20sort%20=%20url:asc%20&%20include_total%20=%20true%20"
            )

        assert resp.status_code == 200
        _, kwargs = mock_query.call_args
        assert kwargs["limit"] == 5
        assert kwargs["sort"] == "url:asc"
        assert kwargs["include_total"] is True
        assert kwargs["filters"] is None

    def test_duplicate_transport_reserved_key_returns_400(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/relays?limit=5&limit=10")
        assert resp.status_code == 400
        assert resp.json()["error"] == "Invalid query parameter"

    def test_duplicate_transport_filter_key_returns_400(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/relays?network=clearnet&network=tor")
        assert resp.status_code == 400
        assert resp.json()["error"] == "Invalid query parameter"

    def test_blank_filter_key_returns_400(self, test_client: TestClient) -> None:
        resp = test_client.get("/v1/relays?%20%20=clearnet")
        assert resp.status_code == 400
        assert resp.json()["error"] == "Invalid filter field"

    @pytest.mark.parametrize(
        "params",
        [
            "limit=not_a_number",
            "offset=abc",
            "limit=0",
            "limit=-1",
            "limit=1001",
            "offset=-1",
            "offset=100001",
        ],
        ids=[
            "invalid_limit",
            "invalid_offset",
            "zero_limit",
            "negative_limit",
            "limit_above_max_page_size",
            "negative_offset",
            "offset_above_max",
        ],
    )
    def test_invalid_pagination_returns_400(self, test_client: TestClient, params: str) -> None:
        resp = test_client.get(f"/v1/relays?{params}")
        assert resp.status_code == 400
        assert "Invalid limit" in resp.json()["error"]


class TestGetRowRoute:
    def test_success(self, test_client: TestClient, api_service: Api) -> None:
        mock_row = {"url": "wss://relay.example.com", "network": "clearnet"}
        with patch.object(
            api_service._read_core.catalog,
            "get_by_pk",
            new_callable=AsyncMock,
            return_value=mock_row,
        ):
            resp = test_client.get("/v1/relays/wss://relay.example.com")

        assert resp.status_code == 200
        assert resp.json()["data"] == mock_row

    def test_not_found(self, test_client: TestClient, api_service: Api) -> None:
        with patch.object(
            api_service._read_core.catalog,
            "get_by_pk",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = test_client.get("/v1/relays/wss://nonexistent")
        assert resp.status_code == 404

    def test_value_error_returns_400(self, test_client: TestClient, api_service: Api) -> None:
        with patch.object(
            api_service._read_core.catalog,
            "get_by_pk",
            new_callable=AsyncMock,
            side_effect=ValueError("bad pk"),
        ):
            resp = test_client.get("/v1/relays/wss://bad")
        assert resp.status_code == 400
        assert "Invalid request" in resp.json()["error"]

    def test_catalog_error_returns_400(self, test_client: TestClient, api_service: Api) -> None:
        with patch.object(
            api_service._read_core.catalog,
            "get_by_pk",
            new_callable=AsyncMock,
            side_effect=CatalogError("type cast failed"),
        ):
            resp = test_client.get("/v1/relays/wss://bad")
        assert resp.status_code == 400
        assert "type cast failed" in resp.json()["error"]


# ============================================================================
# Middleware Tests
# ============================================================================


class TestRequestMiddleware:
    def test_successful_request_increments_total(
        self, test_client: TestClient, api_service: Api
    ) -> None:
        test_client.get("/health")
        assert api_service._requests_total == 1
        assert api_service._requests_failed == 0

    def test_error_request_increments_failed(
        self, test_client: TestClient, api_service: Api
    ) -> None:
        test_client.get("/v1/read-models/nonexistent")
        assert api_service._requests_total == 1
        assert api_service._requests_failed == 1

    def test_unhandled_exception_returns_json_500(
        self,
        test_client: TestClient,
        api_service: Api,
    ) -> None:
        with patch.object(
            api_service._read_core.catalog,
            "query",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected DB failure"),
        ):
            resp = test_client.get("/v1/relays?limit=10")

        assert resp.status_code == 500
        assert resp.json()["error"] == "Internal server error"
        assert api_service._requests_failed == 1


# ============================================================================
# Service Init & Constants
# ============================================================================


class TestApiInit:
    def test_service_name(self) -> None:
        assert Api.SERVICE_NAME == ServiceName.API

    def test_config_class(self) -> None:
        assert Api.CONFIG_CLASS is ApiConfig

    def test_init_state(self, api_service: Api) -> None:
        assert api_service._requests_total == 0
        assert api_service._requests_failed == 0
        assert api_service._server_task is None

    async def test_cleanup_returns_zero(self, api_service: Api) -> None:
        assert await api_service.cleanup() == 0


# ============================================================================
# Lifecycle Tests
# ============================================================================


class TestApiLifecycle:
    async def test_aenter_starts_server_task(self, api_service: Api) -> None:
        server = MagicMock()
        server.started = True
        server.serve = AsyncMock()

        with (
            patch.object(type(api_service._read_core), "discover", new_callable=AsyncMock),
            patch("bigbrotr.services.api.service.uvicorn.Server", return_value=server),
        ):
            async with api_service:
                assert api_service._server_task is not None
                await asyncio.sleep(0)
                server.serve.assert_awaited_once()
                assert api_service._server is server

    async def test_aexit_cancels_server_task(self, api_service: Api) -> None:
        server = MagicMock()
        server.started = True
        server.serve = AsyncMock()

        with (
            patch.object(type(api_service._read_core), "discover", new_callable=AsyncMock),
            patch("bigbrotr.services.api.service.uvicorn.Server", return_value=server),
        ):
            async with api_service:
                assert api_service._server_task is not None
            assert api_service._server_task is None
            assert api_service._server is None

    async def test_aexit_with_no_server_task(self, api_service: Api) -> None:
        server = MagicMock()
        server.started = True
        server.serve = AsyncMock()

        with (
            patch.object(type(api_service._read_core), "discover", new_callable=AsyncMock),
            patch("bigbrotr.services.api.service.uvicorn.Server", return_value=server),
        ):
            async with api_service:
                api_service._server_task = None

    async def test_aenter_propagates_immediate_server_startup_failure(
        self, api_service: Api
    ) -> None:
        server = MagicMock()
        server.started = False
        server.serve = AsyncMock(side_effect=OSError("bind failed"))

        with (
            patch.object(type(api_service._read_core), "discover", new_callable=AsyncMock),
            patch("bigbrotr.services.api.service.uvicorn.Server", return_value=server),
            pytest.raises(RuntimeError, match="HTTP server task has stopped unexpectedly"),
        ):
            await api_service.__aenter__()

        assert api_service._server_task is None
        assert api_service._server is None

    async def test_aenter_logs_http_server_started_only_after_success(
        self, api_service: Api
    ) -> None:
        server = MagicMock()
        server.started = True
        server.serve = AsyncMock()

        with (
            patch.object(type(api_service._read_core), "discover", new_callable=AsyncMock),
            patch("bigbrotr.services.api.service.uvicorn.Server", return_value=server),
            patch.object(api_service._logger, "info") as mock_info,
        ):
            async with api_service:
                await asyncio.sleep(0)

        http_started_calls = [
            call for call in mock_info.call_args_list if call.args[0] == "http_server_started"
        ]
        assert len(http_started_calls) == 1


# ============================================================================
# Run Cycle Tests
# ============================================================================


class TestApiRun:
    async def test_reports_metrics(self, api_service: Api) -> None:
        api_service._requests_total = 42
        api_service._requests_failed = 3

        with (
            patch.object(api_service, "inc_counter") as mock_counter,
            patch.object(api_service, "set_gauge") as mock_gauge,
        ):
            await api_service.run()

        mock_counter.assert_any_call("requests_total", 42)
        mock_counter.assert_any_call("requests_failed", 3)
        mock_gauge.assert_any_call("readable_resources_exposed", 2)

    async def test_resets_counters(self, api_service: Api) -> None:
        api_service._requests_total = 10
        api_service._requests_failed = 2

        with patch.object(api_service, "inc_counter"), patch.object(api_service, "set_gauge"):
            await api_service.run()

        assert api_service._requests_total == 0
        assert api_service._requests_failed == 0

    async def test_detects_crashed_server_task(self, api_service: Api) -> None:
        failed_task = MagicMock(spec=asyncio.Task)
        failed_task.done.return_value = True
        failed_task.cancelled.return_value = False
        failed_task.exception.return_value = OSError("bind failed")
        api_service._server_task = failed_task

        with pytest.raises(RuntimeError, match="HTTP server task has stopped unexpectedly"):
            await api_service.run()

    async def test_detects_cancelled_server_task(self, api_service: Api) -> None:
        cancelled_task = MagicMock(spec=asyncio.Task)
        cancelled_task.done.return_value = True
        cancelled_task.cancelled.return_value = True
        api_service._server_task = cancelled_task

        with pytest.raises(RuntimeError, match="HTTP server task has stopped unexpectedly"):
            await api_service.run()

    async def test_ok_when_server_task_running(self, api_service: Api) -> None:
        running_task = MagicMock(spec=asyncio.Task)
        running_task.done.return_value = False
        api_service._server_task = running_task

        with patch.object(api_service, "inc_counter"), patch.object(api_service, "set_gauge"):
            await api_service.run()

    async def test_ok_when_server_task_none(self, api_service: Api) -> None:
        api_service._server_task = None

        with patch.object(api_service, "inc_counter"), patch.object(api_service, "set_gauge"):
            await api_service.run()
