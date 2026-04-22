from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
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
    configure_runtime_host_gateway,
    prepare_runtime_compose_config,
    start_baseline_relay,
)
from tests.system.harness import (
    LocalHttpFixtureRuntime,
    LocalTlsWebSocketRuntime,
    RuntimeAddressPlan,
    fetch_runtime_rows,
)


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.system.harness import (
        ComposeServiceStatus,
        ComposeStack,
        LocalRelayRuntime,
        SystemArtifactBundle,
    )


pytestmark = pytest.mark.system


DISCOVERY_PIPELINE_ARTIFACT_SERVICES = (
    *BOOTSTRAP_SERVICES,
    "seeder",
    "finder",
    "validator",
    "monitor",
)
_CANDIDATE_ROWS_SQL = """
    SELECT
        state_key,
        state_value->>'network' AS network,
        (state_value->>'failures')::int AS failures,
        (state_value->>'timestamp')::bigint AS timestamp
    FROM service_state
    WHERE owner = 'validator'
      AND state_type = 'checkpoint'
    ORDER BY state_key
"""
_RELAY_ROWS_SQL = """
    SELECT url, network, stored_at
    FROM relay
    ORDER BY url
"""
_API_CHECKPOINT_SQL = """
    SELECT
        state_key,
        (state_value->>'timestamp')::bigint AS timestamp
    FROM service_state
    WHERE owner = 'finder'
      AND state_type = 'checkpoint'
    ORDER BY state_key
"""
_MONITOR_DOCUMENT_ROWS_SQL = """
    SELECT
        rd.relay_url,
        rd.role,
        rd.associated_at,
        d.data
    FROM relay_document AS rd
    JOIN document AS d
      ON d.id = rd.document_id
     AND d.type = rd.role
    ORDER BY rd.relay_url, rd.role, rd.associated_at
"""
_MONITOR_CHECKPOINT_ROWS_SQL = """
    SELECT
        state_key,
        (state_value->>'timestamp')::bigint AS timestamp
    FROM service_state
    WHERE owner = 'monitor'
      AND state_type = 'checkpoint'
    ORDER BY state_key
"""


@dataclass(slots=True)
class _DiscoveryPipelineResources:
    relay: LocalRelayRuntime
    seeded_runtime: LocalTlsWebSocketRuntime
    found_runtime: LocalTlsWebSocketRuntime
    fixture: LocalHttpFixtureRuntime
    seeded_url: str
    found_url: str
    source_url: str


@dataclass(frozen=True, slots=True)
class _DiscoveryPipelineResult:
    seeder_status: ComposeServiceStatus
    seeder_snapshot: dict[str, object]
    finder_snapshot: dict[str, object]
    validator_snapshot: dict[str, object]
    monitor_snapshot: dict[str, object]
    seeder_logs: str
    finder_logs: str
    validator_logs: str
    monitor_logs: str


def _configure_seed_runtime(
    plan: RuntimeAddressPlan,
    *,
    file_path: str,
    seed_lines: tuple[str, ...],
) -> None:
    config_path = plan.runtime_root / "config" / "services" / "seeder.yaml"
    config_payload = yaml.safe_load(config_path.read_text())
    assert isinstance(config_payload, dict)

    seed_payload = config_payload.setdefault("seed", {})
    assert isinstance(seed_payload, dict)
    seed_payload["file_path"] = file_path
    seed_payload["to_validate"] = True
    config_path.write_text(yaml.safe_dump(config_payload, sort_keys=False))

    seed_path = plan.runtime_root / file_path
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_text("\n".join(seed_lines) + "\n")


def _configure_finder_runtime(plan: RuntimeAddressPlan, *, source_url: str) -> None:
    config_path = plan.runtime_root / "config" / "services" / "finder.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    payload["interval"] = 3600.0
    payload["api"] = {
        "enabled": True,
        "cooldown": 3600.9,
        "request_delay": 0.0,
        "max_response_size": 8192,
        "sources": [
            {
                "url": source_url,
                "expression": "[*]",
                "timeout": 5.0,
                "connect_timeout": 1.0,
            }
        ],
    }
    payload["events"] = {"enabled": False}
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _configure_validator_runtime(plan: RuntimeAddressPlan) -> None:
    config_path = plan.runtime_root / "config" / "services" / "validator.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    payload["interval"] = 3600.0
    processing = payload.setdefault("processing", {})
    assert isinstance(processing, dict)
    processing["interval"] = 0.0
    processing["chunk_size"] = 10
    processing["max_candidates"] = 10
    processing["allow_insecure"] = True

    networks = payload.setdefault("networks", {})
    assert isinstance(networks, dict)
    networks["clearnet"] = {"enabled": True, "max_tasks": 2, "timeout": 5.0}
    networks["tor"] = {"enabled": False}
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _metadata_flags(*, nip11_info: bool, nip66_rtt: bool) -> dict[str, bool]:
    return {
        "nip11_info": nip11_info,
        "nip66_rtt": nip66_rtt,
        "nip66_ssl": False,
        "nip66_geo": False,
        "nip66_net": False,
        "nip66_dns": False,
        "nip66_http": False,
    }


