from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.system.deployments.baseline import CONTINUOUS_SERVICES, capture_stack_artifacts
from tests.system.observability.grafana import common as grafana_helpers
from tests.system.observability.postgres_exporter import common as exporter_helpers
from tests.system.observability.prometheus import common as prometheus_helpers


pytestmark = pytest.mark.system


_PROFILE_SLUGS = ("bigbrotr", "lilbrotr")
_PROFILE_NAMES = ("BigBrotr", "LilBrotr")
_SERVICES_DASHBOARD_UID = "<profile>-services"
_BIGBROTR_ONLY_SERVICE_PANELS = (
    "Event Partition Distribution",
    "Event Relay Partition Distribution",
)
_BIGBROTR_ONLY_SERVICE_QUERIES = (
    '<profile>_partition_distribution_approx_rows{parent_table="event"} / on() group_left sum(<profile>_partition_distribution_approx_rows{parent_table="event"}) * 100',
    '<profile>_partition_distribution_approx_rows{parent_table="event_observation"} / on() group_left sum(<profile>_partition_distribution_approx_rows{parent_table="event_observation"}) * 100',
)


def _normalize_profile_tokens(value: object) -> object:
    if isinstance(value, str):
        normalized = value
        for token in _PROFILE_NAMES:
            normalized = normalized.replace(token, "<Profile>")
        for token in _PROFILE_SLUGS:
            normalized = normalized.replace(token, "<profile>")
        return normalized
    if isinstance(value, list):
        return [_normalize_profile_tokens(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_profile_tokens(item) for item in value)
    if isinstance(value, dict):
        return {
            _normalize_profile_tokens(key): _normalize_profile_tokens(item)
            for key, item in value.items()
        }
    return value


def _load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text())
    assert isinstance(payload, dict)
    return payload


def _monitoring_files(profile: str) -> tuple[str, ...]:
    root = Path(f"deployments/{profile}/monitoring")
    return tuple(
        sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    )


def _normalized_monitoring_files(profile: str) -> tuple[str, ...]:
    normalized = _normalize_profile_tokens(_monitoring_files(profile))
    assert isinstance(normalized, tuple)
    return tuple(sorted(str(path) for path in normalized))


def _dashboard_expression_contract(profile: str) -> dict[str, tuple[str, ...]]:
    expressions: dict[str, tuple[str, ...]] = {}
    for path in Path(f"deployments/{profile}/monitoring/grafana/provisioning/dashboards").glob(
        "*.json"
    ):
        payload = grafana_helpers._load_json(path)
        uid = payload["uid"]
        assert isinstance(uid, str)
        expressions[uid] = grafana_helpers._dashboard_target_expressions(payload.get("panels", []))
    return expressions


def _prometheus_target_signature(payload: object) -> dict[str, dict[str, object]]:
    rows = prometheus_helpers.targets_by_job(payload)
    return {
        job: {
            "health": row["health"],
            "instance": row["labels"]["instance"],
            "scrape_url": row["scrapeUrl"],
        }
        for job, row in rows.items()
    }


def _grafana_datasource_signature(snapshot: dict[str, object]) -> dict[str, object]:
    datasource = snapshot["datasource"]
    datasource_health = snapshot["datasource_health"]
    assert isinstance(datasource, dict)
    assert isinstance(datasource_health, dict)
    return {
        "uid": datasource["uid"],
        "type": datasource["type"],
        "url": datasource["url"],
        "isDefault": datasource["isDefault"],
        "readOnly": datasource["readOnly"],
        "health": datasource_health["status"],
    }


def _grafana_dashboard_signature(payload: object) -> tuple[tuple[str, str], ...]:
    dashboards = grafana_helpers._dashboards_by_uid(payload)
    return tuple(sorted((str(uid), str(row["title"])) for uid, row in dashboards.items()))


def _prometheus_query_signature(
    payload: object,
) -> tuple[tuple[tuple[tuple[str, str], ...], float], ...]:
    rows = prometheus_helpers.vector_result(payload)
    signature: list[tuple[tuple[tuple[str, str], ...], float]] = []
    for row in rows:
        metric = row["metric"]
        assert isinstance(metric, dict)
        labels = tuple(
            sorted(
                (str(key), str(value)) for key, value in metric.items() if str(key) != "__name__"
            )
        )
        signature.append((labels, float(row["value"])))
    return tuple(sorted(signature))


