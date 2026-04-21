from pathlib import Path

import yaml

from tests.system.harness import RuntimeAddressPlan, RuntimePortPlan, build_project_name


class TestBuildProjectName:
    def test_sanitizes_and_bounds_project_name(self) -> None:
        project_name = build_project_name("bigbrotr", "Graph / Alerts / Smoke Run", slot=7)

        assert project_name.startswith("bb-sys-graph-alerts-smoke-run-07-")
        assert len(project_name) <= 63


class TestRuntimePortPlan:
    def test_is_deterministic_per_profile_and_slot(self) -> None:
        first = RuntimePortPlan.for_profile("bigbrotr", slot=2)
        second = RuntimePortPlan.for_profile("bigbrotr", slot=2)

        assert first == second
        assert first.db == 18200
        assert first.ranker_metrics == 18218

    def test_env_overrides_match_metric_port_fields(self) -> None:
        ports = RuntimePortPlan.for_profile("lilbrotr", slot=1)

        assert ports.env_overrides() == {
            "FINDER_METRICS_PORT": "19110",
            "VALIDATOR_METRICS_PORT": "19111",
            "MONITOR_METRICS_PORT": "19112",
            "SYNCHRONIZER_METRICS_PORT": "19113",
            "REFRESHER_METRICS_PORT": "19114",
            "API_METRICS_PORT": "19115",
            "DVM_METRICS_PORT": "19116",
            "ASSERTOR_METRICS_PORT": "19117",
            "RANKER_METRICS_PORT": "19118",
        }


class TestRuntimeAddressPlan:
    def test_create_writes_runtime_env_and_compose_files(self, tmp_path: Path) -> None:
        plan = RuntimeAddressPlan.create("bigbrotr", tmp_path, "compose baseline", slot=0)

        assert plan.env_file.is_file()
        assert plan.compose_file.is_file()
        assert "FINDER_METRICS_PORT=18010" in plan.env_file.read_text()

    def test_create_rewrites_fixed_container_names_and_ports(self, tmp_path: Path) -> None:
        plan = RuntimeAddressPlan.create("bigbrotr", tmp_path, "compose baseline", slot=3)
        rendered = yaml.safe_load(plan.compose_file.read_text())

        assert rendered["services"]["postgres"]["container_name"] == f"{plan.project_name}-postgres"
        assert rendered["services"]["grafana"]["container_name"] == f"{plan.project_name}-grafana"
        assert rendered["services"]["postgres"]["ports"] == ["127.0.0.1:18300:5432"]
        assert rendered["services"]["prometheus"]["ports"] == ["127.0.0.1:18303:9090"]
        assert rendered["services"]["alertmanager"]["ports"] == ["127.0.0.1:18304:9093"]
        assert rendered["services"]["grafana"]["ports"] == ["127.0.0.1:18305:3000"]

    def test_create_rehomes_mutable_data_mounts(self, tmp_path: Path) -> None:
        plan = RuntimeAddressPlan.create("lilbrotr", tmp_path, "data rewrite", slot=0)
        rendered = yaml.safe_load(plan.compose_file.read_text())

        postgres_mounts = rendered["services"]["postgres"]["volumes"]
        ranker_mounts = rendered["services"]["ranker"]["volumes"]

        assert f"{plan.postgres_data_dir.as_posix()}:/var/lib/postgresql/data" in postgres_mounts[0]
        assert any(
            f"{plan.ranker_data_dir.as_posix()}:/app/data" in mount for mount in ranker_mounts
        )

    def test_create_rewrites_top_level_volume_and_network_names(self, tmp_path: Path) -> None:
        plan = RuntimeAddressPlan.create("bigbrotr", tmp_path, "resource rewrite", slot=1)
        rendered = yaml.safe_load(plan.compose_file.read_text())

        assert rendered["volumes"]["prometheus-data"]["name"] == plan.prometheus_volume_name
        assert rendered["volumes"]["alertmanager-data"]["name"] == plan.alertmanager_volume_name
        assert rendered["volumes"]["grafana-data"]["name"] == plan.grafana_volume_name
        assert rendered["networks"]["bigbrotr-data-network"]["name"] == plan.data_network_name
        assert (
            rendered["networks"]["bigbrotr-monitoring-network"]["name"]
            == plan.monitoring_network_name
        )
