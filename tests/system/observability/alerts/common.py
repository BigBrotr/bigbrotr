from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
from tests.system.harness import RuntimeAddressPlan
from tests.system.observability.prometheus.common import (
    collect_prometheus_snapshot,
    prometheus_api,
    ready_snapshot,
    single_vector_row,
    targets_by_job,
    vector_result,
    wait_until,
)


if TYPE_CHECKING:
    from pathlib import Path


def _load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text())
    assert isinstance(payload, dict)
    return payload


def _runtime_prometheus_paths(plan: RuntimeAddressPlan) -> tuple[Path, Path]:
    monitoring_root = plan.runtime_root / "monitoring" / "prometheus"
    return monitoring_root / "prometheus.yaml", monitoring_root / "rules" / "alerts.yml"


def _tune_runtime_alert_timing(
    plan: RuntimeAddressPlan,
    *,
    alert_name: str,
    evaluation_interval: str = "1s",
    scrape_interval: str = "1s",
    for_duration: str = "1s",
) -> None:
    prometheus_path, alerts_path = _runtime_prometheus_paths(plan)

    prometheus_config = _load_yaml(prometheus_path)
    global_config = prometheus_config.get("global")
    assert isinstance(global_config, dict)
    global_config["scrape_interval"] = scrape_interval
    global_config["evaluation_interval"] = evaluation_interval

    scrape_configs = prometheus_config.get("scrape_configs")
    assert isinstance(scrape_configs, list)
    for scrape_config in scrape_configs:
        assert isinstance(scrape_config, dict)
        scrape_config["scrape_interval"] = scrape_interval

    prometheus_path.write_text(yaml.safe_dump(prometheus_config, sort_keys=False))

    alerts_config = _load_yaml(alerts_path)
    groups = alerts_config.get("groups")
    assert isinstance(groups, list)

    for group in groups:
        assert isinstance(group, dict)
        rules = group.get("rules")
        if not isinstance(rules, list):
            continue
        for rule in rules:
            assert isinstance(rule, dict)
            if rule.get("alert") == alert_name:
                rule["for"] = for_duration
                alerts_path.write_text(yaml.safe_dump(alerts_config, sort_keys=False))
                return

    raise RuntimeError(f"Could not find alert rule {alert_name!r} in runtime alerts config")


def _active_alerts(payload: object) -> tuple[dict[str, object], ...]:
    assert isinstance(payload, dict)
    assert payload["status"] == "success"

    data = payload["data"]
    assert isinstance(data, dict)
    alerts = data["alerts"]
    assert isinstance(alerts, list)
    normalized: list[dict[str, object]] = []
    for alert in alerts:
        assert isinstance(alert, dict)
        normalized.append(alert)
    return tuple(normalized)


def _find_alert(payload: object, *, alert_name: str, job: str) -> dict[str, object] | None:
    for alert in _active_alerts(payload):
        labels = alert.get("labels")
        if not isinstance(labels, dict):
            continue
        if labels.get("alertname") == alert_name and labels.get("job") == job:
            return alert
    return None


def _single_vector_value(payload: object) -> float | None:
    rows = vector_result(payload)
    if len(rows) != 1:
        return None
    return rows[0]["value"]


def _alert_snapshot(prometheus: Any, *, alert_name: str, job: str) -> dict[str, object]:
    return {
        "targets": prometheus.targets(),
        "alerts": prometheus.alerts(),
        "up": prometheus.query(f'up{{job="{job}"}}'),
        "firing": prometheus.query(
            f'ALERTS{{alertname="{alert_name}",job="{job}",alertstate="firing"}}'
        ),
    }


