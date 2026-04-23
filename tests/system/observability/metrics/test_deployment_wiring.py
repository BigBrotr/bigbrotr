from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from tests.system.deployments.baseline import (
    capture_stack_artifacts,
    create_bundle,
    create_stack,
    record_runtime_plan,
)
from tests.system.deployments.runtime_overrides import (
    BOOTSTRAP_SERVICES,
    configure_runtime_relay_targets,
    prepare_runtime_compose_config,
    start_baseline_relay,
)
from tests.system.harness import MetricsScrapeError, RuntimeAddressPlan, fetch_metrics_snapshot


if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.system.harness import ComposeStack, SystemArtifactBundle


pytestmark = pytest.mark.system


_METRICS_CONFIG_SERVICES = (
    "finder",
    "validator",
    "monitor",
    "synchronizer",
    "refresher",
    "ranker",
    "api",
    "dvm",
    "assertor",
)
_METRICS_HEALTHCHECK_SERVICES = tuple(
    service_name for service_name in _METRICS_CONFIG_SERVICES if service_name != "api"
)
_HOST_PORT_DEFAULTS = {
    "bigbrotr": {
        "finder": "8001",
        "validator": "8002",
        "monitor": "8003",
        "synchronizer": "8004",
        "refresher": "8005",
        "ranker": "8009",
        "api": "8006",
        "dvm": "8007",
        "assertor": "8008",
    },
    "lilbrotr": {
        "finder": "9001",
        "validator": "9002",
        "monitor": "9003",
        "synchronizer": "9004",
        "refresher": "9005",
        "ranker": "9009",
        "api": "9006",
        "dvm": "9007",
        "assertor": "9008",
    },
}
_API_HTTP_HOST_PORT_DEFAULTS = {
    "bigbrotr": "8080",
    "lilbrotr": "8081",
}
_METRICS_ENV_KEYS = {
    "finder": "FINDER_METRICS_PORT",
    "validator": "VALIDATOR_METRICS_PORT",
    "monitor": "MONITOR_METRICS_PORT",
    "synchronizer": "SYNCHRONIZER_METRICS_PORT",
    "refresher": "REFRESHER_METRICS_PORT",
    "ranker": "RANKER_METRICS_PORT",
    "api": "API_METRICS_PORT",
    "dvm": "DVM_METRICS_PORT",
    "assertor": "ASSERTOR_METRICS_PORT",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text())
    assert isinstance(payload, dict)
    return payload


def _wait_until(
    fetch_snapshot: Callable[[], Any],
    *,
    is_ready: Callable[[Any], bool],
    description: str,
    timeout: float = 60.0,
    poll_interval: float = 0.5,
) -> Any:
    deadline = time.monotonic() + timeout
    last_snapshot: Any | None = None
    last_error: MetricsScrapeError | None = None
    while time.monotonic() < deadline:
        try:
            last_snapshot = fetch_snapshot()
        except MetricsScrapeError as exc:
            last_error = exc
        else:
            last_error = None
            if is_ready(last_snapshot):
                return last_snapshot
        time.sleep(poll_interval)
    if last_error is not None:
        raise RuntimeError(f"Timed out waiting for {description}: {last_error}") from last_error
    raise RuntimeError(f"Timed out waiting for {description}: {last_snapshot!r}")


def _capture_assertor_metrics_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    profile: str,
    metrics_text: str,
) -> None:
    bundle.capture_container_logs(
        f"{profile}-assertor",
        stack.run("logs", "--no-color", "assertor", check=False).stdout,
    )
    bundle.write_text_artifact(
        category="observability",
        subdir="observability/metrics",
        name=f"{profile}-assertor-host-metrics",
        contents=metrics_text,
        suffix=".prom",
    )


@pytest.mark.parametrize("profile", ["bigbrotr", "lilbrotr"])
def test_metrics_config_contract_is_exact(profile: str) -> None:
    config_dir = Path(f"deployments/{profile}/config/services")
    actual = {
        service_name: _load_yaml(config_dir / f"{service_name}.yaml").get("metrics")
        for service_name in _METRICS_CONFIG_SERVICES
    }

    assert actual == {
        service_name: {"enabled": True, "host": "0.0.0.0"}
        for service_name in _METRICS_CONFIG_SERVICES
    }
    assert _load_yaml(config_dir / "seeder.yaml").get("metrics") is None