def _configure_monitor_runtime(plan: RuntimeAddressPlan) -> None:
    config_path = plan.runtime_root / "config" / "services" / "monitor.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    flags = _metadata_flags(nip11_info=True, nip66_rtt=True)
    payload["interval"] = 3600.0

    processing = payload.setdefault("processing", {})
    assert isinstance(processing, dict)
    processing["chunk_size"] = 10
    processing["max_relays"] = 10
    processing["allow_insecure"] = True
    processing["compute"] = flags
    processing["store"] = flags
    processing["retries"] = {
        "nip11_info": {"max_attempts": 0},
        "nip66_rtt": {"max_attempts": 0},
    }

    discovery = payload.setdefault("discovery", {})
    assert isinstance(discovery, dict)
    discovery["enabled"] = False
    discovery["interval"] = 60.0
    discovery["include"] = flags

    announcement = payload.setdefault("announcement", {})
    assert isinstance(announcement, dict)
    announcement["enabled"] = False
    announcement["include"] = flags

    profile = payload.setdefault("profile", {})
    assert isinstance(profile, dict)
    profile["enabled"] = False

    relay_list = payload.setdefault("relay_list", {})
    assert isinstance(relay_list, dict)
    relay_list["enabled"] = False

    networks = payload.setdefault("networks", {})
    assert isinstance(networks, dict)
    networks["clearnet"] = {"enabled": True, "max_tasks": 2, "timeout": 2.0}
    networks["tor"] = {"enabled": False}
    networks["i2p"] = {"enabled": False}
    networks["loki"] = {"enabled": False}
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _run_seeder_once(
    *,
    stack: ComposeStack,
    bundle: SystemArtifactBundle,
    label: str,
) -> ComposeServiceStatus:
    stack.up("seeder", build=True)
    status = stack.wait_until_state("seeder", state="exited", exit_code=0, timeout=180.0)
    bundle.write_text_artifact(
        category="containers",
        subdir="containers",
        name=f"{label}-compose-ps",
        contents=stack.run("ps", "--all", "--format", "json").stdout,
        suffix=".jsonl",
    )
    bundle.capture_container_logs(
        f"{label}-seeder", stack.run("logs", "--no-color", "seeder").stdout
    )
    return status


def _candidate_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _CANDIDATE_ROWS_SQL)


def _relay_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _RELAY_ROWS_SQL)


def _api_checkpoints(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _API_CHECKPOINT_SQL)


def _monitor_documents(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _MONITOR_DOCUMENT_ROWS_SQL)


def _monitor_checkpoints(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _MONITOR_CHECKPOINT_ROWS_SQL)


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


def _canonical_tls_docker_url(runtime: LocalTlsWebSocketRuntime) -> str:
    return f"wss://{runtime.docker_host}:{runtime.port}"


def _decode_document_data(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise TypeError(
        f"Expected document payload dict or JSON object string, got {type(value).__name__}"
    )


def _capture_pipeline_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    relay: LocalRelayRuntime,
    fixture: LocalHttpFixtureRuntime,
    seeded_runtime: LocalTlsWebSocketRuntime,
    found_runtime: LocalTlsWebSocketRuntime,
    name: str,
) -> None:
    for service_name in ("finder", "validator", "monitor"):
        bundle.capture_container_logs(
            f"{name}-{service_name}", stack.run("logs", "--no-color", service_name).stdout
        )
    bundle.capture_container_logs(f"{name}-relay", relay.logs())
    bundle.write_json_artifact(
        category="containers",
        subdir="containers",
        name=f"{name}-http-requests",
        payload=[asdict(request) for request in fixture.requests()],
    )
    bundle.write_text_artifact(
        category="containers",
        subdir="containers",
        name=f"{name}-http-requests-log",
        contents=fixture.requests_log_path.read_text()
        if fixture.requests_log_path.exists()
        else "",
        suffix=".jsonl",
    )
    bundle.capture_relay_events(
        f"{name}-relay-sessions",
        {
            "seeded_runtime_sessions": [asdict(session) for session in seeded_runtime.sessions()],
            "found_runtime_sessions": [asdict(session) for session in found_runtime.sessions()],
        },
    )


