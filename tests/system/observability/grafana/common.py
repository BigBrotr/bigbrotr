from __future__ import annotations

import json
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


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text())
    assert isinstance(payload, dict)
    return payload


def _expected_dashboard_provider(profile: str) -> dict[str, object]:
    payload = _load_yaml(
        Path(f"deployments/{profile}/monitoring/grafana/provisioning/dashboards/dashboards.yaml")
    )
    providers = payload["providers"]
    assert isinstance(providers, list)
    assert len(providers) == 1
    provider = providers[0]
    assert isinstance(provider, dict)
    return provider


def _dashboard_json_paths(profile: str) -> tuple[Path, ...]:
    root = Path(f"deployments/{profile}/monitoring/grafana/provisioning/dashboards")
    return tuple(sorted(root.glob("*.json")))


def _panel_titles(panels: object) -> tuple[str, ...]:
    assert isinstance(panels, list)
    titles: list[str] = []
    for panel in panels:
        assert isinstance(panel, dict)
        title = panel.get("title")
        if isinstance(title, str):
            titles.append(title)
        nested_panels = panel.get("panels", [])
        titles.extend(_panel_titles(nested_panels))
    return tuple(titles)


def _expected_dashboard_definitions(profile: str) -> dict[str, dict[str, object]]:
    definitions: dict[str, dict[str, object]] = {}
    for path in _dashboard_json_paths(profile):
        payload = _load_json(path)
        uid = payload["uid"]
        title = payload["title"]
        tags = payload["tags"]
        schema_version = payload["schemaVersion"]
        version = payload["version"]
        assert isinstance(uid, str)
        assert isinstance(title, str)
        assert isinstance(tags, list)
        assert isinstance(schema_version, int)
        assert isinstance(version, int)
        definitions[uid] = {
            "file_name": path.name,
            "title": title,
            "tags": tuple(tags),
            "schema_version": schema_version,
            "version": version,
            "panel_titles": _panel_titles(payload.get("panels", [])),
        }
    return definitions


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


def collect_dashboard_provisioning_snapshot(
    grafana: GrafanaApi,
    *,
    expected_uids: tuple[str, ...],
) -> dict[str, object]:
    dashboards = grafana.dashboards()
    rows = _dashboards_by_uid(dashboards)
    dashboard_details: dict[str, object] = {}
    for uid in expected_uids:
        if uid in rows:
            dashboard_details[uid] = grafana.dashboard(uid)
    return {
        "health": grafana.health(),
        "dashboards": dashboards,
        "dashboard_details": dashboard_details,
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


def capture_dashboard_provisioning_artifacts(
    bundle: SystemArtifactBundle,
    *,
    plan: RuntimeAddressPlan,
    snapshot: dict[str, object],
) -> None:
    bundle.write_text_artifact(
        category="observability",
        subdir="observability/grafana",
        name="dashboard-provider-runtime",
        contents=(
            plan.runtime_root
            / "monitoring"
            / "grafana"
            / "provisioning"
            / "dashboards"
            / "dashboards.yaml"
        ).read_text(),
        suffix=".yaml",
    )
    bundle.capture_grafana_response(
        "dashboards",
        status_code=200,
        payload=snapshot["dashboards"],
    )
    dashboard_details = snapshot["dashboard_details"]
    assert isinstance(dashboard_details, dict)
    for uid, payload in dashboard_details.items():
        bundle.capture_grafana_response(
            f"dashboard-{uid}",
            status_code=200,
            payload=payload,
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


def _dashboards_by_uid(payload: object) -> dict[str, dict[str, object]]:
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


def dashboard_ready_snapshot(
    current: dict[str, object],
    *,
    expected_uids: tuple[str, ...],
) -> bool:
    health = current["health"]
    dashboards = _dashboards_by_uid(current["dashboards"])
    dashboard_details = current["dashboard_details"]
    assert isinstance(dashboard_details, dict)
    return (
        isinstance(health, dict)
        and health.get("database") == "ok"
        and tuple(sorted(dashboards)) == expected_uids
        and tuple(sorted(dashboard_details)) == expected_uids
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


def assert_dashboard_provisioning_contract(snapshot: dict[str, object], *, profile: str) -> None:
    health = snapshot["health"]
    assert isinstance(health, dict)
    assert health["database"] == "ok"

    expected_provider = _expected_dashboard_provider(profile)
    assert expected_provider == {
        "name": "BigBrotr" if profile == "bigbrotr" else "LilBrotr",
        "orgId": 1,
        "folder": "",
        "type": "file",
        "disableDeletion": False,
        "editable": False,
        "options": {"path": "/etc/grafana/provisioning/dashboards"},
    }

    expected_dashboards = _expected_dashboard_definitions(profile)
    dashboard_rows = _dashboards_by_uid(snapshot["dashboards"])
    assert tuple(sorted(dashboard_rows)) == tuple(sorted(expected_dashboards))

    dashboard_details = snapshot["dashboard_details"]
    assert isinstance(dashboard_details, dict)
    assert tuple(sorted(dashboard_details)) == tuple(sorted(expected_dashboards))

    for uid, expected in expected_dashboards.items():
        row = dashboard_rows[uid]
        assert row["uid"] == uid
        assert row["title"] == expected["title"]
        assert row["type"] == "dash-db"
        assert tuple(sorted(row["tags"])) == tuple(sorted(expected["tags"]))
        assert row["url"].startswith(f"/d/{uid}/")

        detail = dashboard_details[uid]
        assert isinstance(detail, dict)
        dashboard = detail["dashboard"]
        meta = detail["meta"]
        assert isinstance(dashboard, dict)
        assert isinstance(meta, dict)
        assert dashboard["uid"] == uid
        assert dashboard["title"] == expected["title"]
        assert tuple(dashboard["tags"]) == expected["tags"]
        assert dashboard["schemaVersion"] == expected["schema_version"]
        assert dashboard["version"] == expected["version"]
        assert _panel_titles(dashboard["panels"]) == expected["panel_titles"]
        assert meta["type"] == "db"


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


def certify_grafana_dashboard_provisioning_contract(
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
        expected_uids = tuple(sorted(_expected_dashboard_definitions(profile)))
        snapshot = wait_until(
            lambda: collect_dashboard_provisioning_snapshot(
                grafana,
                expected_uids=expected_uids,
            ),
            is_ready=lambda current: dashboard_ready_snapshot(
                current,
                expected_uids=expected_uids,
            ),
            description=f"{profile} Grafana dashboard provisioning readiness",
        )
        capture_dashboard_provisioning_artifacts(bundle, plan=plan, snapshot=snapshot)
        assert_dashboard_provisioning_contract(snapshot, profile=profile)
    finally:
        if bundle is not None and stack is not None:
            from tests.system.deployments.baseline import capture_stack_artifacts

            capture_stack_artifacts(bundle, stack)
        if relay is not None:
            relay.stop()
        if stack is not None:
            stack.down(timeout=30)
