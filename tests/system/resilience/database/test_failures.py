from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.system.deployments.baseline import (
    capture_stack_artifacts,
    create_bundle,
    create_stack,
    record_runtime_plan,
)
from tests.system.deployments.runtime_overrides import BOOTSTRAP_SERVICES, start_baseline_relay
from tests.system.harness import LocalTlsWebSocketRuntime, RuntimeAddressPlan, fetch_runtime_value
from tests.system.services.seeder import test_service as seeder_helpers
from tests.system.services.synchronizer import test_service as synchronizer_helpers


if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.system


@pytest.mark.timeout(1200)
def test_seeder_fails_cleanly_when_pool_service_is_missing(tmp_path: Path) -> None:
    bundle = create_bundle(tmp_path, "seeder-pool-startup-failure")
    plan = RuntimeAddressPlan.create(
        "bigbrotr", tmp_path / "runtime", "seeder-pool-startup-failure"
    )
    seeder_helpers.prepare_runtime_compose_config(plan)
    seeder_helpers._configure_seed_runtime(
        plan,
        file_path="static/seed_relays.txt",
        to_validate=True,
        seed_lines=(
            "wss://relay.pool-failure-one.example.com",
            "wss://relay.pool-failure-two.example.com",
        ),
    )
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    run_result = None
    relay_count = 0
    candidate_count = 0
    try:
        stack.up("postgres")
        stack.wait_until_ready(("postgres",), timeout=180.0)

        run_result = stack.run("run", "--rm", "--no-deps", "seeder", check=False)
        bundle.write_text_artifact(
            category="containers",
            subdir="containers",
            name="seeder-pool-startup-failure-run-stdout",
            contents=run_result.stdout,
            suffix=".log",
        )
        bundle.write_text_artifact(
            category="containers",
            subdir="containers",
            name="seeder-pool-startup-failure-run-stderr",
            contents=run_result.stderr,
            suffix=".log",
        )

        relay_count = fetch_runtime_value(plan, "SELECT COUNT(*) FROM relay")
        candidate_count = fetch_runtime_value(
            plan,
            """
            SELECT COUNT(*)
            FROM service_state
            WHERE owner = 'validator'
              AND state_type = 'checkpoint'
            """,
        )
        bundle.capture_db_snapshot(
            "seeder-pool-startup-failure",
            {
                "relay_count": relay_count,
                "candidate_count": candidate_count,
                "returncode": run_result.returncode,
            },
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=("postgres",))
        stack.down()

    assert run_result is not None
    assert run_result.returncode == 1
    combined_output = f"{run_result.stdout}\n{run_result.stderr}"
    assert "connection_failed" in combined_output
    assert "Name or service not known" in combined_output
    assert relay_count == 0
    assert candidate_count == 0