def _start_discovery_resources(
    tmp_path: Path,
    plan: RuntimeAddressPlan,
) -> _DiscoveryPipelineResources:
    relay = start_baseline_relay(plan)
    seeded_runtime = LocalTlsWebSocketRuntime(
        tmp_path / "seeded-runtime",
        mode="proxy",
        backend_url=relay.ws_url,
        http_backend_url=relay.ws_url.replace("ws://", "http://", 1),
    )
    found_runtime = LocalTlsWebSocketRuntime(
        tmp_path / "found-runtime",
        mode="proxy",
        backend_url=relay.ws_url,
        http_backend_url=relay.ws_url.replace("ws://", "http://", 1),
    )
    seeded_runtime.start()
    found_runtime.start()

    seeded_url = _canonical_tls_docker_url(seeded_runtime)
    found_url = _canonical_tls_docker_url(found_runtime)
    fixture = LocalHttpFixtureRuntime(tmp_path / "http-fixture")
    fixture.start()
    fixture.clear_requests()
    fixture.set_json_response(
        "/sources.json",
        [
            found_url,
            found_url,
            "mailto:not-a-relay@example.com",
        ],
    )
    return _DiscoveryPipelineResources(
        relay=relay,
        seeded_runtime=seeded_runtime,
        found_runtime=found_runtime,
        fixture=fixture,
        seeded_url=seeded_url,
        found_url=found_url,
        source_url=fixture.docker_url("/sources.json"),
    )


def _stop_discovery_resources(resources: _DiscoveryPipelineResources | None) -> None:
    if resources is None:
        return
    resources.fixture.stop()
    resources.found_runtime.stop()
    resources.seeded_runtime.stop()
    resources.relay.stop()


def _configure_discovery_pipeline_runtime(
    plan: RuntimeAddressPlan,
    resources: _DiscoveryPipelineResources,
) -> None:
    _configure_seed_runtime(
        plan,
        file_path="static/seed_relays.txt",
        seed_lines=(
            "# seeded by discovery pipeline",
            resources.seeded_url,
            resources.seeded_url,
            "https://not-a-relay.example.com",
        ),
    )
    _configure_finder_runtime(plan, source_url=resources.source_url)
    _configure_validator_runtime(plan)
    _configure_monitor_runtime(plan)


def _run_discovery_pipeline(
    *,
    stack: ComposeStack,
    bundle: SystemArtifactBundle,
    plan: RuntimeAddressPlan,
    resources: _DiscoveryPipelineResources,
) -> _DiscoveryPipelineResult:
    seeder_status = _run_seeder_once(stack=stack, bundle=bundle, label="discovery-pipeline")
    seeder_snapshot = {"candidates": _candidate_rows(plan), "relays": _relay_rows(plan)}
    bundle.capture_db_snapshot("discovery-pipeline-seeder", seeder_snapshot)

    stack.up("finder", build=True)
    stack.wait_until_ready(("finder",), timeout=180.0)
    finder_snapshot = _wait_until(
        lambda: {
            "requests": len(resources.fixture.requests(path="/sources.json")),
            "candidates": _candidate_rows(plan),
            "checkpoints": _api_checkpoints(plan),
        },
        is_ready=lambda current: (
            current["requests"] == 1
            and len(current["candidates"]) == 2
            and len(current["checkpoints"]) == 1
        ),
        description="finder pipeline handoff",
    )
    bundle.capture_db_snapshot("discovery-pipeline-finder", finder_snapshot)

    stack.up("validator", build=True)
    stack.wait_until_ready(("validator",), timeout=180.0)
    validator_snapshot = _wait_until(
        lambda: {
            "candidates": _candidate_rows(plan),
            "relays": _relay_rows(plan),
            "seeded_sessions": resources.seeded_runtime.sessions(),
            "found_sessions": resources.found_runtime.sessions(),
        },
        is_ready=lambda current: (
            len(current["candidates"]) == 0
            and len(current["relays"]) == 2
            and len(current["seeded_sessions"]) >= 1
            and len(current["found_sessions"]) >= 1
        ),
        description="validator relay promotion",
    )
    bundle.capture_db_snapshot("discovery-pipeline-validator", validator_snapshot)

    stack.up("monitor", build=True)
    stack.wait_until_ready(("monitor",), timeout=180.0)
    monitor_snapshot = _wait_until(
        lambda: {
            "documents": _monitor_documents(plan),
            "checkpoints": _monitor_checkpoints(plan),
            "seeded_sessions": resources.seeded_runtime.sessions(),
            "found_sessions": resources.found_runtime.sessions(),
        },
        is_ready=lambda current: (
            len(current["documents"]) == 4
            and len(current["checkpoints"]) == 2
            and {row["state_key"] for row in current["checkpoints"]}
            == {resources.seeded_url, resources.found_url}
        ),
        description="monitor metadata persistence",
    )
    bundle.capture_db_snapshot("discovery-pipeline-monitor", monitor_snapshot)
    _capture_pipeline_artifacts(
        bundle,
        stack,
        relay=resources.relay,
        fixture=resources.fixture,
        seeded_runtime=resources.seeded_runtime,
        found_runtime=resources.found_runtime,
        name="discovery-pipeline",
    )
    return _DiscoveryPipelineResult(
        seeder_status=seeder_status,
        seeder_snapshot=seeder_snapshot,
        finder_snapshot=finder_snapshot,
        validator_snapshot=validator_snapshot,
        monitor_snapshot=monitor_snapshot,
        seeder_logs=stack.run("logs", "--no-color", "seeder").stdout,
        finder_logs=stack.run("logs", "--no-color", "finder").stdout,
        validator_logs=stack.run("logs", "--no-color", "validator").stdout,
        monitor_logs=stack.run("logs", "--no-color", "monitor").stdout,
    )


