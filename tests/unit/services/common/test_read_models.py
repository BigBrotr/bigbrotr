from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.core.yaml import load_yaml
from bigbrotr.services.common.catalog import (
    Catalog,
    CatalogError,
    ColumnSchema,
    QueryResult,
    TableSchema,
)
from bigbrotr.services.common.configs import ReadModelPolicy
from bigbrotr.services.common.read_models import (
    READABLE_RESOURCE_REGISTRY,
    ReadableResourceEntry,
    ReadableResourceNotFoundError,
    ReadCore,
    ReadCoreError,
    ReadModelQuery,
    ReadModelQueryError,
    build_read_model_meta,
    normalize_readable_resource_policies,
    parse_read_model_filter_string,
    read_model_query_from_http_params,
    read_model_query_from_job_params,
    readable_resources_for_surface,
    resolve_surface_readable_resource,
    resolve_surface_readable_resource_names,
    resolve_surface_readable_resources,
)


def _configured_read_models(path: Path) -> set[str]:
    config = load_yaml(str(path))
    return set(config.get("read_models", {}))


class TestReadableResourceRegistry:
    def test_registry_entries_are_readable_resource_entry(self) -> None:
        for entry in READABLE_RESOURCE_REGISTRY.values():
            assert isinstance(entry, ReadableResourceEntry)

    def test_all_entries_are_catalog_compatible_resources(self) -> None:
        for resource_id, entry in READABLE_RESOURCE_REGISTRY.items():
            assert entry.resource_id == resource_id
            assert entry.relation_name == entry.catalog_name
            assert entry.surfaces

    def test_registry_covers_all_configured_api_read_models(self) -> None:
        api_configs = (
            Path("deployments/bigbrotr/config/services/api.yaml"),
            Path("deployments/lilbrotr/config/services/api.yaml"),
        )

        configured = set().union(*(_configured_read_models(path) for path in api_configs))

        assert configured <= set(READABLE_RESOURCE_REGISTRY)

    def test_registry_covers_all_configured_dvm_read_models(self) -> None:
        dvm_configs = (
            Path("deployments/bigbrotr/config/services/dvm.yaml"),
            Path("deployments/lilbrotr/config/services/dvm.yaml"),
        )

        configured = set().union(*(_configured_read_models(path) for path in dvm_configs))

        assert configured <= set(READABLE_RESOURCE_REGISTRY)

    def test_api_surface_matches_configured_api_read_models(self) -> None:
        api_configs = (
            Path("deployments/bigbrotr/config/services/api.yaml"),
            Path("deployments/lilbrotr/config/services/api.yaml"),
        )

        expected = set().union(*(_configured_read_models(path) for path in api_configs))

        assert set(readable_resources_for_surface("api")) == expected

    def test_dvm_surface_matches_configured_dvm_read_models(self) -> None:
        dvm_configs = (
            Path("deployments/bigbrotr/config/services/dvm.yaml"),
            Path("deployments/lilbrotr/config/services/dvm.yaml"),
        )

        expected = set().union(*(_configured_read_models(path) for path in dvm_configs))

        assert set(readable_resources_for_surface("dvm")) == expected

    def test_internal_state_tables_are_not_public_read_models(self) -> None:
        assert "service_state" not in READABLE_RESOURCE_REGISTRY

    def test_resolve_surface_readable_resources_filters_by_config_and_catalog(self) -> None:
        enabled = resolve_surface_readable_resources(
            "api",
            policies={
                "relays": ReadModelPolicy(enabled=True),
                "documents": ReadModelPolicy(enabled=True),
            },
            available_catalog_names={"relay", "event"},
        )

        assert set(enabled) == {"relays"}

    def test_resolve_surface_readable_resources_filters_disabled_and_missing_catalog_entries(
        self,
    ) -> None:
        resolved = resolve_surface_readable_resources(
            "api",
            policies={
                "relays": ReadModelPolicy(enabled=True),
                "events": ReadModelPolicy(enabled=False),
                "documents": ReadModelPolicy(enabled=True),
            },
            available_catalog_names={"relay"},
        )

        assert set(resolved) == {"relays"}

    def test_resolve_surface_readable_resource_names_returns_stable_sorted_ids(self) -> None:
        resolved = resolve_surface_readable_resource_names(
            "dvm",
            policies={
                "events": ReadModelPolicy(enabled=True),
                "relays": ReadModelPolicy(enabled=True),
            },
            available_catalog_names={"relay", "event"},
        )

        assert resolved == ["events", "relays"]

    def test_resolve_surface_readable_resource_filters_out_missing_catalog_entries(self) -> None:
        resolved = resolve_surface_readable_resource(
            "dvm",
            name="relays",
            policies={"relays": ReadModelPolicy(enabled=True)},
            available_catalog_names={"event"},
        )

        assert resolved is None

    def test_entry_schema_uses_catalog_name(self) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay": TableSchema(
                name="relay",
                columns=(ColumnSchema(name="url", pg_type="text", nullable=False),),
                primary_key=("url",),
                is_view=False,
            )
        }

        entry = READABLE_RESOURCE_REGISTRY["relays"]

        assert entry.schema(catalog) == catalog.tables["relay"]

    async def test_entry_query_delegates_to_catalog(self) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay": TableSchema(
                name="relay",
                columns=(ColumnSchema(name="url", pg_type="text", nullable=False),),
                primary_key=("url",),
                is_view=False,
            )
        }
        expected = QueryResult(
            rows=[{"url": "wss://relay.example.com"}], total=1, limit=5, offset=0
        )
        catalog.query = AsyncMock(return_value=expected)  # type: ignore[method-assign]
        brotr = object()

        entry = READABLE_RESOURCE_REGISTRY["relays"]
        request = ReadModelQuery(limit=5, offset=0, max_page_size=50, filters={"url": "foo"})

        result = await entry.query(brotr, catalog, request)

        assert result == expected
        catalog.query.assert_awaited_once_with(  # type: ignore[attr-defined]
            brotr,
            "relay",
            limit=5,
            offset=0,
            max_page_size=50,
            filters={"url": "foo"},
            sort=None,
            include_total=False,
            cursor=None,
            prefer_keyset=True,
        )

    async def test_entry_get_by_pk_delegates_to_catalog(self) -> None:
        catalog = Catalog()
        expected = {"url": "wss://relay.example.com"}
        catalog.get_by_pk = AsyncMock(return_value=expected)  # type: ignore[method-assign]
        brotr = object()

        entry = READABLE_RESOURCE_REGISTRY["relays"]
        pk_values = {"url": "wss://relay.example.com"}

        result = await entry.get_by_pk(brotr, catalog, pk_values)

        assert result == expected
        catalog.get_by_pk.assert_awaited_once_with(  # type: ignore[attr-defined]
            brotr,
            "relay",
            pk_values,
        )

    async def test_entry_delegates_to_custom_handlers(self) -> None:
        schema = TableSchema(
            name="custom",
            columns=(ColumnSchema(name="id", pg_type="text", nullable=False),),
            primary_key=("id",),
            is_view=False,
        )
        expected_result = QueryResult(rows=[{"id": "row-1"}], total=1, limit=1, offset=0)
        expected_row = {"id": "row-1"}
        schema_handler = MagicMock(return_value=schema)
        query_handler = AsyncMock(return_value=expected_result)
        get_by_pk_handler = AsyncMock(return_value=expected_row)
        entry = ReadableResourceEntry(
            resource_id="custom",
            catalog_name="ignored",
            schema_handler=schema_handler,
            query_handler=query_handler,
            get_by_pk_handler=get_by_pk_handler,
        )
        catalog = Catalog()
        brotr = object()
        request = ReadModelQuery(limit=1, offset=0)
        pk_values = {"id": "row-1"}

        assert entry.schema(catalog) == schema
        assert await entry.query(brotr, catalog, request) == expected_result
        assert await entry.get_by_pk(brotr, catalog, pk_values) == expected_row

        schema_handler.assert_called_once_with(catalog, entry)
        query_handler.assert_awaited_once_with(brotr, catalog, entry, request)
        get_by_pk_handler.assert_awaited_once_with(brotr, catalog, entry, pk_values)

    def test_entry_summary_uses_registered_backend_schema(self) -> None:
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
            )
        }

        summary = READABLE_RESOURCE_REGISTRY["relays"].summary(catalog=catalog, route_prefix="/v1")

        assert summary == {
            "id": "relays",
            "path": "/v1/relays",
            "field_count": 2,
            "supports_identity_lookup": True,
            "default_pagination_mode": "cursor",
            "supports_cursor_pagination": True,
        }

    def test_entry_contract_exposes_readable_resource_descriptor(self) -> None:
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
            )
        }

        contract = READABLE_RESOURCE_REGISTRY["relays"].contract(catalog)

        assert contract == {
            "id": "relays",
            "name": "Relays",
            "backing_kind": "relation",
            "relation_name": "relay",
            "identity_fields": ["url"],
            "default_traversal_order": ["url:asc"],
            "cursor_key_fields": ["url"],
            "allowed_filters": ["url", "network"],
            "allowed_sorts": ["url", "network"],
            "pagination": {
                "default_mode": "cursor",
                "supports_cursor": True,
                "supports_offset": True,
                "supports_total_opt_in": True,
                "cursor_param": "cursor",
                "meta_cursor_field": "next_cursor",
            },
        }

    def test_entry_contract_omits_traversal_fields_without_cursor_contract(self) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay_stats": TableSchema(
                name="relay_stats",
                columns=(
                    ColumnSchema(name="url", pg_type="text", nullable=False),
                    ColumnSchema(name="event_count", pg_type="bigint", nullable=False),
                ),
                primary_key=(),
                is_view=True,
            )
        }

        contract = READABLE_RESOURCE_REGISTRY["relay-stats"].contract(catalog)

        assert contract == {
            "id": "relay-stats",
            "name": "Relay stats",
            "backing_kind": "relation",
            "relation_name": "relay_stats",
            "identity_fields": [],
            "default_traversal_order": None,
            "cursor_key_fields": None,
            "allowed_filters": ["url", "event_count"],
            "allowed_sorts": ["url", "event_count"],
            "pagination": {
                "default_mode": "offset",
                "supports_cursor": False,
                "supports_offset": True,
                "supports_total_opt_in": True,
                "cursor_param": None,
                "meta_cursor_field": None,
            },
        }

    def test_entry_detail_uses_registered_backend_schema(self) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay_stats": TableSchema(
                name="relay_stats",
                columns=(ColumnSchema(name="url", pg_type="text", nullable=False),),
                primary_key=(),
                is_view=True,
            )
        }

        detail = READABLE_RESOURCE_REGISTRY["relay-stats"].detail(
            catalog=catalog,
            route_prefix="/v1",
        )

        assert detail == {
            "id": "relay-stats",
            "path": "/v1/relay-stats",
            "fields": [{"name": "url", "type": "text", "nullable": False}],
            "identity_fields": [],
            "pagination": {
                "default_mode": "offset",
                "supports_cursor": False,
                "supports_offset": True,
                "supports_total_opt_in": True,
                "cursor_param": None,
                "meta_cursor_field": None,
            },
        }


