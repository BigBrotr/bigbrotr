from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.system.deployments.baseline import capture_stack_artifacts
from tests.system.deployments.runtime_overrides import BOOTSTRAP_SERVICES, start_baseline_relay
from tests.system.harness import FaultControlPortPlan, LocalToxiproxyRuntime, ProxySpec
from tests.system.services.assertor import test_service as assertor_helpers


if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.system


def _start_faulted_assertor_path(
    tmp_path: Path,
    plan: object,
    stack: object,
) -> tuple[object, LocalToxiproxyRuntime]:
    relay = start_baseline_relay(plan)
    port_plan = FaultControlPortPlan.for_slot(79)
    proxy_port = port_plan.proxy_port(0)
    toxiproxy = LocalToxiproxyRuntime(
        role="assertor-restart-interruption",
        runtime_dir=tmp_path / "toxiproxy-runtime",
        network_name=plan.data_network_name,
        network_aliases=("assertor-restart-toxiproxy",),
        port_plan=port_plan,
        exposed_proxy_ports=(proxy_port,),
    )
    toxiproxy.start()
    toxiproxy.wait_until_ready()
    toxiproxy.client.create_proxy(
        ProxySpec(
            name="assertor-restart-upstream",
            upstream_host=relay.container_name,
            upstream_port=8080,
            listen_port=proxy_port,
        )
    )
    relay_url = assertor_helpers._toxiproxy_internal_ws_url(plan, toxiproxy, proxy_port)
    assertor_helpers._configure_assertor_runtime(
        plan,
        relay_url=relay_url,
        relay_hint=assertor_helpers._PUBLIC_RELAY_HINT,
        interval=60.0,
    )
    stack.up("assertor", build=True)
    stack.wait_until_ready(("assertor",), timeout=180.0)
    return relay, toxiproxy


def _wait_for_provider_only_state(
    plan: object,
    stack: object,
    relay_ws_url: str,
) -> dict[str, object]:
    snapshot = assertor_helpers._wait_until(
        lambda: {
            "events": assertor_helpers._captured_assertor_events(relay_ws_url),
            "checkpoints": assertor_helpers._assertor_checkpoints(plan),
            "cycle_count": assertor_helpers._assertor_log_count(stack, "cycle_completed"),
        },
        is_ready=lambda current: (
            len(current["events"]) == 2
            and len(current["checkpoints"]) == 2
            and current["cycle_count"] >= 1
        ),
        description="assertor initial provider-only state",
    )
    assert set(assertor_helpers._state_rows_by_key(snapshot["checkpoints"])) == {
        f"{assertor_helpers._ALGORITHM_ID}:0:provider_profile",
        f"{assertor_helpers._ALGORITHM_ID}:10040:trusted_provider_list",
    }
    return snapshot


def _wait_for_failed_cycle(
    plan: object,
    stack: object,
    relay_ws_url: str,
    *,
    min_cycle_count: int,
) -> dict[str, object]:
    return assertor_helpers._wait_until(
        lambda: {
            "events": assertor_helpers._captured_assertor_events(relay_ws_url),
            "checkpoints": assertor_helpers._assertor_checkpoints(plan),
            "cycle_count": assertor_helpers._assertor_log_count(stack, "cycle_completed"),
            "logs": assertor_helpers._assertor_logs(stack),
        },
        is_ready=lambda current: (
            current["cycle_count"] >= min_cycle_count and "user_assertion_failed" in current["logs"]
        ),
        description="assertor failed publish cycle after restart interruption",
        timeout=150.0,
    )


def _restart_failure_snapshot(
    plan: object,
    stack: object,
    relay_ws_url: str,
) -> dict[str, object]:
    logs = assertor_helpers._assertor_logs(stack)
    services = {status.service: status for status in stack.ps(all_services=True)}
    service = services.get("assertor")
    return {
        "events": assertor_helpers._captured_assertor_events(relay_ws_url),
        "checkpoints": assertor_helpers._assertor_checkpoints(plan),
        "logs": logs,
        "startup_failure_count": logs.count("assertor could not connect to any publishing relay"),
        "service_state": None if service is None else service.state,
        "service_health": None if service is None else service.health,
    }


def _wait_for_restart_startup_failure(
    plan: object,
    stack: object,
    relay_ws_url: str,
    *,
    min_startup_failure_count: int,
) -> dict[str, object]:
    return assertor_helpers._wait_until(
        lambda: _restart_failure_snapshot(plan, stack, relay_ws_url),
        is_ready=lambda current: current["startup_failure_count"] >= min_startup_failure_count,
        description="assertor startup failure after interrupted restart",
        timeout=150.0,
    )


