from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest

from tests.system.deployments.baseline import (
    ALL_SERVICES,
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
from tests.system.harness import (
    MetricsScrapeError,
    MetricsSnapshot,
    RuntimeAddressPlan,
    fetch_metrics_snapshot,
    parse_metrics_text,
)


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.system.harness import ComposeStack, SystemArtifactBundle


pytestmark = pytest.mark.system


METRIC_SERVICES = (
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
_METRICS_PORT_ATTR = {
    "finder": "finder_metrics",
    "validator": "validator_metrics",
    "monitor": "monitor_metrics",
    "synchronizer": "synchronizer_metrics",
    "refresher": "refresher_metrics",
    "ranker": "ranker_metrics",
    "api": "api_metrics",
    "dvm": "dvm_metrics",
}
_ASSERTOR_INTERNAL_METRICS_PORT = 8000
_EXPECTED_DURATION_BUCKETS = (
    "1.0",
    "5.0",
    "10.0",
    "30.0",
    "60.0",
    "120.0",
    "300.0",
    "600.0",
    "1800.0",
    "3600.0",
    "+Inf",
)


def _wait_until(
    fetch_snapshot: Callable[[], Any],
    *,
    is_ready: Callable[[Any], bool],
    description: str,
    timeout: float = 120.0,
    poll_interval: float = 0.5,
) -> Any:
    deadline = time.monotonic() + timeout
    last_snapshot = fetch_snapshot()
    while time.monotonic() < deadline:
        last_snapshot = fetch_snapshot()
        if is_ready(last_snapshot):
            return last_snapshot
        time.sleep(poll_interval)
    raise RuntimeError(f"Timed out waiting for {description}: {last_snapshot!r}")


def _service_metrics_snapshot(
    stack: ComposeStack,
    plan: RuntimeAddressPlan,
    service_name: str,
) -> MetricsSnapshot:
    if service_name == "assertor":
        result = stack.run(
            "exec",
            "-T",
            "assertor",
            "python",
            "-c",
            (
                "import sys, urllib.request; "
                "sys.stdout.write(urllib.request.urlopen("
                f"'http://127.0.0.1:{_ASSERTOR_INTERNAL_METRICS_PORT}/metrics'"
                ").read().decode())"
            ),
        )
        return parse_metrics_text(result.stdout)

    port_attr = _METRICS_PORT_ATTR[service_name]
    port = getattr(plan.ports, port_attr)
    return fetch_metrics_snapshot(f"http://127.0.0.1:{port}")


def _wait_for_service_metrics(
    stack: ComposeStack,
    plan: RuntimeAddressPlan,
    service_name: str,
) -> MetricsSnapshot:
    def _is_ready(snapshot: MetricsSnapshot) -> bool:
        try:
            return (
                snapshot.single_value("service_info", service=service_name) == 1.0
                and snapshot.single_value(
                    "service_gauge",
                    service=service_name,
                    name="last_cycle_timestamp",
                )
                > 0
                and snapshot.single_value(
                    "service_gauge",
                    service=service_name,
                    name="consecutive_failures",
                )
                == 0.0
                and snapshot.single_value(
                    "service_counter_total",
                    service=service_name,
                    name="cycles_success",
                )
                >= 1.0
                and snapshot.single_value("cycle_duration_seconds_count", service=service_name)
                >= 1.0
            )
        except MetricsScrapeError:
            return False

    return _wait_until(
        lambda: _service_metrics_snapshot(stack, plan, service_name),
        is_ready=_is_ready,
        description=f"{service_name} metrics readiness",
    )


def _capture_metrics_artifacts(
    bundle: SystemArtifactBundle,
    service_snapshots: dict[str, MetricsSnapshot],
    *,
    name: str,
) -> None:
    for service_name, snapshot in service_snapshots.items():
        bundle.write_text_artifact(
            category="observability",
            subdir="observability/metrics",
            name=f"{name}-{service_name}-metrics",
            contents=snapshot.text,
            suffix=".prom",
        )


def _assert_common_metric_schema(snapshot: MetricsSnapshot, *, service_name: str) -> None:
    assert {
        "service_info",
        "service_gauge",
        "service_counter",
        "cycle_duration_seconds",
    }.issubset(snapshot.family_names)

    info_samples = snapshot.matching_samples("service_info", service=service_name)
    assert len(info_samples) == 1
    assert info_samples[0].labels == {"service": service_name}

    gauge_samples = snapshot.samples_for_name("service_gauge")
    assert gauge_samples
    for sample in gauge_samples:
        assert sample.labels.keys() == {"service", "name"}
        assert sample.labels["service"] == service_name

    for sample_name in ("service_counter_total", "service_counter_created"):
        counter_samples = snapshot.samples_for_name(sample_name)
        assert counter_samples
        for sample in counter_samples:
            assert sample.labels.keys() == {"service", "name"}
            assert sample.labels["service"] == service_name

    bucket_samples = snapshot.samples_for_name("cycle_duration_seconds_bucket")
    assert bucket_samples
    assert tuple(sample.labels["le"] for sample in bucket_samples) == _EXPECTED_DURATION_BUCKETS
    for sample in bucket_samples:
        assert sample.labels.keys() == {"service", "le"}
        assert sample.labels["service"] == service_name

    for sample_name in ("cycle_duration_seconds_count", "cycle_duration_seconds_sum"):
        samples = snapshot.samples_for_name(sample_name)
        assert len(samples) == 1
        assert samples[0].labels == {"service": service_name}


def _restart_service(stack: ComposeStack, service_name: str) -> None:
    stack.run("stop", service_name)
    stack.wait_until_state(service_name, state="exited", timeout=60.0)
    stack.run("rm", "-f", service_name)
    stack.up(service_name)
    stack.wait_until_ready((service_name,), timeout=180.0)


@pytest.mark.timeout(1200)
def test_bigbrotr_services_emit_common_metric_schema_and_survive_refresher_restart(
    tmp_path: Path,
) -> None:
    bundle = create_bundle(tmp_path, "bigbrotr-emitted-metrics-contract")
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", "bigbrotr-emitted-metrics")
    prepare_runtime_compose_config(plan)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    relay = None
    initial_snapshots: dict[str, MetricsSnapshot] = {}
    restarted_refresher_snapshot: MetricsSnapshot | None = None
    try:
        stack.up(*BOOTSTRAP_SERVICES)
        relay = start_baseline_relay(plan)
        configure_runtime_relay_targets(plan, relay)
        stack.up()
        stack.wait_until_ready(CONTINUOUS_SERVICES)

        for service_name in METRIC_SERVICES:
            initial_snapshots[service_name] = _wait_for_service_metrics(stack, plan, service_name)

        _capture_metrics_artifacts(bundle, initial_snapshots, name="initial")

        _restart_service(stack, "refresher")
        restarted_refresher_snapshot = _wait_for_service_metrics(stack, plan, "refresher")
        _capture_metrics_artifacts(
            bundle,
            {"refresher-restarted": restarted_refresher_snapshot},
            name="restart",
        )
    finally:
        teardown_stack_runtime(bundle, stack, relay=relay, services=ALL_SERVICES)

    assert set(initial_snapshots) == set(METRIC_SERVICES)

    for service_name, snapshot in initial_snapshots.items():
        _assert_common_metric_schema(snapshot, service_name=service_name)

    assert restarted_refresher_snapshot is not None
    _assert_common_metric_schema(restarted_refresher_snapshot, service_name="refresher")
    assert restarted_refresher_snapshot.family_names == initial_snapshots["refresher"].family_names
    assert restarted_refresher_snapshot.single_value(
        "service_gauge",
        service="refresher",
        name="last_cycle_timestamp",
    ) > initial_snapshots["refresher"].single_value(
        "service_gauge",
        service="refresher",
        name="last_cycle_timestamp",
    )
