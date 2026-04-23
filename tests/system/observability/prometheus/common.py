from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

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
from tests.system.harness import PrometheusApi, RuntimeAddressPlan
from tests.system.harness.observability import ObservabilityApiError


if TYPE_CHECKING:
    from pathlib import Path

    from tests.system.harness import ComposeStack, LocalRelayRuntime, SystemArtifactBundle


PRODUCT_SERVICE_JOBS = (
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
EXPECTED_PROMETHEUS_TARGETS = {
    **{
        service_name: {
            "instance": f"{service_name}:8000",
            "scrape_url": f"http://{service_name}:8000/metrics",
        }
        for service_name in PRODUCT_SERVICE_JOBS
    },
    "postgres": {
        "instance": "postgres-exporter:9187",
        "scrape_url": "http://postgres-exporter:9187/metrics",
    },
    "prometheus": {
        "instance": "localhost:9090",
        "scrape_url": "http://localhost:9090/metrics",
    },
}


def wait_until(
    fetch_snapshot: Any,
    *,
    is_ready: Any,
    description: str,
    timeout: float = 180.0,
    poll_interval: float = 1.0,
) -> Any:
    deadline = time.monotonic() + timeout
    last_snapshot: Any | None = None
    last_error: ObservabilityApiError | None = None
    while time.monotonic() < deadline:
        try:
            last_snapshot = fetch_snapshot()
        except ObservabilityApiError as exc:
            last_error = exc
        else:
            last_error = None
            if is_ready(last_snapshot):
                return last_snapshot
        time.sleep(poll_interval)

    if last_error is not None:
        raise RuntimeError(f"Timed out waiting for {description}: {last_error}") from last_error
    raise RuntimeError(f"Timed out waiting for {description}: {last_snapshot!r}")


def vector_result(payload: object) -> tuple[dict[str, object], ...]:
    assert isinstance(payload, dict)
    assert payload["status"] == "success"

    data = payload["data"]
    assert isinstance(data, dict)
    assert data["resultType"] == "vector"

    result = data["result"]
    assert isinstance(result, list)
    normalized: list[dict[str, object]] = []
    for row in result:
        assert isinstance(row, dict)
        metric = row["metric"]
        value = row["value"]
        assert isinstance(metric, dict)
        assert isinstance(value, list)
        assert len(value) == 2
        normalized.append({"metric": metric, "value": float(value[1])})
    return tuple(normalized)


def targets_by_job(payload: object) -> dict[str, dict[str, object]]:
    assert isinstance(payload, dict)
    assert payload["status"] == "success"

    data = payload["data"]
    assert isinstance(data, dict)
    active_targets = data["activeTargets"]
    dropped_targets = data["droppedTargets"]
    assert isinstance(active_targets, list)
    assert isinstance(dropped_targets, list)
    assert dropped_targets == []

    result: dict[str, dict[str, object]] = {}
    for target in active_targets:
        assert isinstance(target, dict)
        labels = target["labels"]
        assert isinstance(labels, dict)
        job_name = labels["job"]
        assert isinstance(job_name, str)
        result[job_name] = target
    return result


def service_info_by_service(payload: object) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for row in vector_result(payload):
        metric = row["metric"]
        assert isinstance(metric, dict)
        service_name = metric["service"]
        assert isinstance(service_name, str)
        rows[service_name] = row
    return rows


def single_vector_row(payload: object) -> dict[str, object]:
    result = vector_result(payload)
    assert len(result) == 1
    return result[0]


def capture_prometheus_artifacts(
    bundle: SystemArtifactBundle,
    *,
    health: str,
    ready: str,
    targets_payload: object,
    up_payload: object,
    service_info_payload: object,
    postgres_payload: object,
    prometheus_payload: object,
) -> None:
    bundle.write_text_artifact(
        category="observability",
        subdir="observability/prometheus",
        name="health",
        contents=health,
        suffix=".txt",
    )
    bundle.write_text_artifact(
        category="observability",
        subdir="observability/prometheus",
        name="ready",
        contents=ready,
        suffix=".txt",
    )
    bundle.capture_prometheus_targets(targets_payload)
    bundle.write_json_artifact(
        category="observability",
        subdir="observability/prometheus",
        name="query-up",
        payload=up_payload,
    )
    bundle.write_json_artifact(
        category="observability",
        subdir="observability/prometheus",
        name="query-service-info",
        payload=service_info_payload,
    )
    bundle.write_json_artifact(
        category="observability",
        subdir="observability/prometheus",
        name="query-pg-up",
        payload=postgres_payload,
    )
    bundle.write_json_artifact(
        category="observability",
        subdir="observability/prometheus",
        name="query-prometheus-build-info",
        payload=prometheus_payload,
    )


def ready_snapshot(current: dict[str, object]) -> bool:
    return (
        set(targets_by_job(current["targets"])) == set(EXPECTED_PROMETHEUS_TARGETS)
        and all(target["health"] == "up" for target in targets_by_job(current["targets"]).values())
        and {row["metric"]["job"]: row["value"] for row in vector_result(current["up"])}
        == dict.fromkeys(EXPECTED_PROMETHEUS_TARGETS, 1.0)
        and {
            service_name: row["value"]
            for service_name, row in service_info_by_service(current["service_info"]).items()
        }
        == dict.fromkeys(PRODUCT_SERVICE_JOBS, 1.0)
        and single_vector_row(current["pg_up"])["value"] == 1.0
        and single_vector_row(current["prometheus_build_info"])["value"] == 1.0
    )


def prometheus_api(plan: RuntimeAddressPlan) -> PrometheusApi:
    return PrometheusApi(f"http://127.0.0.1:{plan.ports.prometheus}")


def start_prometheus_stack(
    tmp_path: Path,
    *,
    profile: str,
    run_name: str,
    slot: int,
) -> tuple[SystemArtifactBundle, RuntimeAddressPlan, ComposeStack, LocalRelayRuntime]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create(
        profile,
        tmp_path / "runtime",
        run_name,
        slot=slot,
    )
    prepare_runtime_compose_config(plan)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    stack.up(*BOOTSTRAP_SERVICES, build=True)
    relay = start_baseline_relay(plan)
    configure_runtime_relay_targets(plan, relay)
    stack.up(build=True)
    stack.wait_until_ready(CONTINUOUS_SERVICES)
    return bundle, plan, stack, relay


def collect_prometheus_snapshot(prometheus: PrometheusApi) -> dict[str, object]:
    return {
        "health": prometheus.health(),
        "ready": prometheus.ready(),
        "targets": prometheus.targets(),
        "up": prometheus.query("up"),
        "service_info": prometheus.query("service_info"),
        "pg_up": prometheus.query("pg_up"),
        "prometheus_build_info": prometheus.query("prometheus_build_info"),
    }


def assert_target_contract(snapshot: dict[str, object]) -> None:
    current_targets = targets_by_job(snapshot["targets"])
    assert set(current_targets) == set(EXPECTED_PROMETHEUS_TARGETS)
    assert "seeder" not in current_targets

    for job_name, expected_target in EXPECTED_PROMETHEUS_TARGETS.items():
        target = current_targets[job_name]
        labels = target["labels"]
        discovered = target["discoveredLabels"]
        assert isinstance(labels, dict)
        assert isinstance(discovered, dict)
        assert labels["job"] == job_name
        assert labels["instance"] == expected_target["instance"]
        assert discovered["__address__"] == expected_target["instance"]
        assert target["scrapeUrl"] == expected_target["scrape_url"]
        assert target["health"] == "up"
        assert target["lastError"] == ""


def assert_up_query_contract(snapshot: dict[str, object]) -> None:
    up_rows = {
        row["metric"]["job"]: row
        for row in vector_result(snapshot["up"])
        if isinstance(row["metric"], dict)
    }
    assert set(up_rows) == set(EXPECTED_PROMETHEUS_TARGETS)
    for job_name, row in up_rows.items():
        metric = row["metric"]
        assert isinstance(metric, dict)
        assert metric["instance"] == EXPECTED_PROMETHEUS_TARGETS[job_name]["instance"]
        assert row["value"] == 1.0


def assert_service_info_query_contract(snapshot: dict[str, object]) -> None:
    rows = service_info_by_service(snapshot["service_info"])
    assert set(rows) == set(PRODUCT_SERVICE_JOBS)
    for service_name, row in rows.items():
        metric = row["metric"]
        assert isinstance(metric, dict)
        assert metric["job"] == service_name
        assert metric["instance"] == f"{service_name}:8000"
        assert row["value"] == 1.0


def assert_exporter_query_contracts(snapshot: dict[str, object]) -> None:
    postgres_row = single_vector_row(snapshot["pg_up"])
    postgres_metric = postgres_row["metric"]
    assert isinstance(postgres_metric, dict)
    assert postgres_row["value"] == 1.0
    assert postgres_metric["__name__"] == "pg_up"
    assert postgres_metric["instance"] == "postgres-exporter:9187"
    assert postgres_metric["job"] == "postgres"

    prometheus_row = single_vector_row(snapshot["prometheus_build_info"])
    metric = prometheus_row["metric"]
    assert isinstance(metric, dict)
    assert metric["job"] == "prometheus"
    assert metric["instance"] == "localhost:9090"
    assert prometheus_row["value"] == 1.0


def certify_prometheus_scrape_contract(
    tmp_path: Path,
    *,
    profile: str,
    run_name: str,
    slot: int,
) -> None:
    bundle = None
    stack = None
    relay = None

    try:
        bundle, plan, stack, relay = start_prometheus_stack(
            tmp_path,
            profile=profile,
            run_name=run_name,
            slot=slot,
        )
        prometheus = prometheus_api(plan)

        snapshot = wait_until(
            lambda: collect_prometheus_snapshot(prometheus),
            is_ready=ready_snapshot,
            description=f"{profile} Prometheus target and series readiness",
        )

        capture_prometheus_artifacts(
            bundle,
            health=snapshot["health"],
            ready=snapshot["ready"],
            targets_payload=snapshot["targets"],
            up_payload=snapshot["up"],
            service_info_payload=snapshot["service_info"],
            postgres_payload=snapshot["pg_up"],
            prometheus_payload=snapshot["prometheus_build_info"],
        )

        assert "Healthy" in snapshot["health"]
        assert "Ready" in snapshot["ready"]
        assert_target_contract(snapshot)
        assert_up_query_contract(snapshot)
        assert_service_info_query_contract(snapshot)
        assert_exporter_query_contracts(snapshot)
    finally:
        if bundle is not None and stack is not None:
            capture_stack_artifacts(bundle, stack)
        if relay is not None:
            relay.stop()
        if stack is not None:
            stack.down()