@pytest.mark.timeout(1200)
def test_synchronizer_recovers_after_database_and_pool_outage_without_partial_state(  # noqa: PLR0915
    tmp_path: Path,
) -> None:
    bundle, plan, stack = synchronizer_helpers._prepare_synchronizer_run(
        tmp_path,
        "synchronizer-database-outage-recovery",
        request_timeout=5.0,
        cycle_interval=60.0,
    )
    relay = None
    runtime = None
    relay_url = ""
    initial_events = ()
    recovery_event = None

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        runtime = LocalTlsWebSocketRuntime(
            tmp_path / "synchronizer-database-outage-runtime",
            mode="proxy",
            backend_url=relay.ws_url,
        )
        runtime.start()
        relay_url = synchronizer_helpers._canonical_tls_docker_url(runtime)

        synchronizer_helpers._insert_relay(plan, relay_url, stored_at=1)
        initial_events = synchronizer_helpers._publish_text_events(
            relay,
            "system-synchronizer-db-outage-1",
            "system-synchronizer-db-outage-2",
        )

        stack.up("synchronizer", build=True)
        stack.wait_until_ready(("synchronizer",), timeout=180.0)

        initial_snapshot = synchronizer_helpers._wait_until(
            lambda: {
                "events": synchronizer_helpers._event_rows(plan),
                "observations": synchronizer_helpers._observation_rows(plan),
                "cursors": synchronizer_helpers._cursor_rows(plan),
                "sessions": runtime.sessions(path="/archive"),
            },
            is_ready=lambda current: (
                len(current["events"]) == len(initial_events)
                and len(current["observations"]) == len(initial_events)
                and len(current["cursors"]) == 1
                and current["cursors"][0]["state_key"] == relay_url
                and current["cursors"][0]["cursor_id"] == initial_events[-1].event_id
                and current["cursors"][0]["timestamp"] == initial_events[-1].payload["created_at"]
                and len(current["sessions"]) >= 1
            ),
            description="initial synchronizer database outage baseline",
        )

        stack.run("stop", "pgbouncer", "postgres")
        stack.wait_until_state("pgbouncer", state="exited", timeout=60.0)
        stack.wait_until_state("postgres", state="exited", timeout=60.0)

        recovery_event = synchronizer_helpers._publish_text_events(
            relay,
            "system-synchronizer-db-outage-3",
        )[0]

        stack.up("postgres")
        stack.wait_until_ready(("postgres",), timeout=180.0)

        failed_snapshot = synchronizer_helpers._wait_until(
            lambda: {
                "events": synchronizer_helpers._event_rows(plan),
                "observations": synchronizer_helpers._observation_rows(plan),
                "cursors": synchronizer_helpers._cursor_rows(plan),
                "logs": synchronizer_helpers._synchronizer_logs(stack),
                "error_count": synchronizer_helpers._synchronizer_logs(stack).count(
                    "run_cycle_error"
                ),
            },
            is_ready=lambda current: (
                current["events"] == initial_snapshot["events"]
                and current["observations"] == initial_snapshot["observations"]
                and current["cursors"] == initial_snapshot["cursors"]
                and current["error_count"] >= 1
            ),
            description="synchronizer database and pool outage cycle",
            timeout=180.0,
        )

        stack.up("pgbouncer")
        stack.wait_until_ready(("pgbouncer",), timeout=180.0)

        recovered_snapshot = synchronizer_helpers._wait_until(
            lambda: {
                "events": synchronizer_helpers._event_rows(plan),
                "observations": synchronizer_helpers._observation_rows(plan),
                "cursors": synchronizer_helpers._cursor_rows(plan),
                "logs": synchronizer_helpers._synchronizer_logs(stack),
                "sync_completed": synchronizer_helpers._synchronizer_logs(stack).count(
                    "sync_completed"
                ),
            },
            is_ready=lambda current: (
                recovery_event is not None
                and len(current["events"]) == len(initial_events) + 1
                and len(current["observations"]) == len(initial_events) + 1
                and len(current["cursors"]) == 1
                and current["cursors"][0]["state_key"] == relay_url
                and current["cursors"][0]["cursor_id"] == recovery_event.event_id
                and current["cursors"][0]["timestamp"] == recovery_event.payload["created_at"]
                and current["sync_completed"] >= 2
            ),
            description="synchronizer database outage recovery",
            timeout=180.0,
        )

        synchronizer_helpers._capture_synchronizer_artifacts(
            bundle,
            stack,
            relay=relay,
            runtime=runtime,
            name="synchronizer-database-outage-recovery",
        )
        bundle.capture_db_snapshot(
            "synchronizer-database-outage-recovery",
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
        stack.down()
        if runtime is not None:
            runtime.stop()
        if relay is not None:
            relay.stop()

    expected_initial_event_ids = [event.event_id for event in initial_events]
    assert [row["event_id"] for row in initial_snapshot["events"]] == expected_initial_event_ids
    assert failed_snapshot["events"] == initial_snapshot["events"]
    assert failed_snapshot["observations"] == initial_snapshot["observations"]
    assert failed_snapshot["cursors"] == initial_snapshot["cursors"]
    assert failed_snapshot["error_count"] >= 1

    assert recovery_event is not None
    recovered_event_ids = [row["event_id"] for row in recovered_snapshot["events"]]
    assert recovered_event_ids == [*expected_initial_event_ids, recovery_event.event_id]
    recovered_observation_ids = [row["event_id"] for row in recovered_snapshot["observations"]]
    assert sorted(recovered_observation_ids) == sorted(
        [*expected_initial_event_ids, recovery_event.event_id]
    )
    assert recovered_observation_ids.count(initial_events[-1].event_id) == 1
    assert recovered_snapshot["cursors"] == (
        {
            "state_key": relay_url,
            "timestamp": recovery_event.payload["created_at"],
            "cursor_id": recovery_event.event_id,
        },
    )
