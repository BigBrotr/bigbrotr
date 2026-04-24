from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
import yaml

from bigbrotr.core.brotr import Brotr
from tests.integration.harness.builders import build_event_observation, build_relay
from tests.system.harness import (
    MetricsSnapshot,
    RuntimeDatabaseTarget,
    execute_runtime,
    fetch_runtime_rows,
    parse_metrics_text,
)
from tests.system.observability.prometheus.common import (
    collect_prometheus_snapshot,
    prometheus_api,
    single_vector_row,
    start_prometheus_stack,
    targets_by_job,
    vector_result,
    wait_until,
)
from tests.system.observability.prometheus.common import (
    ready_snapshot as ready_prometheus_snapshot,
)


if TYPE_CHECKING:
    from pathlib import Path

    from tests.system.harness import ComposeStack, LocalRelayRuntime, SystemArtifactBundle


_CLEAR_RELAY_URL = "wss://exporter-clear.example.com"
_TOR_RELAY_URL = f"ws://{'a' * 56}.onion"
_EVENT_ID = "44" * 32
_EVENT_PUBKEY = "55" * 32
_EVENT_CONTENT = "system-exporter-event"
_EXPORTER_SERVER_LABEL = "postgres:5432"


def _runtime_brotr(plan: object, *, role: str = "admin") -> Brotr:
    target = RuntimeDatabaseTarget.for_plan(plan, role=role)
    return Brotr.from_dict(
        {
            "pool": {
                "database": {
                    "host": target.host,
                    "port": target.port,
                    "database": target.database,
                    "user": target.user,
                    "password": target.password,
                }
            }
        }
    )


async def _async_seed_exporter_contract(plan: object) -> None:
    brotr = _runtime_brotr(plan)
    async with brotr:
        await brotr.insert_relay(
            [
                build_relay(_CLEAR_RELAY_URL, stored_at=1_700_000_000),
                build_relay(_TOR_RELAY_URL, stored_at=1_700_000_100),
            ]
        )
        await brotr.insert_event_observation(
            [
                build_event_observation(
                    _EVENT_ID,
                    _CLEAR_RELAY_URL,
                    pubkey=_EVENT_PUBKEY,
                    created_at=1_700_000_200,
                    content=_EVENT_CONTENT,
                )
            ],
            cascade=True,
        )


def _seed_exporter_contract(plan: object) -> None:
    asyncio.run(_async_seed_exporter_contract(plan))
    for relation in ("relay", "event", "event_observation"):
        execute_runtime(plan, f"ANALYZE {relation}")


def _runtime_query_path(plan: object) -> Path:
    return plan.runtime_root / "monitoring" / "postgres-exporter" / "queries.yaml"


def _query_contract(plan: object) -> dict[str, dict[str, object]]:
    payload = yaml.safe_load(_runtime_query_path(plan).read_text())
    assert isinstance(payload, dict)
    normalized: dict[str, dict[str, object]] = {}
    for query_name, query_spec in payload.items():
        assert isinstance(query_name, str)
        assert isinstance(query_spec, dict)
        normalized[query_name] = query_spec
    return normalized


def _exporter_metrics_snapshot(stack: ComposeStack) -> MetricsSnapshot:
    result = stack.run(
        "exec",
        "-T",
        "postgres-exporter",
        "wget",
        "-qO-",
        "http://127.0.0.1:9187/metrics",
    )
    return parse_metrics_text(result.stdout)


