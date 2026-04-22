from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from bigbrotr.models import Relay
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
    FaultControlPortPlan,
    LocalTlsWebSocketRuntime,
    LocalToxiproxyRuntime,
    ProxySpec,
    RuntimeAddressPlan,
    ToxicSpec,
    build_text_note_event,
    execute_runtime,
    fetch_runtime_rows,
    fetch_runtime_value,
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


SYNCHRONIZER_ARTIFACT_SERVICES = (*BOOTSTRAP_SERVICES, "synchronizer")
_RELAY_INSERT_SQL = """
    INSERT INTO relay (url, network, stored_at)
    VALUES ($1, $2, $3)
    ON CONFLICT (url) DO UPDATE
    SET network = EXCLUDED.network,
        stored_at = LEAST(relay.stored_at, EXCLUDED.stored_at)
"""
_UPSERT_CURSOR_SQL = """
    INSERT INTO service_state (owner, state_type, state_key, state_value)
    VALUES (
        'synchronizer',
        'cursor',
        $1,
        jsonb_build_object(
            'timestamp', $2::bigint,
            'id', $3::text
        )
    )
    ON CONFLICT (owner, state_type, state_key) DO UPDATE
    SET state_value = EXCLUDED.state_value
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
_BLACKHOLE_TOXIC = ToxicSpec(
    name="blackhole",
    toxic_type="timeout",
    stream="downstream",
    attributes={"timeout": 0},
)


def _configure_synchronizer_runtime(
    plan: RuntimeAddressPlan,
    *,
    request_timeout: float,
) -> None:
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
    networks["clearnet"] = {"enabled": True, "max_tasks": 1, "timeout": request_timeout}
    networks["tor"] = {"enabled": False}
    networks["i2p"] = {"enabled": False}
    networks["loki"] = {"enabled": False}

    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _prepare_synchronizer_run(
    tmp_path: Path,
    run_name: str,
    *,
    request_timeout: float,
) -> tuple[SystemArtifactBundle, RuntimeAddressPlan, ComposeStack]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", run_name)
    prepare_runtime_compose_config(plan)
    configure_runtime_host_gateway(plan, "synchronizer")
    _configure_synchronizer_runtime(plan, request_timeout=request_timeout)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)
    return bundle, plan, stack


def _canonical_tls_docker_url(runtime: LocalTlsWebSocketRuntime, path: str = "/archive") -> str:
    return runtime.docker_url(path)


def _toxiproxy_internal_ws_url(
    plan: RuntimeAddressPlan,
    toxiproxy: LocalToxiproxyRuntime,
    proxy_port: int,
) -> str:
    inspect_payload = toxiproxy.inspect()
    networks = inspect_payload.get("NetworkSettings", {}).get("Networks", {})
    if not isinstance(networks, dict):
        raise RuntimeError("Toxiproxy inspect payload did not include network settings")

    network_payload = networks.get(plan.data_network_name)
    if not isinstance(network_payload, dict):
        raise RuntimeError(f"Toxiproxy is not attached to network {plan.data_network_name!r}")

    ip_address = network_payload.get("IPAddress")
    if not isinstance(ip_address, str) or not ip_address:
        raise RuntimeError(f"Toxiproxy network {plan.data_network_name!r} did not report an IP")

    return f"ws://{ip_address}:{proxy_port}"


def _insert_relay(plan: RuntimeAddressPlan, url: str, *, stored_at: int) -> None:
    relay = Relay(url)
    execute_runtime(plan, _RELAY_INSERT_SQL, relay.url, relay.network.value, stored_at)


def _upsert_cursor(plan: RuntimeAddressPlan, key: str, *, timestamp: int, cursor_id: str) -> None:
    execute_runtime(plan, _UPSERT_CURSOR_SQL, key, timestamp, cursor_id)


def _event_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _EVENT_ROWS_SQL)


def _observation_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _OBSERVATION_ROWS_SQL)


def _cursor_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _CURSOR_ROWS_SQL)


def _stale_cursor_count(plan: RuntimeAddressPlan, key: str) -> int:
    value = fetch_runtime_value(
        plan,
        """
        SELECT COUNT(*)
        FROM service_state
        WHERE owner = 'synchronizer'
          AND state_type = 'cursor'
          AND state_key = $1
        """,
        key,
    )
    assert isinstance(value, int)
    return value


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


def _synchronizer_logs(stack: ComposeStack) -> str:
    return stack.run("logs", "--no-color", "synchronizer", check=False).stdout


def _restart_synchronizer(stack: ComposeStack) -> None:
    stack.run("stop", "synchronizer")
    stack.wait_until_state("synchronizer", state="exited", timeout=60.0)
    stack.run("rm", "-f", "synchronizer")
    stack.up("synchronizer")
    stack.wait_until_ready(("synchronizer",), timeout=180.0)


def _capture_synchronizer_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    relay: LocalRelayRuntime,
    runtime: LocalTlsWebSocketRuntime | None,
    name: str,
    toxiproxy: LocalToxiproxyRuntime | None = None,
    proxy_listing: dict[str, object] | None = None,
) -> None:
    bundle.capture_container_logs(
        f"{name}-synchronizer",
        _synchronizer_logs(stack),
    )
    bundle.capture_container_logs(f"{name}-relay", relay.logs())
    payload: dict[str, object] = {"relay": relay.inspect()}
    if runtime is not None:
        payload["runtime_sessions"] = [asdict(session) for session in runtime.sessions()]
    if toxiproxy is not None:
        bundle.capture_container_logs(f"{name}-toxiproxy", toxiproxy.logs())
        payload["toxiproxy"] = toxiproxy.inspect()
    if proxy_listing is not None:
        payload["proxy_listing"] = proxy_listing
    bundle.write_json_artifact(
        category="relay",
        subdir="relay",
        name=f"{name}-relay-inspect",
        payload=payload,
    )


@pytest.mark.timeout(900)
def test_synchronizer_archives_events_advances_cursor_and_cleans_stale_state(
    tmp_path: Path,
) -> None:
    bundle, plan, stack = _prepare_synchronizer_run(
        tmp_path,
        "synchronizer-archive-contract",
        request_timeout=5.0,
    )
    relay = None
    runtime = None
    relay_url = ""
    stale_key = "wss://stale-cursor.example.com"
    published: tuple[SignedRelayEvent, ...] = ()
    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        runtime = LocalTlsWebSocketRuntime(
            tmp_path / "synchronizer-archive-runtime",
            mode="proxy",
            backend_url=relay.ws_url,
        )
        runtime.start()
        relay_url = _canonical_tls_docker_url(runtime)

        _insert_relay(plan, relay_url, stored_at=1)
        _upsert_cursor(plan, stale_key, timestamp=25, cursor_id="11" * 32)
        published = _publish_text_events(
            relay,
            "system-synchronizer-archive-1",
            "system-synchronizer-archive-2",
        )

        stack.up("synchronizer", build=True)
        stack.wait_until_ready(("synchronizer",), timeout=180.0)

        snapshot = _wait_until(
            lambda: {
                "events": _event_rows(plan),
                "observations": _observation_rows(plan),
                "cursors": _cursor_rows(plan),
                "stale_count": _stale_cursor_count(plan, stale_key),
                "sessions": runtime.sessions(path="/archive"),
            },
            is_ready=lambda current: (
                len(current["events"]) == len(published)
                and len(current["observations"]) == len(published)
                and len(current["cursors"]) == 1
                and current["cursors"][0]["state_key"] == relay_url
                and current["cursors"][0]["cursor_id"] == published[-1].event_id
                and current["cursors"][0]["timestamp"] == published[-1].payload["created_at"]
                and current["stale_count"] == 0
                and len(current["sessions"]) >= 1
            ),
            description="synchronizer archive ingestion",
        )
        _capture_synchronizer_artifacts(
            bundle,
            stack,
            relay=relay,
            runtime=runtime,
            name="synchronizer-archive-contract",
        )
        bundle.capture_db_snapshot("synchronizer-archive-contract", snapshot)
    finally:
        capture_stack_artifacts(bundle, stack, services=SYNCHRONIZER_ARTIFACT_SERVICES)
        stack.down()
        if runtime is not None:
            runtime.stop()
        if relay is not None:
            relay.stop()

    assert [row["event_id"] for row in snapshot["events"]] == [
        event.event_id for event in published
    ]
    assert [row["content"] for row in snapshot["events"]] == [
        event.payload["content"] for event in published
    ]
    assert sorted(row["event_id"] for row in snapshot["observations"]) == sorted(
        event.event_id for event in published
    )
    assert {row["relay_url"] for row in snapshot["observations"]} == {relay_url}
    assert snapshot["cursors"] == (
        {
            "state_key": relay_url,
            "timestamp": published[-1].payload["created_at"],
            "cursor_id": published[-1].event_id,
        },
    )
    assert snapshot["stale_count"] == 0


@pytest.mark.timeout(900)
def test_synchronizer_restart_resumes_after_fault_without_duplicate_drift(  # noqa: PLR0915
    tmp_path: Path,
) -> None:
    bundle, plan, stack = _prepare_synchronizer_run(
        tmp_path,
        "synchronizer-restart-recovery",
        request_timeout=1.0,
    )
    relay = None
    toxiproxy = None
    relay_url = ""
    initial_events: tuple[SignedRelayEvent, ...] = ()
    recovery_event: SignedRelayEvent | None = None
    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        port_plan = FaultControlPortPlan.for_slot(7)
        proxy_port = port_plan.proxy_port(0)
        toxiproxy = LocalToxiproxyRuntime(
            role="sync",
            runtime_dir=tmp_path / "toxiproxy-runtime",
            network_name=plan.data_network_name,
            port_plan=port_plan,
            exposed_proxy_ports=(proxy_port,),
        )
        toxiproxy.start()
        toxiproxy.wait_until_ready()
        toxiproxy.client.create_proxy(
            ProxySpec(
                name="synchronizer-upstream",
                upstream_host=relay.container_name,
                upstream_port=8080,
                listen_port=proxy_port,
            )
        )
        relay_url = _toxiproxy_internal_ws_url(plan, toxiproxy, proxy_port)

        _insert_relay(plan, relay_url, stored_at=1)
        initial_events = _publish_text_events(
            relay,
            "system-synchronizer-recovery-1",
            "system-synchronizer-recovery-2",
        )

        stack.up("synchronizer", build=True)
        stack.wait_until_ready(("synchronizer",), timeout=180.0)

        initial_snapshot = _wait_until(
            lambda: {
                "events": _event_rows(plan),
                "observations": _observation_rows(plan),
                "cursors": _cursor_rows(plan),
            },
            is_ready=lambda current: (
                len(current["events"]) == len(initial_events)
                and len(current["observations"]) == len(initial_events)
                and len(current["cursors"]) == 1
                and current["cursors"][0]["cursor_id"] == initial_events[-1].event_id
                and current["cursors"][0]["timestamp"] == initial_events[-1].payload["created_at"]
            ),
            description="initial synchronizer archive run",
        )

        time.sleep(1.1)
        recovery_event = _publish_text_events(relay, "system-synchronizer-recovery-3")[0]
        toxiproxy.client.add_toxic("synchronizer-upstream", _BLACKHOLE_TOXIC)

        _restart_synchronizer(stack)

        failed_snapshot = _wait_until(
            lambda: {
                "event_count": fetch_runtime_value(plan, "SELECT COUNT(*) FROM event"),
                "observation_count": fetch_runtime_value(
                    plan, "SELECT COUNT(*) FROM event_observation"
                ),
                "cursors": _cursor_rows(plan),
                "logs": _synchronizer_logs(stack),
            },
            is_ready=lambda current: (
                current["event_count"] == len(initial_events)
                and current["observation_count"] == len(initial_events)
                and len(current["cursors"]) == 1
                and current["cursors"][0]["cursor_id"] == initial_events[-1].event_id
                and current["cursors"][0]["timestamp"] == initial_events[-1].payload["created_at"]
                and "sync_completed events_synced=0" in current["logs"]
            ),
            description="synchronizer fault restart",
        )

        toxiproxy.client.remove_toxic("synchronizer-upstream", _BLACKHOLE_TOXIC.name)
        _restart_synchronizer(stack)

        recovered_snapshot = _wait_until(
            lambda: {
                "events": _event_rows(plan),
                "observations": _observation_rows(plan),
                "cursors": _cursor_rows(plan),
            },
            is_ready=lambda current: (
                recovery_event is not None
                and len(current["events"]) == len(initial_events) + 1
                and len(current["observations"]) == len(initial_events) + 1
                and len(current["cursors"]) == 1
                and current["cursors"][0]["cursor_id"] == recovery_event.event_id
                and current["cursors"][0]["timestamp"] == recovery_event.payload["created_at"]
            ),
            description="synchronizer recovery restart",
        )
        proxy_listing = toxiproxy.client.list_proxies()
        _capture_synchronizer_artifacts(
            bundle,
            stack,
            relay=relay,
            runtime=None,
            toxiproxy=toxiproxy,
            proxy_listing=proxy_listing,
            name="synchronizer-restart-recovery",
        )
        bundle.capture_db_snapshot(
            "synchronizer-restart-recovery",
            {
                "initial": initial_snapshot,
                "failed": failed_snapshot,
                "recovered": recovered_snapshot,
            },
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=SYNCHRONIZER_ARTIFACT_SERVICES)
        stack.down()
        if toxiproxy is not None:
            toxiproxy.stop()
        if relay is not None:
            relay.stop()

    expected_event_ids = [event.event_id for event in initial_events]
    assert [row["event_id"] for row in initial_snapshot["events"]] == expected_event_ids
    assert failed_snapshot["event_count"] == len(initial_events)
    assert failed_snapshot["observation_count"] == len(initial_events)

    assert recovery_event is not None
    recovered_event_ids = [row["event_id"] for row in recovered_snapshot["events"]]
    assert recovered_event_ids == [*expected_event_ids, recovery_event.event_id]
    recovered_observation_ids = [row["event_id"] for row in recovered_snapshot["observations"]]
    assert sorted(recovered_observation_ids) == sorted(
        [*expected_event_ids, recovery_event.event_id]
    )
    assert recovered_observation_ids.count(initial_events[-1].event_id) == 1
    assert recovered_snapshot["cursors"] == (
        {
            "state_key": relay_url,
            "timestamp": recovery_event.payload["created_at"],
            "cursor_id": recovery_event.event_id,
        },
    )
