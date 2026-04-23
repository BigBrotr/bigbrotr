from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from tests.system.deployments.baseline import (
    CONTINUOUS_SERVICES,
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
from tests.system.harness import (
    AlertmanagerApi,
    PrometheusApi,
    RuntimeAddressPlan,
    SystemArtifactBundle,
)
from tests.system.observability.alerts.common import _tune_runtime_alert_timing
from tests.system.observability.prometheus.common import (
    collect_prometheus_snapshot,
    ready_snapshot,
    wait_until,
)


if TYPE_CHECKING:
    from tests.system.harness import ComposeStack, LocalRelayRuntime


def _load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text())
    assert isinstance(payload, dict)
    return payload


def _expected_alertmanager_config(profile: str) -> dict[str, object]:
    return _load_yaml(Path(f"deployments/{profile}/monitoring/alertmanager/alertmanager.yml"))


def _runtime_alertmanager_config_path(plan: RuntimeAddressPlan) -> Path:
    return plan.runtime_root / "monitoring" / "alertmanager" / "alertmanager.yml"


def prometheus_api(plan: RuntimeAddressPlan) -> PrometheusApi:
    return PrometheusApi(f"http://127.0.0.1:{plan.ports.prometheus}")


def alertmanager_api(plan: RuntimeAddressPlan) -> AlertmanagerApi:
    return AlertmanagerApi(f"http://127.0.0.1:{plan.ports.alertmanager}")


def _active_alerts(payload: object) -> tuple[dict[str, object], ...]:
    assert isinstance(payload, list)
    alerts: list[dict[str, object]] = []
    for alert in payload:
        assert isinstance(alert, dict)
        alerts.append(alert)
    return tuple(alerts)


def _find_alert(payload: object, *, alert_name: str, job: str) -> dict[str, object] | None:
    for alert in _active_alerts(payload):
        labels = alert.get("labels")
        if not isinstance(labels, dict):
            continue
        if labels.get("alertname") == alert_name and labels.get("job") == job:
            return alert
    return None


def collect_alertmanager_snapshot(
    alertmanager: AlertmanagerApi,
    prometheus: PrometheusApi,
    *,
    alert_name: str,
    job: str,
) -> dict[str, object]:
    return {
        "health": alertmanager.health(),
        "status": alertmanager.status(),
        "alerts": alertmanager.alerts(),
        "prometheus_firing": prometheus.query(
            f'ALERTS{{alertname="{alert_name}",job="{job}",alertstate="firing"}}'
        ),
    }


def capture_alertmanager_artifacts(
    bundle: SystemArtifactBundle,
    plan: RuntimeAddressPlan,
    *,
    baseline: dict[str, object],
    firing: dict[str, object],
) -> None:
    bundle.write_text_artifact(
        category="observability",
        subdir="observability/alertmanager",
        name="runtime-config",
        contents=_runtime_alertmanager_config_path(plan).read_text(),
        suffix=".yaml",
    )
    for name, snapshot in (("baseline", baseline), ("firing", firing)):
        bundle.capture_alertmanager_response(
            name=f"{name}-status", status_code=200, payload=snapshot["status"]
        )
        bundle.capture_alertmanager_response(
            name=f"{name}-alerts", status_code=200, payload=snapshot["alerts"]
        )
        bundle.write_text_artifact(
            category="observability",
            subdir="observability/alertmanager",
            name=f"{name}-health",
            contents=snapshot["health"],
            suffix=".txt",
        )
        bundle.write_json_artifact(
            category="observability",
            subdir="observability/alertmanager",
            name=f"{name}-prometheus-firing",
            payload=snapshot["prometheus_firing"],
        )