def _assert_discovery_pipeline_results(
    result: _DiscoveryPipelineResult,
    resources: _DiscoveryPipelineResources,
) -> None:
    assert result.seeder_status.state == "exited"
    assert result.seeder_status.exit_code == 0
    assert result.seeder_snapshot["relays"] == ()
    assert tuple(row["state_key"] for row in result.seeder_snapshot["candidates"]) == (
        resources.seeded_url,
    )
    assert {row["network"] for row in result.seeder_snapshot["candidates"]} == {"clearnet"}
    assert {row["failures"] for row in result.seeder_snapshot["candidates"]} == {0}

    assert result.finder_snapshot["requests"] == 1
    assert {row["state_key"] for row in result.finder_snapshot["candidates"]} == {
        resources.seeded_url,
        resources.found_url,
    }
    assert result.finder_snapshot["checkpoints"][0]["state_key"] == resources.source_url
    assert isinstance(result.finder_snapshot["checkpoints"][0]["timestamp"], int)
    assert result.finder_snapshot["checkpoints"][0]["timestamp"] > 0

    assert result.validator_snapshot["candidates"] == ()
    assert {row["url"] for row in result.validator_snapshot["relays"]} == {
        resources.found_url,
        resources.seeded_url,
    }
    assert {row["network"] for row in result.validator_snapshot["relays"]} == {"clearnet"}
    assert all(
        isinstance(row["stored_at"], int) and row["stored_at"] > 0
        for row in result.validator_snapshot["relays"]
    )

    documents_by_relay: dict[str, dict[str, dict[str, object]]] = {}
    for row in result.monitor_snapshot["documents"]:
        relay_documents = documents_by_relay.setdefault(str(row["relay_url"]), {})
        relay_documents[str(row["role"])] = dict(row)

    assert set(documents_by_relay) == {resources.seeded_url, resources.found_url}
    for relay_url in (resources.seeded_url, resources.found_url):
        assert set(documents_by_relay[relay_url]) == {"nip11_info", "nip66_rtt"}
        nip11_document = _decode_document_data(documents_by_relay[relay_url]["nip11_info"]["data"])
        assert nip11_document["logs"]["success"] is True
        assert "nostr-rs-relay" in str(nip11_document["data"]["software"])
        assert 11 in nip11_document["data"]["supported_nips"]

        rtt_document = _decode_document_data(documents_by_relay[relay_url]["nip66_rtt"]["data"])
        assert rtt_document["logs"]["open_success"] is True
        assert isinstance(rtt_document["data"]["rtt_open"], int)
        assert rtt_document["data"]["rtt_open"] >= 0

    checkpoints = {
        row["state_key"]: row["timestamp"] for row in result.monitor_snapshot["checkpoints"]
    }
    assert set(checkpoints) == {resources.seeded_url, resources.found_url}
    assert all(isinstance(timestamp, int) and timestamp > 0 for timestamp in checkpoints.values())

    assert "relay_parse_failed:" in result.seeder_logs
    assert "api_completed" in result.finder_logs
    assert "chunk_completed" in result.validator_logs
    assert "relays_available" in result.monitor_logs


@pytest.mark.timeout(1200)
def test_discovery_pipeline_promotes_and_monitors_relays_end_to_end(tmp_path: Path) -> None:
    bundle = create_bundle(tmp_path, "discovery-pipeline")
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", "discovery-pipeline")
    prepare_runtime_compose_config(plan)
    configure_runtime_host_gateway(plan, "finder", "validator", "monitor")

    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    resources = None
    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)
        resources = _start_discovery_resources(tmp_path, plan)
        _configure_discovery_pipeline_runtime(plan, resources)
        result = _run_discovery_pipeline(
            stack=stack,
            bundle=bundle,
            plan=plan,
            resources=resources,
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=DISCOVERY_PIPELINE_ARTIFACT_SERVICES)
        _stop_discovery_resources(resources)
        stack.down()

    _assert_discovery_pipeline_results(result, resources)
