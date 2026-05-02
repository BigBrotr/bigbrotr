from __future__ import annotations

import asyncio
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
    LocalTlsWebSocketRuntime,
    RuntimeAddressPlan,
    build_text_note_event,
    execute_runtime,
    fetch_runtime_rows,
    publish_event,
)


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.system.harness import (
        ComposeStack,
        LocalRelayRuntime,
        SignedRelayEvent,
        SystemArtifactBundle,
    )


pytestmark = pytest.mark.system


ARCHIVE_PIPELINE_ARTIFACT_SERVICES = (*BOOTSTRAP_SERVICES, "validator", "synchronizer")
_UPSERT_CANDIDATE_SQL = """
    INSERT INTO service_state (owner, state_type, state_key, state_value)
    VALUES (
        'validator',
        'checkpoint',
        $1,
        jsonb_build_object(
            'timestamp', $2::bigint,
            'network', $3::text,
            'failures', $4::int
        )
    )
    ON CONFLICT (owner, state_type, state_key) DO UPDATE
    SET state_value = EXCLUDED.state_value
"""
_RELAY_ROWS_SQL = """
    SELECT url, network, stored_at
    FROM relay
    ORDER BY url
"""
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
_EVENT_ROWS_SQL = """
    SELECT
        encode(id, 'hex') AS event_id,
        kind,
        created_at,
        content
    FROM event
    ORDER BY created_at, encode(id, 'hex')
"""
_OBSERVATION_ROWS_SQL = """
    SELECT
        encode(event_id, 'hex') AS event_id,
        relay_url,
        observed_at
    FROM event_observation
    ORDER BY observed_at, encode(event_id, 'hex'), relay_url
"""
_CURSOR_ROWS_SQL = """
    SELECT
        state_key,
        (state_value->>'timestamp')::bigint AS timestamp,
        state_value->>'id' AS cursor_id
    FROM service_state
    WHERE owner = 'synchronizer'
      AND state_type = 'cursor'
    ORDER BY state_key
"""


@dataclass(slots=True)
class _ArchivePipelineResources:
    relay: LocalRelayRuntime
    runtime: LocalTlsWebSocketRuntime
    relay_url: str


@dataclass(frozen=True, slots=True)
class _ArchivePipelineResult:
    validator_snapshot: dict[str, object]
    initial_snapshot: dict[str, object]
    recovered_snapshot: dict[str, object]
    initial_events: tuple[SignedRelayEvent, ...]
    recovery_event: SignedRelayEvent
    validator_logs: str
    synchronizer_logs: str


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


def _configure_synchronizer_runtime(plan: RuntimeAddressPlan) -> None:
    config_path = plan.runtime_root / "config" / "services" / "synchronizer.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    payload["interval"] = 3600.0

    processing = payload.setdefault("processing", {})
    assert isinstance(processing, dict)
    processing["filters"] = [{"kinds": [1]}]
    processing["since"] = 0
    processing["end_lag"] = 0
    processing["limit"] = 50
    processing["batch_size"] = 100
    processing["allow_insecure"] = True

    timeouts = payload.setdefault("timeouts", {})
    assert isinstance(timeouts, dict)
    timeouts["idle"] = 10.0
    timeouts["max_duration"] = 120.0

    networks = payload.setdefault("networks", {})
    assert isinstance(networks, dict)
    networks["clearnet"] = {"enabled": True, "max_tasks": 1, "timeout": 5.0}
    networks["tor"] = {"enabled": False}
    networks["i2p"] = {"enabled": False}
    networks["loki"] = {"enabled": False}
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _configure_archive_pipeline_runtime(plan: RuntimeAddressPlan) -> None:
    _configure_validator_runtime(plan)
    _configure_synchronizer_runtime(plan)


def _insert_candidate(
    plan: RuntimeAddressPlan,
    url: str,
    *,
    timestamp: int = 0,
    failures: int = 0,
    network: str = "clearnet",
) -> None:
    execute_runtime(plan, _UPSERT_CANDIDATE_SQL, url, timestamp, network, failures)


def _relay_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _RELAY_ROWS_SQL)


def _candidate_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _CANDIDATE_ROWS_SQL)


def _event_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _EVENT_ROWS_SQL)


