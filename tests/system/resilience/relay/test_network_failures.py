from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from tests.system.deployments.baseline import capture_stack_artifacts
from tests.system.deployments.runtime_overrides import BOOTSTRAP_SERVICES, start_baseline_relay
from tests.system.harness import (
    FaultControlPortPlan,
    LocalTlsWebSocketRuntime,
    LocalToxiproxyRuntime,
    ProxySpec,
)
from tests.system.services.monitor import test_service as monitor_helpers
from tests.system.services.synchronizer import test_service as synchronizer_helpers


if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.system


def _start_monitor_timeout_path(
    tmp_path: Path,
    *,
    plan: object,
    relay: object,
) -> tuple[LocalToxiproxyRuntime, LocalTlsWebSocketRuntime, str]:
    port_plan = FaultControlPortPlan.for_slot(81)
    proxy_port = port_plan.proxy_port(0)
    toxiproxy = LocalToxiproxyRuntime(
        role="monitor-relay-timeout",
        runtime_dir=tmp_path / "monitor-toxiproxy-runtime",
        network_name=plan.data_network_name,
        port_plan=port_plan,
        exposed_proxy_ports=(proxy_port,),
    )
    toxiproxy.start()
    toxiproxy.wait_until_ready()
    toxiproxy.client.create_proxy(
        ProxySpec(
            name="monitor-upstream",
            upstream_host=relay.container_name,
            upstream_port=8080,
            listen_port=proxy_port,
        )
    )
    degraded_backend_url = toxiproxy.proxy_ws_url(proxy_port)
    degraded_runtime = LocalTlsWebSocketRuntime(
        tmp_path / "monitor-degraded-runtime",
        mode="proxy",
        backend_url=degraded_backend_url,
        http_backend_url=degraded_backend_url.replace("ws://", "http://", 1),
    )
    degraded_runtime.start()
    degraded_url = monitor_helpers._canonical_tls_docker_url(degraded_runtime)
    return toxiproxy, degraded_runtime, degraded_url


