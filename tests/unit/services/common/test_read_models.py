from pathlib import Path

from bigbrotr.core.yaml import load_yaml
from bigbrotr.services.common.read_models import (
    READ_MODEL_REGISTRY,
    ReadModelEntry,
    read_models_for_surface,
)


def _configured_tables(path: Path) -> set[str]:
    config = load_yaml(str(path))
    tables = config.get("tables", {})
    return set(tables)


class TestReadModelRegistry:
    def test_registry_entries_are_read_model_entry(self) -> None:
        for entry in READ_MODEL_REGISTRY.values():
            assert isinstance(entry, ReadModelEntry)

    def test_all_entries_are_catalog_compatibility_read_models(self) -> None:
        for read_model_id, entry in READ_MODEL_REGISTRY.items():
            assert entry.catalog_name == read_model_id
            assert entry.surfaces

    def test_registry_covers_all_configured_api_tables(self) -> None:
        api_configs = (
            Path("deployments/bigbrotr/config/services/api.yaml"),
            Path("deployments/lilbrotr/config/services/api.yaml"),
        )

        configured = set().union(*(_configured_tables(path) for path in api_configs))

        assert configured <= set(READ_MODEL_REGISTRY)

    def test_registry_covers_all_configured_dvm_tables(self) -> None:
        dvm_configs = (
            Path("deployments/bigbrotr/config/services/dvm.yaml"),
            Path("deployments/lilbrotr/config/services/dvm.yaml"),
        )

        configured = set().union(*(_configured_tables(path) for path in dvm_configs))

        assert configured <= set(READ_MODEL_REGISTRY)

    def test_api_surface_matches_configured_api_tables(self) -> None:
        api_configs = (
            Path("deployments/bigbrotr/config/services/api.yaml"),
            Path("deployments/lilbrotr/config/services/api.yaml"),
        )

        expected = set().union(*(_configured_tables(path) for path in api_configs))

        assert set(read_models_for_surface("api")) == expected

    def test_dvm_surface_matches_configured_dvm_tables(self) -> None:
        dvm_configs = (
            Path("deployments/bigbrotr/config/services/dvm.yaml"),
            Path("deployments/lilbrotr/config/services/dvm.yaml"),
        )

        expected = set().union(*(_configured_tables(path) for path in dvm_configs))

        assert set(read_models_for_surface("dvm")) == expected

    def test_internal_state_tables_are_not_public_read_models(self) -> None:
        assert "service_state" not in READ_MODEL_REGISTRY
