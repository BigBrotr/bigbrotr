from __future__ import annotations

import time
from dataclasses import asdict
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
    prepare_runtime_compose_config,
    start_baseline_relay,
)
from tests.system.harness import (
    LocalHttpFixtureRuntime,
    LocalTlsWebSocketRuntime,
    RuntimeAddressPlan,
    execute_runtime,
    fetch_runtime_rows,
)


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.system.harness import ComposeStack, LocalRelayRuntime, SystemArtifactBundle


pytestmark = pytest.mark.system


VALIDATOR_ARTIFACT_SERVICES = (*BOOTSTRAP_SERVICES, "validator")
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


def _configure_validator_runtime(plan: RuntimeAddressPlan, *, retry_interval: float) -> None:
    config_path = plan.runtime_root / "config" / "services" / "validator.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    payload["interval"] = 3600.0
    processing = payload.setdefault("processing", {})
    assert isinstance(processing, dict)
    processing["interval"] = retry_interval
    processing["chunk_size"] = 10
    processing["max_candidates"] = 10
    processing["allow_insecure"] = True

    networks = payload.setdefault("networks", {})
    assert isinstance(networks, dict)
    networks["clearnet"] = {"enabled": True, "max_tasks": 2, "timeout": 5.0}
    networks["tor"] = {"enabled": False}

    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _prepare_validator_run(
    tmp_path: Path,
    run_name: str,
    *,
    retry_interval: float,
) -> tuple[SystemArtifactBundle, RuntimeAddressPlan, ComposeStack]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", run_name)
    prepare_runtime_compose_config(plan)
    _configure_validator_runtime(plan, retry_interval=retry_interval)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)
    return bundle, plan, stack


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


def _wait_until(
    fetch_snapshot: Callable[[], Any],
    *,
    is_ready: Callable[[Any], bool],
    description: str,
    timeout: float = 60.0,
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


def _validator_log_contains(stack: ComposeStack, text: str) -> bool:
    return text in stack.run("logs", "--no-color", "validator", check=False).stdout


def _restart_validator(stack: ComposeStack) -> None:
    stack.run("stop", "validator")
    stack.wait_until_state("validator", state="exited", timeout=60.0)
    stack.run("rm", "-f", "validator")
    stack.up("validator")
    stack.wait_until_ready(("validator",), timeout=180.0)


def _capture_validator_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    relay: LocalRelayRuntime | None = None,
    valid_runtime: LocalTlsWebSocketRuntime | None = None,
    invalid_http: LocalHttpFixtureRuntime | None = None,
    name: str,
) -> None:
    bundle.capture_container_logs(
        f"{name}-validator", stack.run("logs", "--no-color", "validator").stdout
    )
    if relay is not None:
        bundle.write_text_artifact(
            category="relay",
            subdir="relay",
            name=f"{name}-baseline-relay",
            contents=relay.logs(),
            suffix=".log",
        )
    if valid_runtime is not None:
        bundle.capture_relay_events(
            f"{name}-valid-runtime-sessions",
            [asdict(session) for session in valid_runtime.sessions()],
        )
    if invalid_http is not None:
        bundle.write_json_artifact(
            category="relay",
            subdir="relay",
            name=f"{name}-invalid-http-requests",
            payload=[asdict(request) for request in invalid_http.requests()],
        )


