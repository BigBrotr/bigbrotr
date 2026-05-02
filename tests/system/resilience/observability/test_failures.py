from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tests.system.deployments.baseline import (
    CONTINUOUS_SERVICES,
    create_bundle,
    create_stack,
    record_runtime_plan,
    teardown_stack_runtime,
)
from tests.system.deployments.runtime_overrides import (
    BOOTSTRAP_SERVICES,
    configure_runtime_relay_targets,
    prepare_runtime_compose_config,
    start_baseline_relay,
)
from tests.system.harness import RuntimeAddressPlan, SystemArtifactBundle
from tests.system.harness.observability import ObservabilityApiError
from tests.system.observability.alertmanager.common import alertmanager_api
from tests.system.observability.alerts.common import _tune_runtime_alert_timing
from tests.system.observability.grafana.common import (
    collect_grafana_snapshot,
    grafana_api,
)
from tests.system.observability.grafana.common import (
    ready_snapshot as ready_grafana_snapshot,
)
from tests.system.observability.prometheus.common import (
    collect_prometheus_snapshot,
    prometheus_api,
    targets_by_job,
    vector_result,
    wait_until,
)
from tests.system.observability.prometheus.common import (
    ready_snapshot as ready_prometheus_snapshot,
)


if TYPE_CHECKING:
    from pathlib import Path

    from tests.system.harness import (
        AlertmanagerApi,
        ComposeStack,
        GrafanaApi,
        LocalRelayRuntime,
        PrometheusApi,
    )


pytestmark = [pytest.mark.system, pytest.mark.timeout(1200)]


def _prepare_observability_stack(
    tmp_path: Path,
    *,
    run_name: str,
    slot: int,
    tune_alerts: bool = False,
) -> tuple[
    SystemArtifactBundle,
    RuntimeAddressPlan,
    ComposeStack,
    LocalRelayRuntime,
    PrometheusApi,
    GrafanaApi,
    AlertmanagerApi,
]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", run_name, slot=slot)
    prepare_runtime_compose_config(plan)
    if tune_alerts:
        _tune_runtime_alert_timing(plan, alert_name="ServiceDown")
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    stack.up(*BOOTSTRAP_SERVICES)
    relay = start_baseline_relay(plan)
    configure_runtime_relay_targets(plan, relay)
    stack.up()
    stack.wait_until_ready(CONTINUOUS_SERVICES)

    prometheus = prometheus_api(plan)
    grafana = grafana_api(plan)
    alertmanager = alertmanager_api(plan)

    wait_until(
        lambda: collect_prometheus_snapshot(prometheus),
        is_ready=ready_prometheus_snapshot,
        description="bigbrotr Prometheus readiness before observability resilience drill",
    )
    wait_until(
        lambda: collect_grafana_snapshot(grafana),
        is_ready=ready_grafana_snapshot,
        description="bigbrotr Grafana readiness before observability resilience drill",
    )
    wait_until(
        alertmanager.health,
        is_ready=lambda current: current == "OK",
        description="bigbrotr Alertmanager readiness before observability resilience drill",
    )

    return bundle, plan, stack, relay, prometheus, grafana, alertmanager


def _probe(fetch: Any) -> dict[str, object]:
    try:
        return {"ok": True, "value": fetch()}
    except ObservabilityApiError as exc:
        return {"ok": False, "error": str(exc)}


def _capture_snapshot(
    bundle: SystemArtifactBundle,
    name: str,
    payload: object,
) -> None:
    bundle.write_json_artifact(
        category="observability",
        subdir="observability/resilience",
        name=name,
        payload=payload,
    )


def _single_vector_value(payload: object) -> float | None:
    rows = vector_result(payload)
    if len(rows) != 1:
        return None
    return rows[0]["value"]


def _find_alert(payload: object, *, alert_name: str, job: str) -> dict[str, object] | None:
    assert isinstance(payload, dict)
    assert payload["status"] == "success"
    data = payload["data"]
    assert isinstance(data, dict)
    alerts = data["alerts"]
    assert isinstance(alerts, list)
    for alert in alerts:
        assert isinstance(alert, dict)
        labels = alert.get("labels")
        if not isinstance(labels, dict):
            continue
        if labels.get("alertname") == alert_name and labels.get("job") == job:
            return alert
    return None