def _run_live_monitoring_parity(
    tmp_path: Path,
    *,
    profile: str,
    run_name: str,
    slot: int,
) -> dict[str, object]:
    bundle = None
    stack = None
    relay = None

    try:
        bundle, plan, stack, relay = prometheus_helpers.start_prometheus_stack(
            tmp_path,
            profile=profile,
            run_name=run_name,
            slot=slot,
        )
        exporter_helpers._seed_exporter_contract(plan)

        prometheus = prometheus_helpers.prometheus_api(plan)
        prometheus_snapshot = prometheus_helpers.wait_until(
            lambda: prometheus_helpers.collect_prometheus_snapshot(prometheus),
            is_ready=prometheus_helpers.ready_snapshot,
            description=f"{profile} Prometheus monitoring parity readiness",
        )

        grafana = grafana_helpers.grafana_api(plan)
        grafana_snapshot = grafana_helpers.wait_until(
            lambda: grafana_helpers.collect_grafana_snapshot(grafana),
            is_ready=grafana_helpers.ready_snapshot,
            description=f"{profile} Grafana datasource parity readiness",
        )
        expected_uids = tuple(sorted(grafana_helpers._expected_dashboard_definitions(profile)))
        dashboard_snapshot = grafana_helpers.wait_until(
            lambda: grafana_helpers.collect_dashboard_provisioning_snapshot(
                grafana,
                expected_uids=expected_uids,
            ),
            is_ready=lambda current: grafana_helpers.dashboard_ready_snapshot(
                current,
                expected_uids=expected_uids,
            ),
            description=f"{profile} Grafana dashboard parity readiness",
        )

        exporter_snapshot = exporter_helpers.wait_until(
            lambda: {
                "overview_relay_count": prometheus.query(f"{profile}_overview_relay_count"),
                "overview_event_count_approx": prometheus.query(
                    f"{profile}_overview_event_count_approx"
                ),
                "relay_by_network_count": prometheus.query(f"{profile}_relay_by_network_count"),
            },
            is_ready=lambda current: all(
                prometheus_helpers.vector_result(current[query_name]) for query_name in current
            ),
            description=f"{profile} exporter parity queries",
        )

        snapshot = {
            "targets": prometheus_snapshot["targets"],
            "datasource": _grafana_datasource_signature(grafana_snapshot),
            "dashboards": _grafana_dashboard_signature(dashboard_snapshot["dashboards"]),
            "exporter_queries": {
                name: _prometheus_query_signature(payload)
                for name, payload in exporter_snapshot.items()
            },
        }
        bundle.write_json_artifact(
            category="observability",
            subdir="observability/prometheus",
            name=f"{profile}-monitoring-parity",
            payload=snapshot,
        )
        return snapshot
    finally:
        if bundle is not None and stack is not None:
            capture_stack_artifacts(bundle, stack, services=CONTINUOUS_SERVICES)
        if relay is not None:
            relay.stop()
        if stack is not None:
            stack.down()