def _query_metric_columns(query_spec: dict[str, object]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    metrics = query_spec["metrics"]
    assert isinstance(metrics, list)
    label_columns: list[str] = []
    gauge_columns: list[str] = []
    for metric_spec in metrics:
        assert isinstance(metric_spec, dict)
        assert len(metric_spec) == 1
        column_name, column_spec = next(iter(metric_spec.items()))
        assert isinstance(column_name, str)
        assert isinstance(column_spec, dict)
        usage = column_spec["usage"]
        assert isinstance(usage, str)
        if usage == "LABEL":
            label_columns.append(column_name)
        else:
            assert usage == "GAUGE"
            gauge_columns.append(column_name)
    return tuple(label_columns), tuple(gauge_columns)


def _expected_exporter_samples(
    plan: object,
    query_contract: dict[str, dict[str, object]],
) -> tuple[dict[tuple[str, tuple[tuple[str, str], ...]], float], dict[str, object]]:
    samples: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
    query_rows: dict[str, object] = {}
    for query_name, query_spec in query_contract.items():
        query = query_spec["query"]
        assert isinstance(query, str)
        rows = fetch_runtime_rows(plan, query, role="reader")
        query_rows[query_name] = rows
        label_columns, gauge_columns = _query_metric_columns(query_spec)
        for row in rows:
            labels = tuple(
                sorted(
                    [("server", _EXPORTER_SERVER_LABEL)]
                    + [(column_name, str(row[column_name])) for column_name in label_columns]
                )
            )
            for gauge_column in gauge_columns:
                samples[(f"{query_name}_{gauge_column}", labels)] = float(row[gauge_column])
    return samples, query_rows


def _actual_exporter_samples(
    snapshot: MetricsSnapshot,
    *,
    expected_sample_names: frozenset[str],
) -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
    samples: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
    for sample in snapshot.samples:
        if sample.sample_name not in expected_sample_names:
            continue
        samples[(sample.sample_name, tuple(sorted(sample.labels.items())))] = sample.value
    return samples


def _prometheus_exporter_queries(profile: str) -> tuple[str, str]:
    return (
        f"{profile}_overview_relay_count",
        f"{profile}_relay_by_network_count",
    )


def _capture_exporter_artifacts(
    bundle: SystemArtifactBundle,
    plan: object,
    *,
    metrics_snapshot: MetricsSnapshot,
    query_rows: dict[str, object],
    targets_payload: object,
    prom_queries: dict[str, object],
) -> None:
    bundle.write_text_artifact(
        category="observability",
        subdir="observability/postgres_exporter",
        name="runtime-queries",
        contents=_runtime_query_path(plan).read_text(),
        suffix=".yaml",
    )
    bundle.write_text_artifact(
        category="observability",
        subdir="observability/postgres_exporter",
        name="metrics",
        contents=metrics_snapshot.text,
        suffix=".prom",
    )
    bundle.write_json_artifact(
        category="observability",
        subdir="observability/postgres_exporter",
        name="db-query-rows",
        payload=query_rows,
    )
    bundle.write_json_artifact(
        category="observability",
        subdir="observability/postgres_exporter",
        name="prometheus-targets",
        payload=targets_payload,
    )
    bundle.write_json_artifact(
        category="observability",
        subdir="observability/postgres_exporter",
        name="prometheus-queries",
        payload=prom_queries,
    )


def certify_postgres_exporter_contract(
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
        _seed_exporter_contract(plan)
        query_contract = _query_contract(plan)
        prometheus = prometheus_api(plan)

        wait_until(
            lambda: collect_prometheus_snapshot(prometheus),
            is_ready=ready_prometheus_snapshot,
            description=f"{profile} Prometheus readiness before exporter contract",
        )

        overview_query, relay_by_network_query = _prometheus_exporter_queries(profile)
        exporter_snapshot = wait_until(
            lambda: {
                "metrics": _exporter_metrics_snapshot(stack),
                "targets": prometheus.targets(),
                "overview": prometheus.query(overview_query),
                "relay_by_network": prometheus.query(relay_by_network_query),
            },
            is_ready=lambda current: (
                targets_by_job(current["targets"])["postgres"]["health"] == "up"
                and current["metrics"].single_value(overview_query) == 2.0
                and len(current["metrics"].matching_samples(relay_by_network_query)) == 2
                and single_vector_row(current["overview"])["value"] == 2.0
                and len(vector_result(current["relay_by_network"])) == 2
            ),
            description=f"{profile} postgres exporter readiness",
        )

        expected_samples, query_rows = _expected_exporter_samples(plan, query_contract)
        actual_samples = _actual_exporter_samples(
            exporter_snapshot["metrics"],
            expected_sample_names=frozenset(
                sample_name for sample_name, _labels in expected_samples
            ),
        )

        assert set(actual_samples) == set(expected_samples)
        for key, expected_value in expected_samples.items():
            sample_name, _labels = key
            if sample_name.endswith("_index_usage_ratio"):
                assert actual_samples[key] == pytest.approx(expected_value, abs=0.1)
                continue
            assert actual_samples[key] == pytest.approx(expected_value)

        prom_queries = {
            overview_query: exporter_snapshot["overview"],
            relay_by_network_query: exporter_snapshot["relay_by_network"],
        }
        overview_row = single_vector_row(prom_queries[overview_query])
        assert overview_row["value"] == 2.0
        relay_rows = vector_result(prom_queries[relay_by_network_query])
        assert {row["metric"]["network"] for row in relay_rows} == {"clearnet", "tor"}

        _capture_exporter_artifacts(
            bundle,
            plan,
            metrics_snapshot=exporter_snapshot["metrics"],
            query_rows=query_rows,
            targets_payload=exporter_snapshot["targets"],
            prom_queries=prom_queries,
        )
    finally:
        if bundle is not None and stack is not None:
            from tests.system.deployments.baseline import capture_stack_artifacts

            capture_stack_artifacts(bundle, stack)
        if relay is not None:
            relay.stop()
        if stack is not None:
            stack.down(timeout=30)