def test_prometheus_outage_degrades_grafana_datasource_and_recovers(tmp_path: Path) -> None:
    bundle = None
    stack = None
    relay = None

    try:
        bundle, _plan, stack, relay, prometheus, grafana, alertmanager = (
            _prepare_observability_stack(
                tmp_path,
                run_name="observability-prometheus-outage",
                slot=75,
            )
        )

        baseline = {
            "prometheus": collect_prometheus_snapshot(prometheus),
            "grafana": collect_grafana_snapshot(grafana),
            "alertmanager_health": alertmanager.health(),
        }
        _capture_snapshot(bundle, "prometheus-outage-baseline", baseline)

        stack.run("stop", "prometheus")
        stack.wait_until_state("prometheus", state="exited", all_services=True, timeout=60.0)

        outage = wait_until(
            lambda: {
                "prometheus_health": _probe(prometheus.health),
                "prometheus_ready": _probe(prometheus.ready),
                "grafana_health": _probe(grafana.health),
                "grafana_datasource_health": _probe(
                    lambda: grafana.datasource_health("prometheus")
                ),
                "alertmanager_health": _probe(alertmanager.health),
            },
            is_ready=lambda current: (
                current["prometheus_health"]["ok"] is False
                and current["prometheus_ready"]["ok"] is False
                and current["grafana_health"]["ok"] is True
                and isinstance(current["grafana_health"]["value"], dict)
                and current["grafana_health"]["value"].get("database") == "ok"
                and current["grafana_datasource_health"]["ok"] is False
                and current["alertmanager_health"]["ok"] is True
                and current["alertmanager_health"]["value"] == "OK"
            ),
            description="Prometheus outage semantics",
            timeout=120.0,
        )
        _capture_snapshot(bundle, "prometheus-outage-outage", outage)

        assert "Observability request failed" in str(outage["prometheus_health"]["error"])
        assert "Observability request failed" in str(outage["grafana_datasource_health"]["error"])

        stack.up("prometheus")
        stack.wait_until_ready(("prometheus",), timeout=120.0)

        recovery = wait_until(
            lambda: {
                "prometheus": collect_prometheus_snapshot(prometheus),
                "grafana": collect_grafana_snapshot(grafana),
                "alertmanager_health": alertmanager.health(),
            },
            is_ready=lambda current: (
                ready_prometheus_snapshot(current["prometheus"])
                and ready_grafana_snapshot(current["grafana"])
                and current["alertmanager_health"] == "OK"
            ),
            description="Prometheus outage recovery",
            timeout=180.0,
        )
        _capture_snapshot(bundle, "prometheus-outage-recovery", recovery)
    finally:
        teardown_stack_runtime(bundle, stack, relay=relay, down_timeout=30)


def test_postgres_exporter_outage_surfaces_honest_prometheus_target_state(tmp_path: Path) -> None:
    bundle = None
    stack = None
    relay = None

    try:
        bundle, _plan, stack, relay, prometheus, grafana, _alertmanager = (
            _prepare_observability_stack(
                tmp_path,
                run_name="observability-exporter-outage",
                slot=76,
            )
        )

        baseline = {
            "prometheus": collect_prometheus_snapshot(prometheus),
            "grafana": collect_grafana_snapshot(grafana),
        }
        _capture_snapshot(bundle, "exporter-outage-baseline", baseline)

        stack.run("stop", "postgres-exporter")
        stack.wait_until_state("postgres-exporter", state="exited", all_services=True, timeout=60.0)

        outage = wait_until(
            lambda: {
                "prometheus": collect_prometheus_snapshot(prometheus),
                "grafana": collect_grafana_snapshot(grafana),
            },
            is_ready=lambda current: (
                targets_by_job(current["prometheus"]["targets"])["postgres"]["health"] == "down"
                and {
                    row["metric"]["job"]: row["value"]
                    for row in vector_result(current["prometheus"]["up"])
                }.get("postgres")
                == 0.0
                and {
                    row["metric"]["job"]: row["value"]
                    for row in vector_result(current["prometheus"]["up"])
                }.get("prometheus")
                == 1.0
                and ready_grafana_snapshot(current["grafana"])
            ),
            description="postgres-exporter outage semantics",
            timeout=120.0,
        )
        _capture_snapshot(bundle, "exporter-outage-outage", outage)

        other_jobs = targets_by_job(outage["prometheus"]["targets"])
        assert other_jobs["postgres"]["lastError"]
        for job_name, target in other_jobs.items():
            if job_name == "postgres":
                continue
            assert target["health"] == "up"

        stack.up("postgres-exporter")
        stack.wait_until_ready(("postgres-exporter",), timeout=120.0)

        recovery = wait_until(
            lambda: {
                "prometheus": collect_prometheus_snapshot(prometheus),
                "grafana": collect_grafana_snapshot(grafana),
            },
            is_ready=lambda current: (
                ready_prometheus_snapshot(current["prometheus"])
                and ready_grafana_snapshot(current["grafana"])
            ),
            description="postgres-exporter outage recovery",
            timeout=180.0,
        )
        _capture_snapshot(bundle, "exporter-outage-recovery", recovery)
    finally:
        teardown_stack_runtime(bundle, stack, relay=relay, down_timeout=30)


