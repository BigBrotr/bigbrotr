from pathlib import Path
from unittest.mock import AsyncMock

from bigbrotr.core.yaml import load_yaml
from bigbrotr.services.common.catalog import Catalog, ColumnSchema, QueryResult, TableSchema
from bigbrotr.services.common.read_models import (
    READ_MODEL_REGISTRY,
    ReadModelEntry,
    ReadModelQuery,
    enabled_read_models_for_surface,
    read_models_for_surface,
)


def _configured_read_models(path: Path) -> set[str]:
    config = load_yaml(str(path))
    read_models = config.get("read_models")
    if read_models is None:
        read_models = config.get("tables", {})
    return set(read_models)


class TestReadModelRegistry:
    def test_registry_entries_are_read_model_entry(self) -> None:
        for entry in READ_MODEL_REGISTRY.values():
            assert isinstance(entry, ReadModelEntry)

    def test_all_entries_are_catalog_compatibility_read_models(self) -> None:
        for read_model_id, entry in READ_MODEL_REGISTRY.items():
            assert entry.read_model_id == read_model_id
            assert entry.catalog_name == read_model_id
            assert entry.surfaces

    def test_registry_covers_all_configured_api_tables(self) -> None:
        api_configs = (
            Path("deployments/bigbrotr/config/services/api.yaml"),
            Path("deployments/lilbrotr/config/services/api.yaml"),
        )

        configured = set().union(*(_configured_read_models(path) for path in api_configs))

        assert configured <= set(READ_MODEL_REGISTRY)

    def test_registry_covers_all_configured_dvm_tables(self) -> None:
        dvm_configs = (
            Path("deployments/bigbrotr/config/services/dvm.yaml"),
            Path("deployments/lilbrotr/config/services/dvm.yaml"),
        )

        configured = set().union(*(_configured_read_models(path) for path in dvm_configs))

        assert configured <= set(READ_MODEL_REGISTRY)

    def test_api_surface_matches_configured_api_tables(self) -> None:
        api_configs = (
            Path("deployments/bigbrotr/config/services/api.yaml"),
            Path("deployments/lilbrotr/config/services/api.yaml"),
        )

        expected = set().union(*(_configured_read_models(path) for path in api_configs))

        assert set(read_models_for_surface("api")) == expected

    def test_dvm_surface_matches_configured_dvm_tables(self) -> None:
        dvm_configs = (
            Path("deployments/bigbrotr/config/services/dvm.yaml"),
            Path("deployments/lilbrotr/config/services/dvm.yaml"),
        )

        expected = set().union(*(_configured_read_models(path) for path in dvm_configs))

        assert set(read_models_for_surface("dvm")) == expected

    def test_internal_state_tables_are_not_public_read_models(self) -> None:
        assert "service_state" not in READ_MODEL_REGISTRY

    def test_enabled_read_models_filter_by_config_and_catalog(self) -> None:
        enabled = enabled_read_models_for_surface(
            "api",
            available_catalog_names={"relay", "event"},
            enabled_names={"relay", "metadata"},
        )

        assert set(enabled) == {"relay"}

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

        entry = READ_MODEL_REGISTRY["relay"]

        assert entry.schema(catalog) == catalog.tables["relay"]

    async def test_entry_query_delegates_to_catalog(self) -> None:
        catalog = Catalog()
        expected = QueryResult(
            rows=[{"url": "wss://relay.example.com"}], total=1, limit=5, offset=0
        )
        catalog.query = AsyncMock(return_value=expected)  # type: ignore[method-assign]
        brotr = object()

        entry = READ_MODEL_REGISTRY["relay"]
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
        )

    async def test_entry_get_by_pk_delegates_to_catalog(self) -> None:
        catalog = Catalog()
        expected = {"url": "wss://relay.example.com"}
        catalog.get_by_pk = AsyncMock(return_value=expected)  # type: ignore[method-assign]
        brotr = object()

        entry = READ_MODEL_REGISTRY["relay"]
        pk_values = {"url": "wss://relay.example.com"}

        result = await entry.get_by_pk(brotr, catalog, pk_values)

        assert result == expected
        catalog.get_by_pk.assert_awaited_once_with(  # type: ignore[attr-defined]
            brotr,
            "relay",
            pk_values,
        )
