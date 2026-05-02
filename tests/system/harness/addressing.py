"""Stable runtime addressing helpers for higher-band system tests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

from .compose import deployment_dir, write_test_env_file


if TYPE_CHECKING:
    from pathlib import Path


SERVICE_METRIC_ENV_KEYS = {
    "finder": "FINDER_METRICS_PORT",
    "validator": "VALIDATOR_METRICS_PORT",
    "monitor": "MONITOR_METRICS_PORT",
    "synchronizer": "SYNCHRONIZER_METRICS_PORT",
    "refresher": "REFRESHER_METRICS_PORT",
    "api": "API_METRICS_PORT",
    "dvm": "DVM_METRICS_PORT",
    "assertor": "ASSERTOR_METRICS_PORT",
    "ranker": "RANKER_METRICS_PORT",
}
PROFILE_PORT_BASE = {
    "bigbrotr": 18000,
    "lilbrotr": 19000,
}
PROFILE_NAME_PREFIX = {
    "bigbrotr": "bb",
    "lilbrotr": "lb",
}


def _safe_component(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in value.lower()).strip("-")
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or "run"


def build_project_name(profile: str, run_label: str, *, slot: int = 0) -> str:
    """Build a deterministic compose project name suitable for parallel runs."""
    if slot < 0:
        raise ValueError("Runtime addressing slot must be non-negative")
    prefix = PROFILE_NAME_PREFIX[profile]
    cleaned = _safe_component(run_label)
    digest = hashlib.sha256(f"{profile}:{cleaned}:{slot}".encode()).hexdigest()[:8]
    project_name = f"{prefix}-sys-{cleaned[:24]}-{slot:02d}-{digest}"
    return project_name[:63]


@dataclass(frozen=True, slots=True)
class RuntimePortPlan:
    """Deterministic host-port assignments for one runtime stack."""

    db: int
    pgbouncer: int
    tor: int
    prometheus: int
    alertmanager: int
    grafana: int
    finder_metrics: int
    validator_metrics: int
    monitor_metrics: int
    synchronizer_metrics: int
    refresher_metrics: int
    api_metrics: int
    dvm_metrics: int
    assertor_metrics: int
    ranker_metrics: int

    @classmethod
    def for_profile(cls, profile: str, *, slot: int = 0) -> RuntimePortPlan:
        """Build the deterministic host-port plan for a profile/slot pair."""
        if slot < 0:
            raise ValueError("Runtime addressing slot must be non-negative")
        base = PROFILE_PORT_BASE[profile] + (slot * 100)
        return cls(
            db=base,
            pgbouncer=base + 1,
            tor=base + 2,
            prometheus=base + 3,
            alertmanager=base + 4,
            grafana=base + 5,
            finder_metrics=base + 10,
            validator_metrics=base + 11,
            monitor_metrics=base + 12,
            synchronizer_metrics=base + 13,
            refresher_metrics=base + 14,
            api_metrics=base + 15,
            dvm_metrics=base + 16,
            assertor_metrics=base + 17,
            ranker_metrics=base + 18,
        )

    def env_overrides(self) -> dict[str, str]:
        """Return env-file overrides for metrics endpoints."""
        return {
            "FINDER_METRICS_PORT": str(self.finder_metrics),
            "VALIDATOR_METRICS_PORT": str(self.validator_metrics),
            "MONITOR_METRICS_PORT": str(self.monitor_metrics),
            "SYNCHRONIZER_METRICS_PORT": str(self.synchronizer_metrics),
            "REFRESHER_METRICS_PORT": str(self.refresher_metrics),
            "API_METRICS_PORT": str(self.api_metrics),
            "DVM_METRICS_PORT": str(self.dvm_metrics),
            "ASSERTOR_METRICS_PORT": str(self.assertor_metrics),
            "RANKER_METRICS_PORT": str(self.ranker_metrics),
        }


@dataclass(frozen=True, slots=True)
class RuntimeAddressPlan:
    """Filesystem, naming, and port plan for one runtime stack."""

    profile: str
    project_name: str
    runtime_root: Path
    env_file: Path
    compose_file: Path
    ports: RuntimePortPlan
    postgres_data_dir: Path
    ranker_data_dir: Path
    data_network_name: str
    monitoring_network_name: str
    prometheus_volume_name: str
    alertmanager_volume_name: str
    grafana_volume_name: str

    @classmethod
    def create(
        cls,
        profile: str,
        base_dir: Path,
        run_label: str,
        *,
        slot: int = 0,
    ) -> RuntimeAddressPlan:
        """Create the deterministic runtime addressing plan and compose file."""
        base_deployment_dir = deployment_dir(profile)
        ports = RuntimePortPlan.for_profile(profile, slot=slot)
        project_name = build_project_name(profile, run_label, slot=slot)
        runtime_root = base_dir / project_name
        runtime_root.mkdir(parents=True, exist_ok=True)

        postgres_data_dir = runtime_root / "data" / "postgres"
        ranker_data_dir = runtime_root / "data" / "ranker"
        postgres_data_dir.mkdir(parents=True, exist_ok=True)
        ranker_data_dir.mkdir(parents=True, exist_ok=True)

        env_file = runtime_root / f"{profile}.env"
        write_test_env_file(
            profile,
            project_name,
            env_file,
            overrides=ports.env_overrides(),
        )

        data_network_name = f"{project_name}-data-network"
        monitoring_network_name = f"{project_name}-monitoring-network"
        prometheus_volume_name = f"{project_name}-prometheus-data"
        alertmanager_volume_name = f"{project_name}-alertmanager-data"
        grafana_volume_name = f"{project_name}-grafana-data"

        compose_data = yaml.safe_load((base_deployment_dir / "docker-compose.yaml").read_text())
        services = compose_data["services"]

        for service_name, service_data in services.items():
            service_data["container_name"] = f"{project_name}-{service_name}"

        _rewrite_service_ports(services, ports)
        _rewrite_service_volumes(services, postgres_data_dir, ranker_data_dir)

        _rewrite_top_level_names(
            compose_data,
            profile,
            data_network_name=data_network_name,
            monitoring_network_name=monitoring_network_name,
            prometheus_volume_name=prometheus_volume_name,
            alertmanager_volume_name=alertmanager_volume_name,
            grafana_volume_name=grafana_volume_name,
        )

        compose_file = runtime_root / f"{profile}.runtime.compose.yaml"
        compose_file.write_text(yaml.safe_dump(compose_data, sort_keys=False))

        return cls(
            profile=profile,
            project_name=project_name,
            runtime_root=runtime_root,
            env_file=env_file,
            compose_file=compose_file,
            ports=ports,
            postgres_data_dir=postgres_data_dir,
            ranker_data_dir=ranker_data_dir,
            data_network_name=data_network_name,
            monitoring_network_name=monitoring_network_name,
            prometheus_volume_name=prometheus_volume_name,
            alertmanager_volume_name=alertmanager_volume_name,
            grafana_volume_name=grafana_volume_name,
        )


def _rewrite_service_ports(services: dict[str, dict[str, object]], ports: RuntimePortPlan) -> None:
    services["postgres"]["ports"] = [f"127.0.0.1:{ports.db}:5432"]
    services["pgbouncer"]["ports"] = [f"127.0.0.1:{ports.pgbouncer}:5432"]
    services["tor"]["ports"] = [f"127.0.0.1:{ports.tor}:9050"]
    services["prometheus"]["ports"] = [f"127.0.0.1:{ports.prometheus}:9090"]
    services["alertmanager"]["ports"] = [f"127.0.0.1:{ports.alertmanager}:9093"]
    services["grafana"]["ports"] = [f"127.0.0.1:{ports.grafana}:3000"]


def _replace_bind_source(spec: str, destination: str, new_source: Path) -> str:
    parts = spec.split(":")
    if len(parts) < 2 or parts[1] != destination:
        return spec
    parts[0] = new_source.as_posix()
    return ":".join(parts)


def _rewrite_service_volumes(
    services: dict[str, dict[str, object]],
    postgres_data_dir: Path,
    ranker_data_dir: Path,
) -> None:
    postgres_volumes = services["postgres"]["volumes"]
    services["postgres"]["volumes"] = [
        _replace_bind_source(spec, "/var/lib/postgresql/data", postgres_data_dir)
        if isinstance(spec, str)
        else spec
        for spec in postgres_volumes
    ]

    ranker_volumes = services["ranker"]["volumes"]
    services["ranker"]["volumes"] = [
        _replace_bind_source(spec, "/app/data", ranker_data_dir) if isinstance(spec, str) else spec
        for spec in ranker_volumes
    ]


def _rewrite_top_level_names(
    compose_data: dict[str, object],
    profile: str,
    *,
    data_network_name: str,
    monitoring_network_name: str,
    prometheus_volume_name: str,
    alertmanager_volume_name: str,
    grafana_volume_name: str,
) -> None:
    volume_data = compose_data["volumes"]
    volume_data["prometheus-data"]["name"] = prometheus_volume_name
    volume_data["alertmanager-data"]["name"] = alertmanager_volume_name
    volume_data["grafana-data"]["name"] = grafana_volume_name

    network_data = compose_data["networks"]
    network_data[f"{profile}-data-network"]["name"] = data_network_name
    network_data[f"{profile}-monitoring-network"]["name"] = monitoring_network_name
