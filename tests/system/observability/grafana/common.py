from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from tests.system.harness import GrafanaApi, RuntimeAddressPlan, SystemArtifactBundle
from tests.system.harness.compose import build_test_env_values
from tests.system.observability.prometheus.common import start_prometheus_stack, wait_until


if TYPE_CHECKING:
    from tests.system.harness import ComposeStack, LocalRelayRuntime


_EXPECTED_DATASOURCE = {
    "name": "Prometheus",
    "type": "prometheus",
    "uid": "prometheus",
    "access": "proxy",
    "url": "http://prometheus:9090",
    "isDefault": True,
    "readOnly": True,
}


def _load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text())
    assert isinstance(payload, dict)
    return payload


def _expected_datasource_config(profile: str) -> dict[str, object]:
    payload = _load_yaml(
        Path(f"deployments/{profile}/monitoring/grafana/provisioning/datasources/prometheus.yaml")
    )
    datasources = payload["datasources"]
    assert isinstance(datasources, list)
    assert len(datasources) == 1
    datasource = datasources[0]
    assert isinstance(datasource, dict)
    return datasource


def grafana_api(plan: RuntimeAddressPlan) -> GrafanaApi:
    env_values = build_test_env_values(plan.profile, plan.project_name)
    return GrafanaApi(
        f"http://127.0.0.1:{plan.ports.grafana}",
        username="admin",
        password=env_values["GRAFANA_PASSWORD"],
    )


def collect_grafana_snapshot(grafana: GrafanaApi) -> dict[str, object]:
    return {
        "health": grafana.health(),
        "datasources": grafana.datasources(),
        "datasource": grafana.datasource("prometheus"),
        "datasource_health": grafana.datasource_health("prometheus"),
    }


def capture_grafana_artifacts(
    bundle: SystemArtifactBundle,
    *,
    snapshot: dict[str, object],
) -> None:
    bundle.capture_grafana_response(
        "health",
        status_code=200,
        payload=snapshot["health"],
    )
    bundle.capture_grafana_response(
        "datasources",
        status_code=200,
        payload=snapshot["datasources"],
    )
    bundle.capture_grafana_response(
        "datasource",
        status_code=200,
        payload=snapshot["datasource"],
    )
    bundle.capture_grafana_response(
        "datasource-health",
        status_code=200,
        payload=snapshot["datasource_health"],
    )


def _datasources_by_uid(payload: object) -> dict[str, dict[str, object]]:
    assert isinstance(payload, list)
    rows: dict[str, dict[str, object]] = {}
    for row in payload:
        assert isinstance(row, dict)
        uid = row["uid"]
        assert isinstance(uid, str)
        rows[uid] = row
    return rows


def ready_snapshot(current: dict[str, object]) -> bool:
    health = current["health"]
    datasource = current["datasource"]
    datasource_health = current["datasource_health"]
    datasources = _datasources_by_uid(current["datasources"])
    return (
        datasources.keys() == {"prometheus"}
        and datasources["prometheus"].get("uid") == "prometheus"
        and isinstance(health, dict)
        and health.get("database") == "ok"
        and isinstance(datasource, dict)
        and datasource.get("uid") == "prometheus"
        and datasource.get("type") == "prometheus"
        and datasource.get("url") == "http://prometheus:9090"
        and isinstance(datasource_health, dict)
        and datasource_health.get("status") == "OK"
    )


def assert_datasource_contract(snapshot: dict[str, object], *, profile: str) -> None:
    health = snapshot["health"]
    assert isinstance(health, dict)
    assert health["database"] == "ok"

    datasources = _datasources_by_uid(snapshot["datasources"])
    assert set(datasources) == {"prometheus"}
    datasource_list_row = datasources["prometheus"]
    datasource_row = snapshot["datasource"]
    assert isinstance(datasource_row, dict)

    expected_config = _expected_datasource_config(profile)
    for key, value in _EXPECTED_DATASOURCE.items():
        assert datasource_list_row[key] == value
        assert datasource_row[key] == value

    assert expected_config == {
        "name": datasource_row["name"],
        "type": datasource_row["type"],
        "uid": datasource_row["uid"],
        "access": datasource_row["access"],
        "url": datasource_row["url"],
        "isDefault": datasource_row["isDefault"],
        "editable": False,
    }

    datasource_health = snapshot["datasource_health"]
    assert isinstance(datasource_health, dict)
    assert datasource_health["status"] == "OK"
    assert datasource_health["message"]


def certify_grafana_datasource_contract(
    tmp_path: Path,
    *,
    profile: str,
    run_name: str,
    slot: int,
) -> None:
    bundle: SystemArtifactBundle | None = None
    stack: ComposeStack | None = None
    relay: LocalRelayRuntime | None = None

    try:
        bundle, plan, stack, relay = start_prometheus_stack(
            tmp_path,
            profile=profile,
            run_name=run_name,
            slot=slot,
        )
        grafana = grafana_api(plan)
        snapshot = wait_until(
            lambda: collect_grafana_snapshot(grafana),
            is_ready=ready_snapshot,
            description=f"{profile} Grafana datasource provisioning readiness",
        )
        capture_grafana_artifacts(bundle, snapshot=snapshot)
        assert_datasource_contract(snapshot, profile=profile)
    finally:
        if bundle is not None and stack is not None:
            from tests.system.deployments.baseline import capture_stack_artifacts

            capture_stack_artifacts(bundle, stack)
        if relay is not None:
            relay.stop()
        if stack is not None:
            stack.down()