def test_monitoring_assets_only_differ_on_profile_tokens() -> None:
    assert _normalized_monitoring_files("bigbrotr") == _normalized_monitoring_files("lilbrotr")

    assert _normalize_profile_tokens(
        _load_yaml(Path("deployments/bigbrotr/monitoring/prometheus/prometheus.yaml"))
    ) == _normalize_profile_tokens(
        _load_yaml(Path("deployments/lilbrotr/monitoring/prometheus/prometheus.yaml"))
    )
    assert _normalize_profile_tokens(
        _load_yaml(Path("deployments/bigbrotr/monitoring/prometheus/rules/alerts.yml"))
    ) == _normalize_profile_tokens(
        _load_yaml(Path("deployments/lilbrotr/monitoring/prometheus/rules/alerts.yml"))
    )
    assert _normalize_profile_tokens(
        _load_yaml(Path("deployments/bigbrotr/monitoring/alertmanager/alertmanager.yml"))
    ) == _normalize_profile_tokens(
        _load_yaml(Path("deployments/lilbrotr/monitoring/alertmanager/alertmanager.yml"))
    )
    assert _normalize_profile_tokens(grafana_helpers._expected_datasource_config("bigbrotr")) == (
        _normalize_profile_tokens(grafana_helpers._expected_datasource_config("lilbrotr"))
    )
    assert _normalize_profile_tokens(grafana_helpers._expected_dashboard_provider("bigbrotr")) == (
        _normalize_profile_tokens(grafana_helpers._expected_dashboard_provider("lilbrotr"))
    )
    big_dashboards = _normalize_profile_tokens(
        grafana_helpers._expected_dashboard_definitions("bigbrotr")
    )
    lil_dashboards = _normalize_profile_tokens(
        grafana_helpers._expected_dashboard_definitions("lilbrotr")
    )
    assert isinstance(big_dashboards, dict)
    assert isinstance(lil_dashboards, dict)
    assert {
        key: value for key, value in big_dashboards.items() if key != _SERVICES_DASHBOARD_UID
    } == {key: value for key, value in lil_dashboards.items() if key != _SERVICES_DASHBOARD_UID}
    big_services_dashboard = big_dashboards[_SERVICES_DASHBOARD_UID]
    lil_services_dashboard = lil_dashboards[_SERVICES_DASHBOARD_UID]
    assert isinstance(big_services_dashboard, dict)
    assert isinstance(lil_services_dashboard, dict)
    assert {
        key: value for key, value in big_services_dashboard.items() if key != "panel_titles"
    } == {key: value for key, value in lil_services_dashboard.items() if key != "panel_titles"}
    assert isinstance(big_services_dashboard["panel_titles"], tuple)
    assert isinstance(lil_services_dashboard["panel_titles"], tuple)
    assert (
        tuple(
            title
            for title in big_services_dashboard["panel_titles"]
            if title not in _BIGBROTR_ONLY_SERVICE_PANELS
        )
        == lil_services_dashboard["panel_titles"]
    )
    assert (
        tuple(
            title
            for title in big_services_dashboard["panel_titles"]
            if title in _BIGBROTR_ONLY_SERVICE_PANELS
        )
        == _BIGBROTR_ONLY_SERVICE_PANELS
    )

    big_expressions = _normalize_profile_tokens(_dashboard_expression_contract("bigbrotr"))
    lil_expressions = _normalize_profile_tokens(_dashboard_expression_contract("lilbrotr"))
    assert isinstance(big_expressions, dict)
    assert isinstance(lil_expressions, dict)
    assert {
        key: value for key, value in big_expressions.items() if key != _SERVICES_DASHBOARD_UID
    } == {key: value for key, value in lil_expressions.items() if key != _SERVICES_DASHBOARD_UID}
    assert isinstance(big_expressions[_SERVICES_DASHBOARD_UID], tuple)
    assert isinstance(lil_expressions[_SERVICES_DASHBOARD_UID], tuple)
    assert (
        tuple(
            expr
            for expr in big_expressions[_SERVICES_DASHBOARD_UID]
            if expr not in _BIGBROTR_ONLY_SERVICE_QUERIES
        )
        == lil_expressions[_SERVICES_DASHBOARD_UID]
    )
    assert (
        tuple(
            expr
            for expr in big_expressions[_SERVICES_DASHBOARD_UID]
            if expr in _BIGBROTR_ONLY_SERVICE_QUERIES
        )
        == _BIGBROTR_ONLY_SERVICE_QUERIES
    )
    assert _normalize_profile_tokens(grafana_helpers._query_anchor_contracts("bigbrotr")) == (
        _normalize_profile_tokens(grafana_helpers._query_anchor_contracts("lilbrotr"))
    )
    assert _normalize_profile_tokens(
        _load_yaml(Path("deployments/bigbrotr/monitoring/postgres-exporter/queries.yaml"))
    ) == _normalize_profile_tokens(
        _load_yaml(Path("deployments/lilbrotr/monitoring/postgres-exporter/queries.yaml"))
    )


@pytest.mark.timeout(1800)
def test_live_monitoring_surfaces_remain_coherent_across_profiles(tmp_path: Path) -> None:
    bigbrotr = _run_live_monitoring_parity(
        tmp_path,
        profile="bigbrotr",
        run_name="bigbrotr-monitoring-parity",
        slot=90,
    )
    lilbrotr = _run_live_monitoring_parity(
        tmp_path,
        profile="lilbrotr",
        run_name="lilbrotr-monitoring-parity",
        slot=91,
    )

    assert _prometheus_target_signature(bigbrotr["targets"]) == _prometheus_target_signature(
        lilbrotr["targets"]
    )
    assert bigbrotr["datasource"] == lilbrotr["datasource"]
    assert _normalize_profile_tokens(bigbrotr["dashboards"]) == _normalize_profile_tokens(
        lilbrotr["dashboards"]
    )
    assert _normalize_profile_tokens(bigbrotr["exporter_queries"]) == _normalize_profile_tokens(
        lilbrotr["exporter_queries"]
    )
