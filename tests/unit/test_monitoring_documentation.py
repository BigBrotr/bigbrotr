from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
README_PATH = ROOT / "README.md"
MONITORING_SETUP_PATH = ROOT / "docs" / "how-to" / "monitoring-setup.md"
DOCKER_DEPLOY_PATH = ROOT / "docs" / "how-to" / "docker-deploy.md"
USER_GUIDE_PATH = ROOT / "docs" / "user-guide" / "monitoring.md"
PROFILES = ("bigbrotr", "lilbrotr")


def _read_text(path: Path) -> str:
    return path.read_text()


def _compose_services(profile: str) -> dict[str, object]:
    compose_path = ROOT / "deployments" / profile / "docker-compose.yaml"
    payload = yaml.safe_load(compose_path.read_text())
    assert isinstance(payload, dict)
    services = payload["services"]
    assert isinstance(services, dict)
    return services


def _postgres_exporter_version() -> str:
    image = _compose_services("bigbrotr")["postgres-exporter"]["image"]
    assert isinstance(image, str)
    _repo, _separator, remainder = image.partition(":")
    return remainder.split("@", 1)[0]


def _service_dashboard_names() -> tuple[str, ...]:
    dashboard_root = (
        ROOT / "deployments" / "bigbrotr" / "monitoring" / "grafana" / "provisioning" / "dashboards"
    )
    dashboards = sorted(
        path.stem for path in dashboard_root.glob("*.json") if path.stem not in PROFILES
    )
    return tuple(dashboards)


def _healthcheck_endpoint(service_spec: object) -> str:
    assert isinstance(service_spec, dict)
    healthcheck = service_spec["healthcheck"]
    assert isinstance(healthcheck, dict)
    command = " ".join(healthcheck["test"])
    match = re.search(r"http://localhost:[^\"' ]+", command)
    assert match is not None
    return match.group(0)


def test_readme_monitoring_summary_matches_operator_surface() -> None:
    text = _read_text(README_PATH)

    assert f"prometheuscommunity/postgres-exporter:{_postgres_exporter_version()}" in text
    assert "RefresherTargetsFailing" in text
    assert "RefresherViewsFailing" not in text
    assert "default `Prometheus` datasource" in text
    assert "one deployment overview" in text


def test_monitoring_setup_documents_builtin_stack_and_dashboard_surface() -> None:
    text = _read_text(MONITORING_SETUP_PATH)

    for component in ("Prometheus", "Alertmanager", "Grafana", "postgres-exporter"):
        assert component in text
    assert "UID `prometheus`" in text
    assert "postgres-exporter:9187" in text
    assert (
        f"`{len(_service_dashboard_names()) + 1}` auto-provisioned dashboards per profile" in text
    )
    for dashboard_name in _service_dashboard_names():
        assert dashboard_name in text


def test_docker_deploy_documents_monitoring_network_membership() -> None:
    text = _read_text(DOCKER_DEPLOY_PATH)

    expected_row = (
        "| **monitoring-network** | Prometheus, Grafana, Alertmanager, "
        "postgres-exporter, all services | Metrics scraping, alert routing, and dashboards |"
    )
    assert expected_row in text


def test_user_guide_monitoring_healthchecks_match_compose_contract() -> None:
    text = _read_text(USER_GUIDE_PATH)
    services = _compose_services("bigbrotr")

    expected_endpoints = (
        _healthcheck_endpoint(services["finder"]),
        _healthcheck_endpoint(services["api"]),
        _healthcheck_endpoint(services["postgres-exporter"]),
        _healthcheck_endpoint(services["prometheus"]),
        _healthcheck_endpoint(services["alertmanager"]),
        _healthcheck_endpoint(services["grafana"]),
    )

    for endpoint in expected_endpoints:
        assert endpoint in text

    assert "urllib.request.urlopen" in text
    assert "wget -q --spider" in text
    assert "Seeder remains a one-shot" in text
    assert "uid: prometheus" in text
    assert "<profile>.json" in text
    for dashboard_name in _service_dashboard_names():
        assert dashboard_name in text