@pytest.mark.timeout(1200)
def test_monitor_recovers_degraded_subset_after_timeout_without_restart(  # noqa: PLR0915
    tmp_path: Path,
) -> None:
    bundle, plan, stack = monitor_helpers._prepare_monitor_run(
        tmp_path,
        "monitor-relay-timeout-recovery",
        discovery_interval=60.0,
        timeout=1.0,
        cycle_interval=60.0,
    )
    relay = None
    toxiproxy = None
    good_runtime = None
    degraded_runtime = None
    good_url = ""
    degraded_url = ""
    failed_snapshot: dict[str, object] | None = None
    recovered_snapshot: dict[str, object] | None = None

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        good_runtime = LocalTlsWebSocketRuntime(
            tmp_path / "monitor-good-runtime",
            mode="proxy",
            backend_url=relay.ws_url,
            http_backend_url=relay.ws_url.replace("ws://", "http://", 1),
        )
        good_runtime.start()
        good_url = monitor_helpers._canonical_tls_docker_url(good_runtime)

        toxiproxy, degraded_runtime, degraded_url = _start_monitor_timeout_path(
            tmp_path,
            plan=plan,
            relay=relay,
        )
        toxiproxy.client.add_toxic("monitor-upstream", monitor_helpers._BLACKHOLE_TOXIC)

        monitor_helpers._insert_relay(plan, good_url, stored_at=1)
        monitor_helpers._insert_relay(plan, degraded_url, stored_at=2)

        stack.up("monitor", build=True)
        stack.wait_until_ready(("monitor",), timeout=180.0)

        failed_snapshot = monitor_helpers._wait_until(
            lambda: {
                "documents": monitor_helpers._monitor_documents(plan),
                "checkpoints": monitor_helpers._monitor_checkpoints(plan),
                "log_count": monitor_helpers._monitor_log_count(stack, "relays_available"),
                "good_sessions": good_runtime.sessions(),
                "degraded_sessions": degraded_runtime.sessions(),
            },
            is_ready=lambda current: (
                len(current["documents"]) >= 4
                and len(current["checkpoints"]) == 2
                and current["log_count"] >= 1
                and len(current["good_sessions"]) >= 1
                and len(current["degraded_sessions"]) >= 1
                and {row["relay_url"] for row in current["documents"]} == {good_url, degraded_url}
                and any(
                    row["relay_url"] == degraded_url
                    and row["role"] == "nip11_info"
                    and monitor_helpers._decode_document_data(row["data"])["logs"]["success"]
                    is False
                    for row in current["documents"]
                )
                and any(
                    row["relay_url"] == degraded_url
                    and row["role"] == "nip66_rtt"
                    and monitor_helpers._decode_document_data(row["data"])["logs"]["write_reason"]
                    == "TimeoutError"
                    for row in current["documents"]
                )
            ),
            description="monitor degraded relay timeout cycle",
            timeout=120.0,
        )

        toxiproxy.client.remove_toxic("monitor-upstream", monitor_helpers._BLACKHOLE_TOXIC.name)
        recovered_snapshot = monitor_helpers._wait_until(
            lambda: {
                "documents": monitor_helpers._monitor_documents(plan),
                "checkpoints": monitor_helpers._monitor_checkpoints(plan),
                "log_count": monitor_helpers._monitor_log_count(stack, "relays_available"),
                "good_sessions": good_runtime.sessions(),
                "degraded_sessions": degraded_runtime.sessions(),
            },
            is_ready=lambda current: (
                len(current["documents"]) >= 4
                and len(current["checkpoints"]) == 2
                and current["log_count"] >= 2
                and {row["relay_url"] for row in current["documents"]} == {good_url, degraded_url}
                and any(
                    row["relay_url"] == degraded_url
                    and row["role"] == "nip11_info"
                    and monitor_helpers._decode_document_data(row["data"])["logs"]["success"]
                    is True
                    for row in current["documents"]
                )
                and any(
                    row["relay_url"] == degraded_url
                    and row["role"] == "nip66_rtt"
                    and monitor_helpers._decode_document_data(row["data"])["logs"]["write_reason"]
                    != "TimeoutError"
                    for row in current["documents"]
                )
            ),
            description="monitor degraded relay recovery without restart",
            timeout=150.0,
        )
        proxy_listing = toxiproxy.client.list_proxies()
        monitor_helpers._capture_monitor_artifacts(
            bundle,
            stack,
            relay=relay,
            toxiproxy=toxiproxy,
            good_runtime=good_runtime,
            degraded_runtime=degraded_runtime,
            proxy_listing=proxy_listing,
            name="monitor-relay-timeout-recovery",
        )
        bundle.capture_db_snapshot(
            "monitor-relay-timeout-recovery",
            {
                "failed": failed_snapshot,
                "recovered": recovered_snapshot,
            },
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=monitor_helpers.MONITOR_ARTIFACT_SERVICES)
        if degraded_runtime is not None:
            degraded_runtime.stop()
        if good_runtime is not None:
            good_runtime.stop()
        if toxiproxy is not None:
            toxiproxy.stop()
        if relay is not None:
            relay.stop()
        stack.down()

    assert failed_snapshot is not None
    assert recovered_snapshot is not None
    failed_relays = {row["relay_url"] for row in failed_snapshot["documents"]}
    recovered_relays = {row["relay_url"] for row in recovered_snapshot["documents"]}
    assert failed_relays == {good_url, degraded_url}
    assert recovered_relays == {good_url, degraded_url}
    failed_degraded_nip11_rows = [
        row
        for row in failed_snapshot["documents"]
        if row["relay_url"] == degraded_url and row["role"] == "nip11_info"
    ]
    assert failed_degraded_nip11_rows
    failed_degraded_nip11 = monitor_helpers._decode_document_data(
        failed_degraded_nip11_rows[-1]["data"]
    )
    assert failed_degraded_nip11["logs"]["success"] is False
    assert failed_degraded_nip11["logs"]["reason"] == "HTTP 504"
    failed_degraded_rtt_rows = [
        row
        for row in failed_snapshot["documents"]
        if row["relay_url"] == degraded_url and row["role"] == "nip66_rtt"
    ]
    assert failed_degraded_rtt_rows
    failed_degraded_rtt = monitor_helpers._decode_document_data(
        failed_degraded_rtt_rows[-1]["data"]
    )
    assert failed_degraded_rtt["logs"]["open_success"] is True
    assert failed_degraded_rtt["logs"]["write_reason"] == "TimeoutError"
    recovered_degraded_nip11_rows = [
        row
        for row in recovered_snapshot["documents"]
        if row["relay_url"] == degraded_url and row["role"] == "nip11_info"
    ]
    assert recovered_degraded_nip11_rows
    recovered_degraded_nip11 = monitor_helpers._decode_document_data(
        recovered_degraded_nip11_rows[-1]["data"]
    )
    assert recovered_degraded_nip11["logs"]["success"] is True
    degraded_rtt_rows = [
        row
        for row in recovered_snapshot["documents"]
        if row["relay_url"] == degraded_url and row["role"] == "nip66_rtt"
    ]
    assert degraded_rtt_rows
    degraded_rtt = monitor_helpers._decode_document_data(degraded_rtt_rows[-1]["data"])
    assert degraded_rtt["logs"]["open_success"] is True
    assert degraded_rtt["logs"]["write_reason"] != "TimeoutError"