def _capture_alert_artifacts(
    bundle: Any,
    plan: RuntimeAddressPlan,
    *,
    baseline: dict[str, object],
    firing: dict[str, object],
    resolved: dict[str, object],
) -> None:
    prometheus_path, alerts_path = _runtime_prometheus_paths(plan)
    bundle.write_text_artifact(
        category="observability",
        subdir="observability/alerts",
        name="runtime-prometheus-config",
        contents=prometheus_path.read_text(),
        suffix=".yaml",
    )
    bundle.write_text_artifact(
        category="observability",
        subdir="observability/alerts",
        name="runtime-alert-rules",
        contents=alerts_path.read_text(),
        suffix=".yaml",
    )
    for name, snapshot in (
        ("baseline", baseline),
        ("firing", firing),
        ("resolved", resolved),
    ):
        bundle.write_json_artifact(
            category="observability",
            subdir="observability/alerts",
            name=f"{name}-targets",
            payload=snapshot["targets"],
        )
        bundle.write_json_artifact(
            category="observability",
            subdir="observability/alerts",
            name=f"{name}-alerts",
            payload=snapshot["alerts"],
        )
        bundle.write_json_artifact(
            category="observability",
            subdir="observability/alerts",
            name=f"{name}-up-query",
            payload=snapshot["up"],
        )
        bundle.write_json_artifact(
            category="observability",
            subdir="observability/alerts",
            name=f"{name}-firing-query",
            payload=snapshot["firing"],
        )


def certify_service_down_alert_contract(
    tmp_path: Path,
    *,
    profile: str,
    run_name: str,
    slot: int,
    stopped_service: str,
) -> None:
    alert_name = "ServiceDown"
    bundle = None
    stack = None
    relay = None

    try:
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
        wait_until(
            lambda: collect_prometheus_snapshot(prometheus),
            is_ready=ready_snapshot,
            description=f"{profile} Prometheus target and series readiness",
        )

        baseline = wait_until(
            lambda: _alert_snapshot(prometheus, alert_name=alert_name, job=stopped_service),
            is_ready=lambda current: (
                targets_by_job(current["targets"])[stopped_service]["health"] == "up"
                and single_vector_row(current["up"])["value"] == 1.0
                and _find_alert(current["alerts"], alert_name=alert_name, job=stopped_service)
                is None
                and vector_result(current["firing"]) == ()
            ),
            description=f"{profile} baseline alert state for {stopped_service}",
        )

        stack.run("stop", stopped_service)
        stack.wait_until_state(stopped_service, state="exited", all_services=True, timeout=60.0)

        firing = wait_until(
            lambda: _alert_snapshot(prometheus, alert_name=alert_name, job=stopped_service),
            is_ready=lambda current: (
                targets_by_job(current["targets"])[stopped_service]["health"] == "down"
                and single_vector_row(current["up"])["value"] == 0.0
                and _single_vector_value(current["firing"]) == 1.0
                and (
                    alert := _find_alert(
                        current["alerts"],
                        alert_name=alert_name,
                        job=stopped_service,
                    )
                )
                is not None
                and alert["state"] == "firing"
            ),
            description=f"{profile} ServiceDown firing state for {stopped_service}",
            timeout=120.0,
        )

        alert = _find_alert(firing["alerts"], alert_name=alert_name, job=stopped_service)
        assert alert is not None
        labels = alert["labels"]
        annotations = alert["annotations"]
        assert isinstance(labels, dict)
        assert isinstance(annotations, dict)
        assert labels["severity"] == "critical"
        assert labels["job"] == stopped_service
        assert labels["instance"] == f"{stopped_service}:8000"
        assert annotations["summary"] == f"{stopped_service} is down"
        assert f"{stopped_service}:8000" in str(annotations["description"])
        assert alert["activeAt"]

        stack.up(stopped_service)
        stack.wait_until_ready((stopped_service,), timeout=120.0)

        resolved = wait_until(
            lambda: _alert_snapshot(prometheus, alert_name=alert_name, job=stopped_service),
            is_ready=lambda current: (
                targets_by_job(current["targets"])[stopped_service]["health"] == "up"
                and single_vector_row(current["up"])["value"] == 1.0
                and _find_alert(current["alerts"], alert_name=alert_name, job=stopped_service)
                is None
                and vector_result(current["firing"]) == ()
            ),
            description=f"{profile} ServiceDown resolution state for {stopped_service}",
            timeout=120.0,
        )

        _capture_alert_artifacts(
            bundle,
            plan,
            baseline=baseline,
            firing=firing,
            resolved=resolved,
        )
    finally:
        if bundle is not None and stack is not None:
            capture_stack_artifacts(bundle, stack)
        if relay is not None:
            relay.stop()
        if stack is not None:
            stack.down()
