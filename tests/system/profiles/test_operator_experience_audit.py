from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.system


_PROFILES = ("bigbrotr", "lilbrotr")
_ROOT_PORT_LABELS = {
    "PostgreSQL": "postgres",
    "PgBouncer": "pgbouncer",
    "Tor SOCKS5": "tor",
}
_ROOT_README_LINKS = (
    ".env.example",
    "docker-compose.yaml",
    "config/README.md",
    "postgres/README.md",
    "static/README.md",
    "data/README.md",
    "dumps/README.md",
    "monitoring/README.md",
    "pgbouncer/README.md",
)
_MONITORING_SUBDIRS = {"prometheus", "alertmanager", "grafana", "postgres-exporter"}
_ASSET_READMES = (
    "README.md",
    "config/services/README.md",
    "monitoring/README.md",
    "postgres/README.md",
    "pgbouncer/README.md",
    "static/README.md",
)
_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_ROOT_PORT_RE = re.compile(r"^\s*-\s*(?P<label>[^:]+):\s*`(?P<port>\d+)`\s*$")
_METRICS_RANGE_RE = re.compile(
    r"^\s*-\s*service metrics:\s*`(?P<start>\d+)`\s*through\s*`(?P<end>\d+)`\s*$"
)
_ENV_METRICS_RE = re.compile(r"^# (?P<name>[A-Z_]+_METRICS_PORT)=(?P<port>\d+)\s*$")
_COMPOSE_METRICS_RE = re.compile(r"\$\{(?P<name>[A-Z_]+_METRICS_PORT):-(?P<port>\d+)\}")
_HOST_PORT_RE = re.compile(r"127\.0\.0\.1:(?P<port>\d+):\d+")


def _deployment_root(profile: str) -> Path:
    return Path("deployments") / profile


def _read_text(profile: str, relative_path: str) -> str:
    return (_deployment_root(profile) / relative_path).read_text()


def _markdown_link_targets(profile: str, relative_path: str) -> tuple[str, ...]:
    return tuple(_LINK_RE.findall(_read_text(profile, relative_path)))


def _assert_markdown_links_exist(profile: str, relative_path: str) -> None:
    base = _deployment_root(profile) / relative_path
    for target in _markdown_link_targets(profile, relative_path):
        if target.startswith("http"):
            continue
        resolved = (base.parent / target).resolve()
        assert resolved.exists(), f"{profile}:{relative_path} points at missing target {target!r}"


def _compose_services(profile: str) -> dict[str, object]:
    payload = yaml.safe_load((_deployment_root(profile) / "docker-compose.yaml").read_text())
    assert isinstance(payload, dict)
    services = payload.get("services")
    assert isinstance(services, dict)
    return services


def _compose_host_ports(profile: str) -> dict[str, int]:
    host_ports: dict[str, int] = {}
    for service_name, spec in _compose_services(profile).items():
        assert isinstance(spec, dict)
        for entry in spec.get("ports") or []:
            match = _HOST_PORT_RE.search(str(entry))
            if match is not None:
                host_ports.setdefault(str(service_name), int(match.group("port")))
    return host_ports


def _compose_metrics_ports(profile: str) -> dict[str, int]:
    metrics_ports: dict[str, int] = {}
    for spec in _compose_services(profile).values():
        assert isinstance(spec, dict)
        for entry in spec.get("ports") or []:
            match = _COMPOSE_METRICS_RE.search(str(entry))
            if match is not None:
                metrics_ports[match.group("name")] = int(match.group("port"))
    return metrics_ports


def _env_metrics_ports(profile: str) -> dict[str, int]:
    ports: dict[str, int] = {}
    for line in _read_text(profile, ".env.example").splitlines():
        match = _ENV_METRICS_RE.match(line)
        if match is not None:
            ports[match.group("name")] = int(match.group("port"))
    return ports


def _readme_root_ports(profile: str) -> tuple[dict[str, int], tuple[int, int]]:
    ports: dict[str, int] = {}
    metrics_range: tuple[int, int] | None = None
    for line in _read_text(profile, "README.md").splitlines():
        port_match = _ROOT_PORT_RE.match(line)
        if port_match is not None:
            ports[port_match.group("label")] = int(port_match.group("port"))
            continue
        range_match = _METRICS_RANGE_RE.match(line)
        if range_match is not None:
            metrics_range = (int(range_match.group("start")), int(range_match.group("end")))
    assert metrics_range is not None
    return ports, metrics_range


def _documented_service_yaml_files(profile: str) -> set[str]:
    return {
        Path(target).name
        for target in _markdown_link_targets(profile, "config/services/README.md")
        if target.endswith(".yaml")
    }


def _actual_service_yaml_files(profile: str) -> set[str]:
    return {
        path.name for path in (_deployment_root(profile) / "config" / "services").glob("*.yaml")
    }


def _documented_monitoring_dirs(profile: str) -> set[str]:
    return {
        Path(target).parts[0].rstrip("/")
        for target in _markdown_link_targets(profile, "monitoring/README.md")
        if target.endswith("/README.md")
    }


@pytest.mark.parametrize("profile", _PROFILES)
def test_profile_root_readme_ports_and_links_match_compose_and_env_contract(profile: str) -> None:
    _assert_markdown_links_exist(profile, "README.md")

    link_targets = set(_markdown_link_targets(profile, "README.md"))
    assert link_targets >= set(_ROOT_README_LINKS)

    compose_host_ports = _compose_host_ports(profile)
    readme_ports, metrics_range = _readme_root_ports(profile)

    assert readme_ports == {
        label: compose_host_ports[service_name] for label, service_name in _ROOT_PORT_LABELS.items()
    }

    env_metrics = _env_metrics_ports(profile)
    compose_metrics = _compose_metrics_ports(profile)
    assert env_metrics == compose_metrics
    assert metrics_range == (min(env_metrics.values()), max(env_metrics.values()))


@pytest.mark.parametrize("profile", _PROFILES)
def test_profile_operator_asset_readmes_match_real_inventory(profile: str) -> None:
    for relative_path in _ASSET_READMES:
        _assert_markdown_links_exist(profile, relative_path)

    assert _documented_service_yaml_files(profile) == _actual_service_yaml_files(profile)
    assert _documented_monitoring_dirs(profile) == _MONITORING_SUBDIRS
