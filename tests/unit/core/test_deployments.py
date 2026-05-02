from pathlib import Path

import pytest

from bigbrotr.core.deployments import (
    BUILTIN_DEPLOYMENT_PROFILES,
    BUILTIN_STORAGE_PROFILES,
    DEFAULT_DEPLOYMENT_PROFILE,
    DeploymentLayout,
    builtin_deployment_spec,
    deployment_layout,
    resolve_builtin_deployment_root,
    storage_profile_spec,
)


def _create_deployment_root(base: Path, profile: str) -> Path:
    root = base / profile
    (root / "config" / "services").mkdir(parents=True)
    (root / "postgres" / "init").mkdir(parents=True)
    (root / "docker-compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (root / ".env.example").write_text("EXAMPLE=true\n", encoding="utf-8")
    (root / "config" / "brotr.yaml").write_text("pool: {}\n", encoding="utf-8")
    return root


class TestDeploymentProfiles:
    def test_default_profile_is_builtin(self) -> None:
        assert DEFAULT_DEPLOYMENT_PROFILE in BUILTIN_DEPLOYMENT_PROFILES

    def test_invalid_builtin_profile_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unsupported built-in deployment profile"):
            deployment_layout("custombrotr")

    def test_layout_resolves_repo_checkout_root_for_builtin_profile(self) -> None:
        layout = deployment_layout("bigbrotr", cwd=Path.cwd())

        assert isinstance(layout, DeploymentLayout)
        assert layout.name == "bigbrotr"
        assert layout.storage_profile == "full_archive"
        assert layout.storage_profile_contract.stores_full_event_payload is True
        assert layout.root == Path.cwd().resolve() / "deployments" / "bigbrotr"
        assert layout.brotr_config_path == layout.root / "config" / "brotr.yaml"
        assert (
            layout.service_config_path("finder")
            == layout.root / "config" / "services" / "finder.yaml"
        )

    def test_resolve_builtin_root_uses_current_deployment_root(self, tmp_path: Path) -> None:
        deployment_root = _create_deployment_root(tmp_path, "bigbrotr")

        assert resolve_builtin_deployment_root("bigbrotr", cwd=deployment_root) == deployment_root

    def test_resolve_builtin_root_searches_upward_for_checkout(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        nested_dir = repo_root / "src" / "nested"
        nested_dir.mkdir(parents=True)
        deployment_root = _create_deployment_root(repo_root / "deployments", "lilbrotr")

        assert resolve_builtin_deployment_root("lilbrotr", cwd=nested_dir) == deployment_root

    def test_layout_reports_missing_required_paths_and_service_configs(
        self, tmp_path: Path
    ) -> None:
        deployment_root = tmp_path / "bigbrotr"
        deployment_root.mkdir()
        layout = DeploymentLayout("bigbrotr", deployment_root)

        missing = layout.missing_required_paths(service_names=("finder", "monitor"))

        assert missing == (
            deployment_root / "docker-compose.yaml",
            deployment_root / ".env.example",
            deployment_root / "config" / "brotr.yaml",
            deployment_root / "config" / "services",
            deployment_root / "postgres" / "init",
            deployment_root / "config" / "services" / "finder.yaml",
            deployment_root / "config" / "services" / "monitor.yaml",
        )


class TestStorageProfiles:
    def test_builtin_storage_profiles_have_explicit_contracts(self) -> None:
        assert BUILTIN_STORAGE_PROFILES == ("full_archive", "lightweight_archive")

    def test_bigbrotr_uses_full_archive_profile(self) -> None:
        spec = builtin_deployment_spec("bigbrotr")
        profile = storage_profile_spec(spec.storage_profile)

        assert spec.database_name == "bigbrotr"
        assert spec.storage_profile == "full_archive"
        assert profile.event_payload_mode == "full"
        assert profile.sql_template_namespace is None
        assert profile.stores_full_event_payload is True
        assert profile.stores_event_tags is True
        assert profile.stores_event_content is True
        assert profile.stores_event_signature is True

    def test_lilbrotr_uses_lightweight_archive_profile(self) -> None:
        spec = builtin_deployment_spec("lilbrotr")
        profile = storage_profile_spec(spec.storage_profile)

        assert spec.database_name == "lilbrotr"
        assert spec.storage_profile == "lightweight_archive"
        assert profile.event_payload_mode == "lightweight"
        assert profile.sql_template_namespace == "lilbrotr"
        assert profile.stores_full_event_payload is False
        assert profile.stores_event_tags is False
        assert profile.stores_event_content is False
        assert profile.stores_event_signature is False

    def test_invalid_storage_profile_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unsupported built-in storage profile"):
            storage_profile_spec("custom_archive")