def _assert_partial_state_unchanged(
    snapshot: dict[str, object],
    *,
    initial_event_ids: list[str],
    initial_state: dict[str, dict[str, int | str]],
) -> None:
    assert [str(frame.event["id"]) for frame in snapshot["events"]] == initial_event_ids
    assert assertor_helpers._state_rows_by_key(snapshot["checkpoints"]) == initial_state


@pytest.mark.timeout(1500)
def test_assertor_repeated_restarts_keep_partial_publish_state_honest_until_recovery(
    tmp_path: Path,
) -> None:
    bundle, plan, stack = assertor_helpers._prepare_assertor_run(
        tmp_path,
        "assertor-restart-interruption",
        slot=78,
    )
    relay = None
    toxiproxy = None

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay, toxiproxy = _start_faulted_assertor_path(tmp_path, plan, stack)

        initial_snapshot = _wait_for_provider_only_state(plan, stack, relay.ws_url)
        initial_event_ids = [str(frame.event["id"]) for frame in initial_snapshot["events"]]
        initial_state = assertor_helpers._state_rows_by_key(initial_snapshot["checkpoints"])
        assertor_helpers._capture_assertor_artifacts(
            bundle,
            stack,
            relay=relay,
            toxiproxy=toxiproxy,
            name="assertor-restart-initial",
            snapshot=initial_snapshot,
        )

        toxiproxy.client.add_toxic("assertor-restart-upstream", assertor_helpers._FAULT_RESET_TOXIC)
        assertor_helpers._seed_assertor_inputs(plan)

        failed_snapshot = _wait_for_failed_cycle(
            plan,
            stack,
            relay.ws_url,
            min_cycle_count=2,
        )
        assert [str(frame.event["id"]) for frame in failed_snapshot["events"]] == initial_event_ids
        assert assertor_helpers._state_rows_by_key(failed_snapshot["checkpoints"]) == initial_state
        assertor_helpers._capture_assertor_artifacts(
            bundle,
            stack,
            relay=relay,
            toxiproxy=toxiproxy,
            name="assertor-restart-failed-cycle",
            snapshot=failed_snapshot,
        )

        restart_snapshots: list[dict[str, object]] = []
        for startup_failure_count, restart_index in enumerate((1, 2), start=1):
            stack.run("restart", "assertor")
            restart_snapshot = _wait_for_restart_startup_failure(
                plan,
                stack,
                relay.ws_url,
                min_startup_failure_count=startup_failure_count,
            )
            _assert_partial_state_unchanged(
                restart_snapshot,
                initial_event_ids=initial_event_ids,
                initial_state=initial_state,
            )
            assert restart_snapshot["service_state"] in {"restarting", "running", "exited"}
            restart_snapshots.append(restart_snapshot)
            assertor_helpers._capture_assertor_artifacts(
                bundle,
                stack,
                relay=relay,
                toxiproxy=toxiproxy,
                name=f"assertor-restart-failed-restart-{restart_index}",
                snapshot=restart_snapshot,
            )

        toxiproxy.client.remove_toxic(
            "assertor-restart-upstream",
            assertor_helpers._FAULT_RESET_TOXIC.name,
        )
        stack.run("restart", "assertor")
        stack.wait_until_ready(("assertor",), timeout=180.0)

        recovered_snapshot = assertor_helpers._wait_until(
            lambda: {
                "events": assertor_helpers._captured_assertor_events(relay.ws_url),
                "checkpoints": assertor_helpers._assertor_checkpoints(plan),
                "cycle_count": assertor_helpers._assertor_log_count(stack, "cycle_completed"),
            },
            is_ready=lambda current: (
                len(current["events"]) == 6
                and len(current["checkpoints"]) == 6
                and current["cycle_count"] >= int(failed_snapshot["cycle_count"]) + 1
            ),
            description="assertor recovers after repeated restart interruptions",
        )
        assertor_helpers._assert_full_provider_package(
            recovered_snapshot["events"],
            expected_pubkey=assertor_helpers._expected_assertor_pubkey(plan),
            relay_hint=assertor_helpers._PUBLIC_RELAY_HINT,
        )
        assertor_helpers._capture_assertor_artifacts(
            bundle,
            stack,
            relay=relay,
            toxiproxy=toxiproxy,
            name="assertor-restart-recovered",
            snapshot={
                "initial": initial_snapshot,
                "failed": failed_snapshot,
                "restarts": restart_snapshots,
                "recovered": recovered_snapshot,
            },
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=assertor_helpers.ASSERTOR_ARTIFACT_SERVICES)
        if toxiproxy is not None:
            toxiproxy.stop()
        if relay is not None:
            relay.stop()
        stack.down(timeout=30)