class TestReadCore:
    def _core(
        self,
        *,
        policies: dict[str, ReadModelPolicy] | None = None,
        catalog: Catalog | None = None,
    ) -> ReadCore:
        core = ReadCore(policy_source=lambda: policies or {})
        if catalog is not None:
            core.catalog = catalog
        return core

    def test_init_creates_empty_catalog(self) -> None:
        core = self._core()

        assert isinstance(core.catalog, Catalog)
        assert core.catalog.tables == {}

    async def test_discover_uses_catalog_and_logs_shape(self) -> None:
        core = self._core()
        catalog = MagicMock()
        catalog.discover = AsyncMock()
        table = MagicMock(is_view=False)
        view = MagicMock(is_view=True)
        catalog.tables.values.return_value = [table, table, view]
        core.catalog = catalog
        logger = MagicMock()
        brotr = MagicMock()

        await core.discover(brotr, logger=logger)

        catalog.discover.assert_awaited_once_with(brotr)
        logger.info.assert_called_once_with("schema_discovered", tables=2, views=1)

    def test_enabled_resource_ids_follow_catalog_and_policy(self) -> None:
        catalog = Catalog()
        catalog._tables = {"relay": MagicMock(), "event": MagicMock()}
        core = self._core(
            policies={
                "relays": ReadModelPolicy(enabled=True),
                "events": ReadModelPolicy(enabled=False),
            },
            catalog=catalog,
        )

        assert core.enabled_resource_ids("api") == ["relays"]

    def test_enabled_resources_follow_catalog_and_policy(self) -> None:
        catalog = Catalog()
        catalog._tables = {"relay": MagicMock(), "event": MagicMock()}
        core = self._core(
            policies={
                "relays": ReadModelPolicy(enabled=True),
                "events": ReadModelPolicy(enabled=False),
            },
            catalog=catalog,
        )

        assert set(core.enabled_resources("api")) == {"relays"}

    def test_require_resource_returns_enabled_resource(self) -> None:
        catalog = Catalog()
        catalog._tables = {"relay": MagicMock()}
        core = self._core(
            policies={"relays": ReadModelPolicy(enabled=True)},
            catalog=catalog,
        )

        resource = core.require_resource("api", "relays")

        assert resource is READABLE_RESOURCE_REGISTRY["relays"]

    def test_require_resource_raises_normalized_error_for_missing_resource(self) -> None:
        catalog = Catalog()
        catalog._tables = {"relay": MagicMock()}
        core = self._core(
            policies={"relays": ReadModelPolicy(enabled=True)},
            catalog=catalog,
        )

        with pytest.raises(ReadableResourceNotFoundError, match="Invalid or disabled readable"):
            core.require_resource("api", "events")

    def test_resource_not_found_error_is_read_core_error(self) -> None:
        assert issubclass(ReadableResourceNotFoundError, ReadCoreError)

    async def test_query_resource_uses_catalog_context(self) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay": TableSchema(
                name="relay",
                columns=(ColumnSchema(name="url", pg_type="text", nullable=False),),
                primary_key=("url",),
                is_view=False,
            )
        }
        request = ReadModelQuery(limit=10, offset=0)
        result = MagicMock()
        catalog.query = AsyncMock(return_value=result)  # type: ignore[method-assign]
        brotr = MagicMock()
        core = self._core(catalog=catalog)
        resource = ReadableResourceEntry(
            resource_id="relays",
            catalog_name="relay",
        )

        resolved = await core.query_resource(brotr, resource, request)

        assert resolved is result
        catalog.query.assert_awaited_once_with(  # type: ignore[attr-defined]
            brotr,
            "relay",
            limit=10,
            offset=0,
            max_page_size=1000,
            filters=None,
            sort=None,
            include_total=False,
            cursor=None,
            prefer_keyset=True,
        )

    async def test_query_resource_uses_offset_only_contract_when_cursor_is_not_supported(
        self,
    ) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay_stats": TableSchema(
                name="relay_stats",
                columns=(
                    ColumnSchema(name="url", pg_type="text", nullable=False),
                    ColumnSchema(name="event_count", pg_type="bigint", nullable=False),
                ),
                primary_key=(),
                is_view=True,
            )
        }
        result = MagicMock()
        catalog.query = AsyncMock(return_value=result)  # type: ignore[method-assign]
        brotr = MagicMock()
        core = self._core(catalog=catalog)
        resource = ReadableResourceEntry(
            resource_id="relay-stats",
            catalog_name="relay_stats",
        )

        resolved = await core.query_resource(
            brotr,
            resource,
            ReadModelQuery(limit=10, offset=5, include_total=True),
        )

        assert resolved is result
        catalog.query.assert_awaited_once_with(  # type: ignore[attr-defined]
            brotr,
            "relay_stats",
            limit=10,
            offset=5,
            max_page_size=1000,
            filters=None,
            sort=None,
            include_total=True,
            cursor=None,
            prefer_keyset=False,
        )

    async def test_query_resource_rejects_cursor_when_resource_is_offset_only(self) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay_stats": TableSchema(
                name="relay_stats",
                columns=(ColumnSchema(name="url", pg_type="text", nullable=False),),
                primary_key=(),
                is_view=True,
            )
        }
        catalog.query = AsyncMock()  # type: ignore[method-assign]
        core = self._core(catalog=catalog)
        resource = ReadableResourceEntry(
            resource_id="relay-stats",
            catalog_name="relay_stats",
        )

        with pytest.raises(CatalogError, match="Cursor pagination is not supported"):
            await core.query_resource(
                MagicMock(),
                resource,
                ReadModelQuery(limit=10, offset=0, cursor="opaque-token"),
            )

        catalog.query.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_query_resource_rejects_offset_when_resource_disables_it(self) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay": TableSchema(
                name="relay",
                columns=(ColumnSchema(name="url", pg_type="text", nullable=False),),
                primary_key=("url",),
                is_view=False,
            )
        }
        catalog.query = AsyncMock()  # type: ignore[method-assign]
        core = self._core(catalog=catalog)
        resource = ReadableResourceEntry(
            resource_id="relays",
            catalog_name="relay",
            supports_offset_pagination=False,
        )

        with pytest.raises(CatalogError, match="Offset pagination is not supported"):
            await core.query_resource(
                MagicMock(),
                resource,
                ReadModelQuery(limit=10, offset=1),
            )

        catalog.query.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_query_resource_rejects_include_total_when_resource_disables_it(self) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay": TableSchema(
                name="relay",
                columns=(ColumnSchema(name="url", pg_type="text", nullable=False),),
                primary_key=("url",),
                is_view=False,
            )
        }
        catalog.query = AsyncMock()  # type: ignore[method-assign]
        core = self._core(catalog=catalog)
        resource = ReadableResourceEntry(
            resource_id="relays",
            catalog_name="relay",
            supports_total_opt_in=False,
        )

        with pytest.raises(CatalogError, match="include_total is not supported"):
            await core.query_resource(
                MagicMock(),
                resource,
                ReadModelQuery(limit=10, offset=0, include_total=True),
            )

        catalog.query.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_query_resource_rejects_unsupported_filter_fields(self) -> None:
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
            )
        }
        catalog.query = AsyncMock()  # type: ignore[method-assign]
        core = self._core(catalog=catalog)
        resource = ReadableResourceEntry(
            resource_id="relays",
            catalog_name="relay",
            allowed_filters=("network",),
        )

        with pytest.raises(CatalogError, match="Unsupported filter fields for relays: url"):
            await core.query_resource(
                MagicMock(),
                resource,
                ReadModelQuery(limit=10, offset=0, filters={"url": "wss://relay.example.com"}),
            )

        catalog.query.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_query_resource_rejects_unsupported_sort_fields(self) -> None:
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
            )
        }
        catalog.query = AsyncMock()  # type: ignore[method-assign]
        core = self._core(catalog=catalog)
        resource = ReadableResourceEntry(
            resource_id="relays",
            catalog_name="relay",
            allowed_sorts=("network",),
        )

        with pytest.raises(CatalogError, match="Unsupported sort field for relays: url"):
            await core.query_resource(
                MagicMock(),
                resource,
                ReadModelQuery(limit=10, offset=0, sort="url:desc"),
            )

        catalog.query.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_query_resource_applies_resource_max_page_size(self) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay": TableSchema(
                name="relay",
                columns=(ColumnSchema(name="url", pg_type="text", nullable=False),),
                primary_key=("url",),
                is_view=False,
            )
        }
        request = ReadModelQuery(limit=50, offset=0, max_page_size=1000)
        result = MagicMock()
        catalog.query = AsyncMock(return_value=result)  # type: ignore[method-assign]
        brotr = MagicMock()
        core = self._core(catalog=catalog)
        resource = ReadableResourceEntry(
            resource_id="relays",
            catalog_name="relay",
            max_page_size=25,
        )

        resolved = await core.query_resource(brotr, resource, request)

        assert resolved is result
        catalog.query.assert_awaited_once_with(  # type: ignore[attr-defined]
            brotr,
            "relay",
            limit=50,
            offset=0,
            max_page_size=25,
            filters=None,
            sort=None,
            include_total=False,
            cursor=None,
            prefer_keyset=True,
        )

    async def test_get_resource_by_pk_uses_catalog_context(self) -> None:
        catalog = Catalog()
        row = {"url": "wss://relay.example.com"}
        catalog.get_by_pk = AsyncMock(return_value=row)  # type: ignore[method-assign]
        brotr = MagicMock()
        core = self._core(catalog=catalog)
        resource = ReadableResourceEntry(
            resource_id="relays",
            catalog_name="relay",
        )

        resolved = await core.get_resource_by_pk(brotr, resource, {"url": row["url"]})

        assert resolved == row
        catalog.get_by_pk.assert_awaited_once_with(  # type: ignore[attr-defined]
            brotr,
            "relay",
            {"url": row["url"]},
        )

    def test_build_resource_summaries_and_detail_use_enabled_surface(self) -> None:
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
            )
        }
        core = self._core(
            policies={"relays": ReadModelPolicy(enabled=True)},
            catalog=catalog,
        )

        summaries = core.build_resource_summaries("api", route_prefix="/v1")
        detail = core.build_resource_detail("api", "relays", route_prefix="/v1")

        assert summaries == [
            {
                "id": "relays",
                "path": "/v1/relays",
                "field_count": 2,
                "supports_identity_lookup": True,
                "default_pagination_mode": "cursor",
                "supports_cursor_pagination": True,
            }
        ]
        assert detail == {
            "id": "relays",
            "path": "/v1/relays",
            "fields": [
                {"name": "url", "type": "text", "nullable": False},
                {"name": "network", "type": "text", "nullable": False},
            ],
            "identity_fields": ["url"],
            "pagination": {
                "default_mode": "cursor",
                "supports_cursor": True,
                "supports_offset": True,
                "supports_total_opt_in": True,
                "cursor_param": "cursor",
                "meta_cursor_field": "next_cursor",
            },
        }


