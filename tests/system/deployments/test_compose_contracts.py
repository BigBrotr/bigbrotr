from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.system


_COMMON_DEPENDS_ON = {
    "postgres": {},
    "pgbouncer": {"postgres": "service_healthy"},
    "tor": {},
    "seeder": {"pgbouncer": "service_healthy"},
    "finder": {"pgbouncer": "service_healthy"},
    "validator": {"pgbouncer": "service_healthy", "tor": "service_healthy"},
    "monitor": {"pgbouncer": "service_healthy", "tor": "service_healthy"},
    "synchronizer": {"pgbouncer": "service_healthy", "tor": "service_healthy"},
    "refresher": {"pgbouncer": "service_healthy"},
    "ranker": {"pgbouncer": "service_healthy"},
    "api": {"pgbouncer": "service_healthy"},
    "dvm": {"pgbouncer": "service_healthy"},
    "assertor": {"pgbouncer": "service_healthy"},
    "postgres-exporter": {"postgres": "service_healthy"},
    "prometheus": {},
    "alertmanager": {},
    "grafana": {"prometheus": "service_healthy"},
}


def _load_compose(profile: str) -> dict[str, object]:
    compose_path = Path(f"deployments/{profile}/docker-compose.yaml")
    payload = yaml.safe_load(compose_path.read_text())
    assert isinstance(payload, dict)
    return payload


def _metrics_healthcheck(port: int = 8000, *, start_period: str = "30s") -> dict[str, object]:
    return {
        "test": [
            "CMD-SHELL",
            f"python -c \"import urllib.request; urllib.request.urlopen('http://localhost:{port}/metrics')\"",
        ],
        "interval": "30s",
        "timeout": "10s",
        "retries": 3,
        "start_period": start_period,
    }


def _wget_healthcheck(
    url: str,
    *,
    timeout: str,
    retries: int,
    start_period: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "test": ["CMD", "wget", "-q", "--spider", url],
        "interval": "30s",
        "timeout": timeout,
        "retries": retries,
    }
    if start_period is not None:
        payload["start_period"] = start_period
    return payload


def _expected_healthchecks(profile: str) -> dict[str, dict[str, object]]:
    assertor_port = 8008 if profile == "bigbrotr" else 9008
    return {
        "postgres": {
            "test": ["CMD-SHELL", f"pg_isready -U admin -d {profile}"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 5,
            "start_period": "30s",
        },
        "pgbouncer": {
            "test": ["CMD-SHELL", "pg_isready -h localhost -p 5432 -U admin"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 3,
            "start_period": "20s",
        },
        "tor": {
            "test": ["CMD-SHELL", "nc -z 127.0.0.1 9050 || exit 1"],
            "interval": "30s",
            "timeout": "5s",
            "retries": 3,
            "start_period": "60s",
        },
        "seeder": {"disable": True},
        "finder": _metrics_healthcheck(),
        "validator": _metrics_healthcheck(),
        "monitor": _metrics_healthcheck(),
        "synchronizer": _metrics_healthcheck(start_period="60s"),
        "refresher": _metrics_healthcheck(),
        "ranker": _metrics_healthcheck(),
        "api": {
            "test": [
                "CMD-SHELL",
                "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8080/health')\"",
            ],
            "interval": "30s",
            "timeout": "10s",
            "retries": 3,
            "start_period": "30s",
        },
        "dvm": _metrics_healthcheck(),
        "assertor": _metrics_healthcheck(assertor_port),
        "postgres-exporter": {
            "test": ["CMD-SHELL", "wget -q --spider http://localhost:9187/metrics || exit 1"],
            "interval": "30s",
            "timeout": "5s",
            "retries": 3,
            "start_period": "10s",
        },
        "prometheus": _wget_healthcheck(
            "http://localhost:9090/-/healthy",
            timeout="10s",
            retries=3,
            start_period="10s",
        ),
        "alertmanager": _wget_healthcheck(
            "http://localhost:9093/-/healthy",
            timeout="5s",
            retries=3,
        ),
        "grafana": _wget_healthcheck(
            "http://localhost:3000/api/health",
            timeout="10s",
            retries=3,
            start_period="30s",
        ),
    }


def _normalize_depends_on(service_data: dict[str, object]) -> dict[str, str]:
    raw_depends_on = service_data.get("depends_on")
    if raw_depends_on is None:
        return {}
    assert isinstance(raw_depends_on, dict)
    normalized: dict[str, str] = {}
    for dependency, value in raw_depends_on.items():
        assert isinstance(dependency, str)
        assert isinstance(value, dict)
        condition = value.get("condition")
        assert isinstance(condition, str)
        normalized[dependency] = condition
    return normalized


def _normalize_healthcheck(service_data: dict[str, object]) -> dict[str, object]:
    healthcheck = service_data.get("healthcheck")
    assert isinstance(healthcheck, dict)
    return dict(healthcheck)


@pytest.mark.parametrize("profile", ["bigbrotr", "lilbrotr"])
def test_compose_dependency_contract_is_exact(profile: str) -> None:
    compose_data = _load_compose(profile)
    services = compose_data["services"]
    assert isinstance(services, dict)

    actual = {
        service_name: _normalize_depends_on(service_data)
        for service_name, service_data in services.items()
        if isinstance(service_name, str) and isinstance(service_data, dict)
    }

    assert actual == _COMMON_DEPENDS_ON


@pytest.mark.parametrize("profile", ["bigbrotr", "lilbrotr"])
def test_compose_healthcheck_contract_is_exact(profile: str) -> None:
    compose_data = _load_compose(profile)
    services = compose_data["services"]
    assert isinstance(services, dict)

    actual = {
        service_name: _normalize_healthcheck(service_data)
        for service_name, service_data in services.items()
        if isinstance(service_name, str) and isinstance(service_data, dict)
    }

    assert actual == _expected_healthchecks(profile)


def test_profile_compose_contracts_only_differ_on_intended_fields() -> None:
    big_services = _load_compose("bigbrotr")["services"]
    lil_services = _load_compose("lilbrotr")["services"]
    assert isinstance(big_services, dict)
    assert isinstance(lil_services, dict)

    big_depends_on = {
        service_name: _normalize_depends_on(service_data)
        for service_name, service_data in big_services.items()
        if isinstance(service_name, str) and isinstance(service_data, dict)
    }
    lil_depends_on = {
        service_name: _normalize_depends_on(service_data)
        for service_name, service_data in lil_services.items()
        if isinstance(service_name, str) and isinstance(service_data, dict)
    }

    big_healthchecks = deepcopy(_expected_healthchecks("bigbrotr"))
    lil_healthchecks = deepcopy(_expected_healthchecks("lilbrotr"))

    big_healthchecks["postgres"]["test"] = ["CMD-SHELL", "pg_isready -U admin -d <profile>"]
    lil_healthchecks["postgres"]["test"] = ["CMD-SHELL", "pg_isready -U admin -d <profile>"]
    big_healthchecks["assertor"]["test"] = [
        "CMD-SHELL",
        "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:<assertor-metrics-port>/metrics')\"",
    ]
    lil_healthchecks["assertor"]["test"] = [
        "CMD-SHELL",
        "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:<assertor-metrics-port>/metrics')\"",
    ]

    assert big_depends_on == lil_depends_on == _COMMON_DEPENDS_ON
    assert big_healthchecks == lil_healthchecks
