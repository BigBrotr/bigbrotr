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
    configure_runtime_host_gateway,
    prepare_runtime_compose_config,
)
from tests.system.harness import LocalHttpFixtureRuntime, RuntimeAddressPlan, fetch_runtime_rows


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.system.harness import ComposeStack, SystemArtifactBundle


pytestmark = pytest.mark.system


FINDER_BOOTSTRAP_SERVICES = ("postgres", "pgbouncer")
FINDER_ARTIFACT_SERVICES = (*FINDER_BOOTSTRAP_SERVICES, "finder")
_CANDIDATE_ROWS_SQL = """
    SELECT
        state_key,
        state_value->>'network' AS network,
        (state_value->>'failures')::int AS failures
    FROM service_state
    WHERE owner = 'validator'
      AND state_type = 'checkpoint'
    ORDER BY state_key
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


def _configure_finder_runtime(
    plan: RuntimeAddressPlan, *, source_url: str, cooldown: float
) -> None:
    config_path = plan.runtime_root / "config" / "services" / "finder.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    payload["interval"] = 3600.0
    payload["api"] = {
        "enabled": True,
        "cooldown": cooldown,
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


def _candidate_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _CANDIDATE_ROWS_SQL)


def _api_checkpoints(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _API_CHECKPOINT_SQL)


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


def _finder_log_contains(stack: ComposeStack, text: str) -> bool:
    return text in stack.run("logs", "--no-color", "finder", check=False).stdout


def _capture_finder_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    fixture: LocalHttpFixtureRuntime,
    name: str,
) -> None:
    bundle.capture_container_logs(
        f"{name}-finder", stack.run("logs", "--no-color", "finder").stdout
    )
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


@pytest.mark.timeout(900)
def test_finder_fetches_from_controlled_http_source_and_persists_candidates(tmp_path: Path) -> None:
    bundle = create_bundle(tmp_path, "finder-api-fetch")
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", "finder-api-fetch")
    prepare_runtime_compose_config(plan)
    configure_runtime_host_gateway(plan, "finder")

    fixture = LocalHttpFixtureRuntime(tmp_path / "http-fixture")
    fixture.set_json_response(
        "/sources.json",
        [
            "wss://relay.finder-one.example.com",
            "wss://relay.finder-one.example.com",
            "wss://relay.finder-two.example.com/path",
            "mailto:not-a-relay@example.com",
        ],
    )

    with fixture:
        source_url = fixture.docker_url("/sources.json")
        _configure_finder_runtime(plan, source_url=source_url, cooldown=3600.9)
        stack = create_stack(plan)
        record_runtime_plan(bundle, plan)

        try:
            stack.up(*FINDER_BOOTSTRAP_SERVICES)
            stack.wait_until_ready(FINDER_BOOTSTRAP_SERVICES)
            stack.up("finder", build=True)
            stack.wait_until_ready(("finder",), timeout=180.0)

            snapshot = _wait_until(
                lambda: {
                    "requests": len(fixture.requests(path="/sources.json")),
                    "candidates": _candidate_rows(plan),
                    "checkpoints": _api_checkpoints(plan),
                },
                is_ready=lambda current: (
                    current["requests"] == 1
                    and len(current["candidates"]) == 2
                    and len(current["checkpoints"]) == 1
                ),
                description="finder API fetch persistence",
            )
            _capture_finder_artifacts(bundle, stack, fixture=fixture, name="finder-api-fetch")
            bundle.capture_db_snapshot("finder-api-fetch", snapshot)
        finally:
            capture_stack_artifacts(bundle, stack, services=FINDER_ARTIFACT_SERVICES)
            stack.down()

    assert tuple(row["state_key"] for row in snapshot["candidates"]) == (
        "wss://relay.finder-one.example.com",
        "wss://relay.finder-two.example.com/path",
    )
    assert {row["network"] for row in snapshot["candidates"]} == {"clearnet"}
    assert {row["failures"] for row in snapshot["candidates"]} == {0}
    assert snapshot["checkpoints"][0]["state_key"] == source_url
    assert isinstance(snapshot["checkpoints"][0]["timestamp"], int)
    assert snapshot["checkpoints"][0]["timestamp"] > 0


@pytest.mark.timeout(900)
def test_finder_restart_respects_persisted_cooldown_and_skips_refetch(tmp_path: Path) -> None:
    bundle = create_bundle(tmp_path, "finder-api-restart")
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", "finder-api-restart")
    prepare_runtime_compose_config(plan)
    configure_runtime_host_gateway(plan, "finder")

    fixture = LocalHttpFixtureRuntime(tmp_path / "http-fixture")
    fixture.set_json_response(
        "/sources.json",
        [
            "wss://relay.restart-one.example.com",
            "wss://relay.restart-two.example.com",
        ],
    )

    with fixture:
        source_url = fixture.docker_url("/sources.json")
        _configure_finder_runtime(plan, source_url=source_url, cooldown=3600.9)
        stack = create_stack(plan)
        record_runtime_plan(bundle, plan)

        try:
            stack.up(*FINDER_BOOTSTRAP_SERVICES)
            stack.wait_until_ready(FINDER_BOOTSTRAP_SERVICES)
            stack.up("finder", build=True)
            stack.wait_until_ready(("finder",), timeout=180.0)

            first_snapshot = _wait_until(
                lambda: {
                    "requests": len(fixture.requests(path="/sources.json")),
                    "candidates": _candidate_rows(plan),
                    "checkpoints": _api_checkpoints(plan),
                },
                is_ready=lambda current: (
                    current["requests"] == 1
                    and len(current["candidates"]) == 2
                    and len(current["checkpoints"]) == 1
                ),
                description="initial finder API fetch before restart",
            )

            fixture.set_json_response(
                "/sources.json",
                [
                    "wss://relay.restart-one.example.com",
                    "wss://relay.restart-two.example.com",
                    "wss://relay.restart-three.example.com",
                ],
            )

            stack.run("stop", "finder")
            stack.wait_until_state("finder", state="exited", all_services=True, timeout=60.0)
            stack.run("rm", "-f", "finder")
            stack.up("finder")
            stack.wait_until_ready(("finder",), timeout=180.0)

            _wait_until(
                lambda: _finder_log_contains(stack, "api_completed"),
                is_ready=bool,
                description="finder restart cycle completion",
            )
            second_snapshot = {
                "requests": len(fixture.requests(path="/sources.json")),
                "candidates": _candidate_rows(plan),
                "checkpoints": _api_checkpoints(plan),
            }
            _capture_finder_artifacts(bundle, stack, fixture=fixture, name="finder-api-restart")
            bundle.capture_db_snapshot("finder-api-restart-first", first_snapshot)
            bundle.capture_db_snapshot("finder-api-restart-second", second_snapshot)
        finally:
            capture_stack_artifacts(bundle, stack, services=FINDER_ARTIFACT_SERVICES)
            stack.down()

    assert first_snapshot["requests"] == 1
    assert second_snapshot["requests"] == 1
    assert second_snapshot["candidates"] == first_snapshot["candidates"]
    assert second_snapshot["checkpoints"] == first_snapshot["checkpoints"]