def _status_dump(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _prepare_alertmanager_stack(
    tmp_path: Path,
    *,
    profile: str,
    run_name: str,
    slot: int,
    alert_name: str,
) -> tuple[
    SystemArtifactBundle,
    RuntimeAddressPlan,
    ComposeStack,
    LocalRelayRuntime,
    PrometheusApi,
    AlertmanagerApi,
]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create(profile, tmp_path / "runtime", run_name, slot=slot)
    prepare_runtime_compose_config(plan)
    _tune_runtime_alert_timing(plan, alert_name=alert_name)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    stack.up(*BOOTSTRAP_SERVICES, build=True)
    relay = start_baseline_relay(plan)
    configure_runtime_relay_targets(plan, relay)
    stack.up(build=True)
    stack.wait_until_ready(CONTINUOUS_SERVICES)

    prometheus = prometheus_api(plan)
    alertmanager = alertmanager_api(plan)
    wait_until(
        lambda: collect_prometheus_snapshot(prometheus),
        is_ready=ready_snapshot,
        description=f"{profile} Prometheus readiness before Alertmanager routing",
    )
    return bundle, plan, stack, relay, prometheus, alertmanager


def _wait_for_baseline_state(
    *,
    profile: str,
    alert_name: str,
    stopped_service: str,
    alertmanager: AlertmanagerApi,
    prometheus: PrometheusApi,
) -> dict[str, object]:
    return wait_until(
        lambda: collect_alertmanager_snapshot(
            alertmanager,
            prometheus,
            alert_name=alert_name,
            job=stopped_service,
        ),
        is_ready=lambda current: (
            current["health"] == "OK"
            and _find_alert(current["alerts"], alert_name=alert_name, job=stopped_service) is None
        ),
        description=f"{profile} Alertmanager baseline routing state",
    )


def _assert_expected_routing_config(
    baseline: dict[str, object],
    *,
    profile: str,
) -> None:
    baseline_status = _status_dump(baseline["status"])
    expected_config = _expected_alertmanager_config(profile)
    assert expected_config["global"] == {"resolve_timeout": "5m"}
    assert expected_config["route"]["receiver"] == "default"
    assert expected_config["route"]["group_by"] == ["alertname", "service"]
    assert expected_config["route"]["routes"] == [
        {
            "match": {"severity": "critical"},
            "receiver": "default",
            "repeat_interval": "1h",
        }
    ]
    assert expected_config["receivers"] == [{"name": "default"}]
    assert "default" in baseline_status
    assert "resolve_timeout" in baseline_status
    assert "group_wait" in baseline_status


def _wait_for_routed_alert(
    *,
    profile: str,
    alert_name: str,
    stopped_service: str,
    alertmanager: AlertmanagerApi,
    prometheus: PrometheusApi,
) -> dict[str, object]:
    return wait_until(
        lambda: collect_alertmanager_snapshot(
            alertmanager,
            prometheus,
            alert_name=alert_name,
            job=stopped_service,
        ),
        is_ready=lambda current: (
            _find_alert(current["alerts"], alert_name=alert_name, job=stopped_service) is not None
        ),
        description=f"{profile} Alertmanager receipt for {alert_name}",
        timeout=120.0,
    )


def _assert_received_alert(
    firing: dict[str, object],
    *,
    alert_name: str,
    stopped_service: str,
) -> None:
    alert = _find_alert(firing["alerts"], alert_name=alert_name, job=stopped_service)
    assert alert is not None
    labels = alert["labels"]
    status = alert["status"]
    receivers = alert["receivers"]
    assert isinstance(labels, dict)
    assert isinstance(status, dict)
    assert isinstance(receivers, list)
    assert labels["alertname"] == alert_name
    assert labels["severity"] == "critical"
    assert labels["job"] == stopped_service
    assert status["state"] == "active"
    assert [receiver["name"] for receiver in receivers] == ["default"]


def certify_alertmanager_routing_contract(
    tmp_path: Path,
    *,
    profile: str,
    run_name: str,
    slot: int,
    stopped_service: str = "validator",
) -> None:
    alert_name = "ServiceDown"
    bundle: SystemArtifactBundle | None = None
    stack: ComposeStack | None = None
    relay: LocalRelayRuntime | None = None

    try:
        bundle, plan, stack, relay, prometheus, alertmanager = _prepare_alertmanager_stack(
            tmp_path,
            profile=profile,
            run_name=run_name,
            slot=slot,
            alert_name=alert_name,
        )
        baseline = _wait_for_baseline_state(
            profile=profile,
            alert_name=alert_name,
            stopped_service=stopped_service,
            alertmanager=alertmanager,
            prometheus=prometheus,
        )
        _assert_expected_routing_config(baseline, profile=profile)

        stack.run("stop", stopped_service)
        stack.wait_until_state(stopped_service, state="exited", all_services=True, timeout=60.0)

        firing = _wait_for_routed_alert(
            profile=profile,
            alert_name=alert_name,
            stopped_service=stopped_service,
            alertmanager=alertmanager,
            prometheus=prometheus,
        )
        _assert_received_alert(firing, alert_name=alert_name, stopped_service=stopped_service)
        capture_alertmanager_artifacts(bundle, plan, baseline=baseline, firing=firing)
    finally:
        if bundle is not None and stack is not None:
            capture_stack_artifacts(bundle, stack)
        if relay is not None:
            relay.stop()
        if stack is not None:
            stack.down(timeout=30)