@pytest.mark.timeout(1200)
def test_synchronizer_recovers_after_transient_disconnect_without_restart(
    tmp_path: Path,
) -> None:
    bundle, plan, stack = synchronizer_helpers._prepare_synchronizer_run(
        tmp_path,
        "synchronizer-relay-disconnect-recovery",
        request_timeout=1.0,
        cycle_interval=60.0,
    )
    relay = None
    toxiproxy = None
    relay_url = ""
    initial_events = ()
    recovery_event = None

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        port_plan = FaultControlPortPlan.for_slot(82)
        proxy_port = port_plan.proxy_port(0)
        toxiproxy = LocalToxiproxyRuntime(
            role="synchronizer-relay-disconnect",
            runtime_dir=tmp_path / "synchronizer-toxiproxy-runtime",
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
        relay_url = synchronizer_helpers._toxiproxy_internal_ws_url(plan, toxiproxy, proxy_port)

        synchronizer_helpers._insert_relay(plan, relay_url, stored_at=1)
        initial_events = synchronizer_helpers._publish_text_events(
            relay,
            "system-synchronizer-disconnect-1",
            "system-synchronizer-disconnect-2",
        )

        stack.up("synchronizer", build=True)
        stack.wait_until_ready(("synchronizer",), timeout=180.0)

        initial_snapshot = synchronizer_helpers._wait_until(
            lambda: {
                "events": synchronizer_helpers._event_rows(plan),
                "observations": synchronizer_helpers._observation_rows(plan),
                "cursors": synchronizer_helpers._cursor_rows(plan),
            },
            is_ready=lambda current: (
                len(current["events"]) == len(initial_events)
                and len(current["observations"]) == len(initial_events)
                and len(current["cursors"]) == 1
                and current["cursors"][0]["cursor_id"] == initial_events[-1].event_id
                and current["cursors"][0]["timestamp"] == initial_events[-1].payload["created_at"]
            ),
            description="initial synchronizer archive cycle",
            timeout=120.0,
        )

        time.sleep(1.1)
        recovery_event = synchronizer_helpers._publish_text_events(
            relay,
            "system-synchronizer-disconnect-3",
        )[0]
        toxiproxy.client.set_proxy_enabled("synchronizer-upstream", enabled=False)

        failed_snapshot = synchronizer_helpers._wait_until(
            lambda: {
                "events": synchronizer_helpers._event_rows(plan),
                "observations": synchronizer_helpers._observation_rows(plan),
                "cursors": synchronizer_helpers._cursor_rows(plan),
                "logs": synchronizer_helpers._synchronizer_logs(stack),
                "cycles": synchronizer_helpers._synchronizer_logs(stack).count("sync_completed"),
            },
            is_ready=lambda current: (
                len(current["events"]) == len(initial_events)
                and len(current["observations"]) == len(initial_events)
                and len(current["cursors"]) == 1
                and current["cursors"][0]["cursor_id"] == initial_events[-1].event_id
                and current["cursors"][0]["timestamp"] == initial_events[-1].payload["created_at"]
                and current["cycles"] >= 2
                and "sync_completed events_synced=0" in current["logs"]
            ),
            description="synchronizer transient disconnect cycle",
            timeout=150.0,
        )

        toxiproxy.client.set_proxy_enabled("synchronizer-upstream", enabled=True)
        recovered_snapshot = synchronizer_helpers._wait_until(
            lambda: {
                "events": synchronizer_helpers._event_rows(plan),
                "observations": synchronizer_helpers._observation_rows(plan),
                "cursors": synchronizer_helpers._cursor_rows(plan),
                "cycles": synchronizer_helpers._synchronizer_logs(stack).count("sync_completed"),
            },
            is_ready=lambda current: (
                recovery_event is not None
                and len(current["events"]) == len(initial_events) + 1
                and len(current["observations"]) == len(initial_events) + 1
                and len(current["cursors"]) == 1
                and current["cursors"][0]["cursor_id"] == recovery_event.event_id
                and current["cursors"][0]["timestamp"] == recovery_event.payload["created_at"]
                and current["cycles"] >= 3
            ),
            description="synchronizer disconnect recovery without restart",
            timeout=180.0,
        )
        proxy_listing = toxiproxy.client.list_proxies()
        synchronizer_helpers._capture_synchronizer_artifacts(
            bundle,
            stack,
            relay=relay,
            runtime=None,
            toxiproxy=toxiproxy,
            proxy_listing=proxy_listing,
            name="synchronizer-relay-disconnect-recovery",
        )
        bundle.capture_db_snapshot(
            "synchronizer-relay-disconnect-recovery",
            {
                "initial": initial_snapshot,
                "failed": failed_snapshot,
                "recovered": recovered_snapshot,
            },
        )
    finally:
        capture_stack_artifacts(
            bundle,
            stack,
            services=synchronizer_helpers.SYNCHRONIZER_ARTIFACT_SERVICES,
        )
        if toxiproxy is not None:
            toxiproxy.stop()
        if relay is not None:
            relay.stop()
        stack.down()

    expected_event_ids = [event.event_id for event in initial_events]
    assert [row["event_id"] for row in initial_snapshot["events"]] == expected_event_ids
    assert failed_snapshot["events"] == initial_snapshot["events"]
    assert failed_snapshot["observations"] == initial_snapshot["observations"]
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