def _observation_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _OBSERVATION_ROWS_SQL)


def _cursor_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _CURSOR_ROWS_SQL)


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


def _restart_synchronizer(stack: ComposeStack) -> None:
    stack.run("stop", "synchronizer")
    stack.wait_until_state("synchronizer", state="exited", timeout=60.0)
    stack.run("rm", "-f", "synchronizer")
    stack.up("synchronizer")
    stack.wait_until_ready(("synchronizer",), timeout=180.0)


def _publish_text_events(
    relay: LocalRelayRuntime,
    *contents: str,
    delay_between: float = 1.1,
) -> tuple[SignedRelayEvent, ...]:
    published: list[SignedRelayEvent] = []
    for index, content in enumerate(contents):
        event = build_text_note_event(content)
        ok = asyncio.run(publish_event(relay.ws_url, event.payload))
        assert ok.accepted is True
        published.append(event)
        if index != len(contents) - 1:
            time.sleep(delay_between)
    return tuple(published)


def _capture_archive_pipeline_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    resources: _ArchivePipelineResources,
    name: str,
) -> None:
    for service_name in ("validator", "synchronizer"):
        bundle.capture_container_logs(
            f"{name}-{service_name}", stack.run("logs", "--no-color", service_name).stdout
        )
    bundle.capture_container_logs(f"{name}-relay", resources.relay.logs())
    bundle.capture_relay_events(
        f"{name}-runtime-sessions",
        [asdict(session) for session in resources.runtime.sessions(path="/archive")],
    )
    bundle.write_json_artifact(
        category="relay",
        subdir="relay",
        name=f"{name}-relay-inspect",
        payload={"relay": resources.relay.inspect()},
    )


def _start_archive_resources(
    tmp_path: Path,
    plan: RuntimeAddressPlan,
) -> _ArchivePipelineResources:
    relay = start_baseline_relay(plan)
    runtime = LocalTlsWebSocketRuntime(
        tmp_path / "archive-runtime",
        mode="proxy",
        backend_url=relay.ws_url,
    )
    runtime.start()
    return _ArchivePipelineResources(
        relay=relay,
        runtime=runtime,
        relay_url=runtime.docker_url("/archive"),
    )


def _stop_archive_resources(resources: _ArchivePipelineResources | None) -> None:
    if resources is None:
        return
    resources.runtime.stop()
    resources.relay.stop()


def _run_archive_pipeline(
    *,
    stack: ComposeStack,
    bundle: SystemArtifactBundle,
    plan: RuntimeAddressPlan,
    resources: _ArchivePipelineResources,
) -> _ArchivePipelineResult:
    _insert_candidate(plan, resources.relay_url)

    stack.up("validator", build=True)
    stack.wait_until_ready(("validator",), timeout=180.0)
    validator_snapshot = _wait_until(
        lambda: {
            "relays": _relay_rows(plan),
            "candidates": _candidate_rows(plan),
            "sessions": resources.runtime.sessions(path="/archive"),
        },
        is_ready=lambda current: (
            len(current["relays"]) == 1
            and len(current["candidates"]) == 0
            and len(current["sessions"]) >= 1
        ),
        description="validator promotion into archive pipeline",
    )
    bundle.capture_db_snapshot("archive-pipeline-validator", validator_snapshot)

    initial_events = _publish_text_events(
        resources.relay,
        "system-archive-pipeline-1",
        "system-archive-pipeline-2",
    )

    stack.up("synchronizer", build=True)
    stack.wait_until_ready(("synchronizer",), timeout=180.0)
    initial_snapshot = _wait_until(
        lambda: {
            "events": _event_rows(plan),
            "observations": _observation_rows(plan),
            "cursors": _cursor_rows(plan),
            "sessions": resources.runtime.sessions(path="/archive"),
        },
        is_ready=lambda current: (
            len(current["events"]) == len(initial_events)
            and len(current["observations"]) == len(initial_events)
            and len(current["cursors"]) == 1
            and current["cursors"][0]["state_key"] == resources.relay_url
            and current["cursors"][0]["cursor_id"] == initial_events[-1].event_id
            and current["cursors"][0]["timestamp"] == initial_events[-1].payload["created_at"]
            and len(current["sessions"]) >= 2
        ),
        description="initial archive synchronization",
    )
    bundle.capture_db_snapshot("archive-pipeline-initial", initial_snapshot)

    time.sleep(1.1)
    recovery_event = _publish_text_events(resources.relay, "system-archive-pipeline-3")[0]
    _restart_synchronizer(stack)
    recovered_snapshot = _wait_until(
        lambda: {
            "events": _event_rows(plan),
            "observations": _observation_rows(plan),
            "cursors": _cursor_rows(plan),
        },
        is_ready=lambda current: (
            len(current["events"]) == len(initial_events) + 1
            and len(current["observations"]) == len(initial_events) + 1
            and len(current["cursors"]) == 1
            and current["cursors"][0]["state_key"] == resources.relay_url
            and current["cursors"][0]["cursor_id"] == recovery_event.event_id
            and current["cursors"][0]["timestamp"] == recovery_event.payload["created_at"]
        ),
        description="archive synchronization after restart",
    )
    bundle.capture_db_snapshot("archive-pipeline-recovered", recovered_snapshot)
    _capture_archive_pipeline_artifacts(
        bundle,
        stack,
        resources=resources,
        name="archive-pipeline",
    )
    return _ArchivePipelineResult(
        validator_snapshot=validator_snapshot,
        initial_snapshot=initial_snapshot,
        recovered_snapshot=recovered_snapshot,
        initial_events=initial_events,
        recovery_event=recovery_event,
        validator_logs=stack.run("logs", "--no-color", "validator").stdout,
        synchronizer_logs=stack.run("logs", "--no-color", "synchronizer").stdout,
    )