class TestReadModelQueryHelpers:
    def test_parse_read_model_filter_string_empty(self) -> None:
        assert parse_read_model_filter_string("") is None

    def test_parse_read_model_filter_string_trims_entries(self) -> None:
        assert parse_read_model_filter_string(" network = clearnet , kind = 1 ") == {
            "network": "clearnet",
            "kind": "1",
        }

    def test_parse_read_model_filter_string_skips_empty_parts(self) -> None:
        assert parse_read_model_filter_string(" , network = clearnet , , kind = 1 , ") == {
            "network": "clearnet",
            "kind": "1",
        }

    @pytest.mark.parametrize("filter_str", ["invalid", "network=clearnet,invalid", "=clearnet"])
    def test_parse_read_model_filter_string_rejects_malformed_parts(self, filter_str: str) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid filter value"):
            parse_read_model_filter_string(filter_str)

    def test_read_model_query_from_http_params(self) -> None:
        query = read_model_query_from_http_params(
            {
                "limit": "25",
                "offset": "5",
                "sort": "url:asc",
                "include_total": "true",
                "network": "clearnet",
            },
            default_page_size=100,
            max_page_size=1000,
        )

        assert query == ReadModelQuery(
            limit=25,
            offset=5,
            max_page_size=1000,
            filters={"network": "clearnet"},
            sort="url:asc",
            include_total=True,
            cursor=None,
        )

    def test_read_model_query_from_http_params_trims_filter_keys(self) -> None:
        query = read_model_query_from_http_params(
            {
                " network ": " clearnet ",
                " kind ": " 1 ",
            },
            default_page_size=100,
            max_page_size=1000,
        )

        assert query.filters == {
            "network": "clearnet",
            "kind": "1",
        }

    def test_read_model_query_from_http_params_trims_reserved_keys(self) -> None:
        query = read_model_query_from_http_params(
            {
                " limit ": "25",
                " sort ": " url:asc ",
                " include_total ": " true ",
            },
            default_page_size=100,
            max_page_size=1000,
        )

        assert query.limit == 25
        assert query.sort == "url:asc"
        assert query.include_total is True
        assert query.filters is None

    def test_read_model_query_from_http_params_invalid_limit(self) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid limit or offset"):
            read_model_query_from_http_params(
                {"limit": "oops"},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_http_params_rejects_blank_filter_key(self) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid filter field"):
            read_model_query_from_http_params(
                {"   ": "clearnet"},
                default_page_size=100,
                max_page_size=1000,
            )

    @pytest.mark.parametrize("params", [{"limit": "0"}, {"limit": "-1"}, {"offset": "-1"}])
    def test_read_model_query_from_http_params_rejects_non_positive_or_negative_bounds(
        self,
        params: dict[str, str],
    ) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid limit or offset"):
            read_model_query_from_http_params(
                params,
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_http_params_invalid_include_total(self) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid include_total value"):
            read_model_query_from_http_params(
                {"include_total": "maybe"},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_http_params_invalid_cursor_type(self) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid cursor value"):
            read_model_query_from_http_params(  # type: ignore[arg-type]
                {"cursor": 123},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_http_params_with_cursor(self) -> None:
        query = read_model_query_from_http_params(
            {"cursor": "opaque-token", "limit": "20"},
            default_page_size=100,
            max_page_size=1000,
        )

        assert query == ReadModelQuery(
            limit=20,
            offset=0,
            max_page_size=1000,
            filters=None,
            sort=None,
            include_total=False,
            cursor="opaque-token",
        )

    def test_read_model_query_from_http_params_normalizes_blank_sort(self) -> None:
        query = read_model_query_from_http_params(
            {"sort": "   "},
            default_page_size=100,
            max_page_size=1000,
        )

        assert query.sort is None

    def test_read_model_query_from_http_params_rejects_cursor_with_offset(self) -> None:
        with pytest.raises(
            ReadModelQueryError,
            match="Cursor pagination cannot be combined with offset",
        ):
            read_model_query_from_http_params(
                {"cursor": "opaque-token", "offset": "1"},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_job_params(self) -> None:
        query = read_model_query_from_job_params(
            {
                "limit": "50",
                "offset": "10",
                "sort": "url:asc",
                "filter": "network=clearnet,kind=>:100",
                "include_total": "1",
            },
            default_page_size=100,
            max_page_size=1000,
        )

        assert query == ReadModelQuery(
            limit=50,
            offset=10,
            max_page_size=1000,
            filters={"network": "clearnet", "kind": ">:100"},
            sort="url:asc",
            include_total=True,
            cursor=None,
        )

    def test_read_model_query_from_job_params_invalid_offset(self) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid limit or offset value"):
            read_model_query_from_job_params(
                {"offset": "oops"},
                default_page_size=100,
                max_page_size=1000,
            )

    @pytest.mark.parametrize("params", [{"limit": "0"}, {"limit": "-1"}, {"offset": "-1"}])
    def test_read_model_query_from_job_params_rejects_non_positive_or_negative_bounds(
        self,
        params: dict[str, str],
    ) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid limit or offset value"):
            read_model_query_from_job_params(
                params,
                default_page_size=100,
                max_page_size=1000,
            )

    @pytest.mark.parametrize("field_name", ["limit", "offset"])
    def test_read_model_query_from_job_params_rejects_boolean_numeric_fields(
        self,
        field_name: str,
    ) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid limit or offset value"):
            read_model_query_from_job_params(
                {field_name: True},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_job_params_invalid_include_total(self) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid include_total value"):
            read_model_query_from_job_params(
                {"include_total": "maybe"},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_job_params_accepts_boolean_include_total(self) -> None:
        query = read_model_query_from_job_params(
            {"include_total": True},
            default_page_size=100,
            max_page_size=1000,
        )

        assert query.include_total is True

    def test_read_model_query_from_job_params_invalid_cursor_type(self) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid cursor value"):
            read_model_query_from_job_params(
                {"cursor": 123},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_job_params_with_cursor(self) -> None:
        query = read_model_query_from_job_params(
            {"cursor": "opaque-token", "limit": "10"},
            default_page_size=100,
            max_page_size=1000,
        )

        assert query == ReadModelQuery(
            limit=10,
            offset=0,
            max_page_size=1000,
            filters=None,
            sort=None,
            include_total=False,
            cursor="opaque-token",
        )

    def test_read_model_query_from_job_params_normalizes_blank_sort_and_filter(self) -> None:
        query = read_model_query_from_job_params(
            {"sort": "   ", "filter": "   "},
            default_page_size=100,
            max_page_size=1000,
        )

        assert query.sort is None
        assert query.filters is None

    def test_read_model_query_from_job_params_invalid_sort_type(self) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid sort value"):
            read_model_query_from_job_params(
                {"sort": 123},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_job_params_invalid_filter_type(self) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid filter value"):
            read_model_query_from_job_params(
                {"filter": 123},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_job_params_invalid_filter_fragment(self) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid filter value"):
            read_model_query_from_job_params(
                {"filter": "network=clearnet,invalid"},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_job_params_rejects_cursor_with_offset(self) -> None:
        with pytest.raises(
            ReadModelQueryError,
            match="Cursor pagination cannot be combined with offset",
        ):
            read_model_query_from_job_params(
                {"cursor": "opaque-token", "offset": "1"},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_build_read_model_meta(self) -> None:
        meta = build_read_model_meta(
            QueryResult(
                rows=[{"url": "wss://relay.example.com"}],
                total=1,
                limit=10,
                offset=0,
                next_cursor="opaque-token",
            ),
            read_model_id="relays",
        )

        assert meta == {
            "total": 1,
            "limit": 10,
            "offset": 0,
            "next_cursor": "opaque-token",
            "read_model": "relays",
        }

    def test_build_read_model_meta_omits_total_when_unavailable(self) -> None:
        meta = build_read_model_meta(
            QueryResult(
                rows=[{"url": "wss://relay.example.com"}],
                total=None,
                limit=10,
                offset=0,
            ),
            read_model_id="relays",
        )

        assert meta == {
            "limit": 10,
            "offset": 0,
            "read_model": "relays",
        }

    def test_normalize_readable_resource_policies_rejects_non_canonical_names(self) -> None:
        with pytest.raises(
            ValueError,
            match=r"read_models contains non-public API read models: relay, relay_stats",
        ):
            normalize_readable_resource_policies(
                {
                    "relay": ReadModelPolicy(enabled=True),
                    "relay_stats": ReadModelPolicy(enabled=True),
                },
                surface="api",
            )