def test_alertmanager_outage_preserves_local_alert_firing_and_routes_after_recovery(
    tmp_path: Path,
) -> None:
    bundle = None
    stack = None
    relay = None

    try:
        bundle, _plan, stack, relay, prometheus, _grafana, alertmanager = (
            _prepare_observability_stack(
                tmp_path,
                run_name="observability-alertmanager-outage",
                slot=77,
                tune_alerts=True,
            )
        )

        baseline = {
            "alertmanager_health": alertmanager.health(),
            "prometheus_alerts": prometheus.alerts(),
            "prometheus_firing": prometheus.query(
                'ALERTS{alertname="ServiceDown",job="validator",alertstate="firing"}'
            ),
        }
        _capture_snapshot(bundle, "alertmanager-outage-baseline", baseline)
        assert baseline["alertmanager_health"] == "OK"
        assert (
            _find_alert(baseline["prometheus_alerts"], alert_name="ServiceDown", job="validator")
            is None
        )
        assert vector_result(baseline["prometheus_firing"]) == ()

        stack.run("stop", "alertmanager")
        stack.wait_until_state("alertmanager", state="exited", all_services=True, timeout=60.0)
        stack.run("stop", "validator")
        stack.wait_until_state("validator", state="exited", all_services=True, timeout=60.0)

        outage = wait_until(
            lambda: {
                "alertmanager_health": _probe(alertmanager.health),
                "prometheus_targets": prometheus.targets(),
                "prometheus_alerts": prometheus.alerts(),
                "prometheus_firing": prometheus.query(
                    'ALERTS{alertname="ServiceDown",job="validator",alertstate="firing"}'
                ),
            },
            is_ready=lambda current: (
                current["alertmanager_health"]["ok"] is False
                and targets_by_job(current["prometheus_targets"])["validator"]["health"] == "down"
                and _find_alert(
                    current["prometheus_alerts"],
                    alert_name="ServiceDown",
                    job="validator",
                )
                is not None
                and _single_vector_value(current["prometheus_firing"]) == 1.0
            ),
            description="Alertmanager outage with local firing alert",
            timeout=180.0,
        )
        _capture_snapshot(bundle, "alertmanager-outage-outage", outage)

        stack.up("alertmanager")
        stack.wait_until_ready(("alertmanager",), timeout=120.0)

        rerouted = wait_until(
            lambda: {
                "alertmanager_health": alertmanager.health(),
                "alertmanager_alerts": alertmanager.alerts(),
                "prometheus_firing": prometheus.query(
                    'ALERTS{alertname="ServiceDown",job="validator",alertstate="firing"}'
                ),
            },
            is_ready=lambda current: (
                current["alertmanager_health"] == "OK"
                and isinstance(current["alertmanager_alerts"], list)
                and any(
                    isinstance(alert, dict)
                    and isinstance(alert.get("labels"), dict)
                    and alert["labels"].get("alertname") == "ServiceDown"
                    and alert["labels"].get("job") == "validator"
                    for alert in current["alertmanager_alerts"]
                )
                and _single_vector_value(current["prometheus_firing"]) == 1.0
            ),
            description="Alertmanager receives firing alert after recovery",
            timeout=180.0,
        )
        _capture_snapshot(bundle, "alertmanager-outage-rerouted", rerouted)

        stack.up("validator")
        stack.wait_until_ready(("validator",), timeout=120.0)

        resolved = wait_until(
            lambda: {
                "alertmanager_health": alertmanager.health(),
                "alertmanager_alerts": alertmanager.alerts(),
                "prometheus_targets": prometheus.targets(),
                "prometheus_alerts": prometheus.alerts(),
                "prometheus_firing": prometheus.query(
                    'ALERTS{alertname="ServiceDown",job="validator",alertstate="firing"}'
                ),
            },
            is_ready=lambda current: (
                current["alertmanager_health"] == "OK"
                and targets_by_job(current["prometheus_targets"])["validator"]["health"] == "up"
                and _find_alert(
                    current["prometheus_alerts"],
                    alert_name="ServiceDown",
                    job="validator",
                )
                is None
                and _single_vector_value(current["prometheus_firing"]) is None
                and not any(
                    isinstance(alert, dict)
                    and isinstance(alert.get("labels"), dict)
                    and alert["labels"].get("alertname") == "ServiceDown"
                    and alert["labels"].get("job") == "validator"
                    for alert in current["alertmanager_alerts"]
                )
            ),
            description="Alertmanager outage resolution after recovery",
            timeout=180.0,
        )
        _capture_snapshot(bundle, "alertmanager-outage-resolved", resolved)
    finally:
        teardown_stack_runtime(bundle, stack, relay=relay, down_timeout=30)