def _assert_archive_pipeline_results(
    result: _ArchivePipelineResult,
    resources: _ArchivePipelineResources,
) -> None:
    assert result.validator_snapshot["candidates"] == ()
    assert {row["url"] for row in result.validator_snapshot["relays"]} == {resources.relay_url}
    assert {row["network"] for row in result.validator_snapshot["relays"]} == {"clearnet"}

    expected_initial_ids = [event.event_id for event in result.initial_events]
    assert [row["event_id"] for row in result.initial_snapshot["events"]] == expected_initial_ids
    assert [row["content"] for row in result.initial_snapshot["events"]] == [
        event.payload["content"] for event in result.initial_events
    ]
    assert sorted(row["event_id"] for row in result.initial_snapshot["observations"]) == sorted(
        expected_initial_ids
    )
    assert {row["relay_url"] for row in result.initial_snapshot["observations"]} == {
        resources.relay_url
    }

    recovered_event_ids = [row["event_id"] for row in result.recovered_snapshot["events"]]
    assert recovered_event_ids == [*expected_initial_ids, result.recovery_event.event_id]
    recovered_observation_ids = [
        row["event_id"] for row in result.recovered_snapshot["observations"]
    ]
    assert sorted(recovered_observation_ids) == sorted(
        [*expected_initial_ids, result.recovery_event.event_id]
    )
    assert all(recovered_observation_ids.count(event_id) == 1 for event_id in recovered_event_ids)
    assert result.recovered_snapshot["cursors"] == (
        {
            "state_key": resources.relay_url,
            "timestamp": result.recovery_event.payload["created_at"],
            "cursor_id": result.recovery_event.event_id,
        },
    )

    assert "chunk_completed" in result.validator_logs
    assert "sync_completed" in result.synchronizer_logs


@pytest.mark.timeout(1200)
def test_archive_pipeline_validated_relay_is_archived_and_resumes_after_restart(
    tmp_path: Path,
) -> None:
    bundle = create_bundle(tmp_path, "archive-pipeline")
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", "archive-pipeline")
    prepare_runtime_compose_config(plan)
    configure_runtime_host_gateway(plan, "validator", "synchronizer")
    _configure_archive_pipeline_runtime(plan)

    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    resources = None
    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)
        resources = _start_archive_resources(tmp_path, plan)
        result = _run_archive_pipeline(
            stack=stack,
            bundle=bundle,
            plan=plan,
            resources=resources,
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=ARCHIVE_PIPELINE_ARTIFACT_SERVICES)
        _stop_archive_resources(resources)
        stack.down()

    _assert_archive_pipeline_results(result, resources)