@pytest.mark.timeout(900)
def test_validator_promotes_valid_relay_and_isolates_failed_candidate(tmp_path: Path) -> None:
    bundle, plan, stack = _prepare_validator_run(
        tmp_path,
        "validator-valid-and-invalid",
        retry_interval=3600.9,
    )
    relay = None
    valid_runtime = None
    invalid_http = None
    valid_url = ""
    invalid_url = ""
    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        valid_runtime = LocalTlsWebSocketRuntime(
            tmp_path / "valid-wss-runtime",
            mode="proxy",
            backend_url=relay.ws_url,
        )
        invalid_http = LocalHttpFixtureRuntime(tmp_path / "invalid-http-runtime")
        valid_runtime.start()
        invalid_http.start()
        invalid_http.clear_requests()

        valid_url = valid_runtime.docker_url("/relay")
        invalid_url = f"wss://{invalid_http.docker_host}:{invalid_http.port}/invalid"
        _insert_candidate(plan, valid_url)
        _insert_candidate(plan, invalid_url)

        stack.up("validator", build=True)
        stack.wait_until_ready(("validator",), timeout=180.0)

        snapshot = _wait_until(
            lambda: {
                "relays": _relay_rows(plan),
                "candidates": _candidate_rows(plan),
                "valid_sessions": valid_runtime.sessions(path="/relay"),
            },
            is_ready=lambda current: (
                len(current["relays"]) == 1
                and len(current["candidates"]) == 1
                and len(current["valid_sessions"]) >= 1
                and current["candidates"][0]["state_key"] == invalid_url
                and current["candidates"][0]["failures"] == 1
            ),
            description="validator promotion and failure isolation",
        )
        _capture_validator_artifacts(
            bundle,
            stack,
            relay=relay,
            valid_runtime=valid_runtime,
            invalid_http=invalid_http,
            name="validator-valid-and-invalid",
        )
        bundle.capture_db_snapshot("validator-valid-and-invalid", snapshot)
        validator_logs = stack.run("logs", "--no-color", "validator").stdout
    finally:
        capture_stack_artifacts(bundle, stack, services=VALIDATOR_ARTIFACT_SERVICES)
        if valid_runtime is not None:
            valid_runtime.stop()
        if invalid_http is not None:
            invalid_http.stop()
        if relay is not None:
            relay.stop()
        stack.down()

    assert tuple(row["url"] for row in snapshot["relays"]) == (valid_url,)
    assert {row["network"] for row in snapshot["relays"]} == {"clearnet"}
    assert all(
        isinstance(row["stored_at"], int) and row["stored_at"] > 0 for row in snapshot["relays"]
    )
    assert tuple(row["state_key"] for row in snapshot["candidates"]) == (invalid_url,)
    assert {row["network"] for row in snapshot["candidates"]} == {"clearnet"}
    assert {row["failures"] for row in snapshot["candidates"]} == {1}
    assert all(
        isinstance(row["timestamp"], int) and row["timestamp"] > 0 for row in snapshot["candidates"]
    )
    assert len(snapshot["valid_sessions"]) >= 1
    assert "chunk_completed" in validator_logs
    assert "validate_unexpected_error" not in validator_logs


@pytest.mark.timeout(900)
def test_validator_restart_honors_retry_interval_for_recent_failures(tmp_path: Path) -> None:
    bundle, plan, stack = _prepare_validator_run(
        tmp_path,
        "validator-retry-backoff",
        retry_interval=3600.9,
    )

    invalid_http = None
    invalid_url = ""
    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        invalid_http = LocalHttpFixtureRuntime(tmp_path / "invalid-http-runtime")
        invalid_http.start()
        invalid_http.clear_requests()

        invalid_url = f"wss://{invalid_http.docker_host}:{invalid_http.port}/retry"
        _insert_candidate(plan, invalid_url)

        stack.up("validator", build=True)
        stack.wait_until_ready(("validator",), timeout=180.0)

        first_snapshot = _wait_until(
            lambda: {
                "relays": _relay_rows(plan),
                "candidates": _candidate_rows(plan),
            },
            is_ready=lambda current: (
                len(current["relays"]) == 0
                and len(current["candidates"]) == 1
                and current["candidates"][0]["failures"] == 1
            ),
            description="validator initial failed-attempt persistence",
        )

        _restart_validator(stack)
        _wait_until(
            lambda: _validator_log_contains(stack, "candidates_available"),
            is_ready=bool,
            description="validator restart cycle completion",
        )

        second_snapshot = {
            "relays": _relay_rows(plan),
            "candidates": _candidate_rows(plan),
        }
        _capture_validator_artifacts(
            bundle,
            stack,
            invalid_http=invalid_http,
            name="validator-retry-backoff",
        )
        bundle.capture_db_snapshot("validator-retry-backoff-first", first_snapshot)
        bundle.capture_db_snapshot("validator-retry-backoff-second", second_snapshot)
        validator_logs = stack.run("logs", "--no-color", "validator").stdout
    finally:
        capture_stack_artifacts(bundle, stack, services=VALIDATOR_ARTIFACT_SERVICES)
        if invalid_http is not None:
            invalid_http.stop()
        stack.down()

    assert invalid_url
    assert first_snapshot["relays"] == ()
    assert tuple(row["state_key"] for row in first_snapshot["candidates"]) == (invalid_url,)
    assert first_snapshot["candidates"][0]["failures"] == 1
    assert second_snapshot["relays"] == ()
    assert second_snapshot["candidates"] == first_snapshot["candidates"]
    assert "candidates_available" in validator_logs
    assert "chunk_completed" not in validator_logs