@pytest.mark.parametrize("profile", ["bigbrotr", "lilbrotr"])
def test_compose_metrics_wiring_contract_is_exact(profile: str) -> None:
    compose_data = _load_yaml(Path(f"deployments/{profile}/docker-compose.yaml"))
    services = compose_data["services"]
    assert isinstance(services, dict)

    actual_ports = {
        service_name: services[service_name]["ports"]
        for service_name in _METRICS_CONFIG_SERVICES
        if isinstance(services[service_name], dict)
    }
    expected_ports = {
        service_name: [
            f"127.0.0.1:${{{_METRICS_ENV_KEYS[service_name]}:-{_HOST_PORT_DEFAULTS[profile][service_name]}}}:8000"
        ]
        for service_name in _METRICS_CONFIG_SERVICES
    }
    expected_ports["api"] = [
        f"127.0.0.1:{_API_HTTP_HOST_PORT_DEFAULTS[profile]}:8080",
        f"127.0.0.1:${{{_METRICS_ENV_KEYS['api']}:-{_HOST_PORT_DEFAULTS[profile]['api']}}}:8000",
    ]
    assert actual_ports == expected_ports

    actual_healthchecks = {
        service_name: services[service_name]["healthcheck"]["test"]
        for service_name in _METRICS_HEALTHCHECK_SERVICES
        if isinstance(services[service_name], dict)
    }
    expected_healthcheck = [
        "CMD-SHELL",
        "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/metrics')\"",
    ]
    assert actual_healthchecks == dict.fromkeys(_METRICS_HEALTHCHECK_SERVICES, expected_healthcheck)


@pytest.mark.parametrize("profile", ["bigbrotr", "lilbrotr"])
def test_prometheus_scrape_targets_match_metrics_container_ports(profile: str) -> None:
    prometheus_data = _load_yaml(
        Path(f"deployments/{profile}/monitoring/prometheus/prometheus.yaml")
    )
    scrape_configs = prometheus_data["scrape_configs"]
    assert isinstance(scrape_configs, list)

    actual_targets = {}
    for config in scrape_configs:
        if not isinstance(config, dict):
            continue
        job_name = config.get("job_name")
        static_configs = config.get("static_configs")
        if (
            not isinstance(job_name, str)
            or not isinstance(static_configs, list)
            or not static_configs
        ):
            continue
        first_static = static_configs[0]
        if not isinstance(first_static, dict):
            continue
        targets = first_static.get("targets")
        if isinstance(targets, list):
            actual_targets[job_name] = targets

    expected_targets = {
        service_name: [f"{service_name}:8000"] for service_name in _METRICS_CONFIG_SERVICES
    }
    expected_targets["postgres"] = ["postgres-exporter:9187"]
    expected_targets["prometheus"] = ["localhost:9090"]

    assert actual_targets == expected_targets


@pytest.mark.timeout(900)
@pytest.mark.parametrize("profile", ["bigbrotr", "lilbrotr"])
def test_assertor_metrics_host_port_is_reachable_for_profile(tmp_path: Path, profile: str) -> None:
    bundle = create_bundle(tmp_path, f"{profile}-assertor-metrics-host-port")
    plan = RuntimeAddressPlan.create(
        profile,
        tmp_path / "runtime",
        f"{profile}-assertor-metrics-host-port",
    )
    prepare_runtime_compose_config(plan)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    relay = None
    try:
        stack.up(*BOOTSTRAP_SERVICES, build=True)
        relay = start_baseline_relay(plan)
        configure_runtime_relay_targets(plan, relay)
        stack.up("assertor", build=True)
        stack.wait_until_ready(("assertor",), timeout=180.0)

        snapshot = _wait_until(
            lambda: fetch_metrics_snapshot(f"http://127.0.0.1:{plan.ports.assertor_metrics}"),
            is_ready=lambda current: (
                current.single_value("service_info", service="assertor") == 1.0
            ),
            description=f"{profile} assertor host metrics endpoint",
        )
        _capture_assertor_metrics_artifacts(
            bundle,
            stack,
            profile=profile,
            metrics_text=snapshot.text,
        )
    finally:
        capture_stack_artifacts(
            bundle, stack, services=("postgres", "pgbouncer", "tor", "assertor")
        )
        if relay is not None:
            relay.stop()
        stack.down()

    assert snapshot.single_value("service_info", service="assertor") == 1.0
