from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from tests.system.deployments.baseline import (
    capture_stack_artifacts,
    create_bundle,
    create_stack,
    record_runtime_plan,
)
from tests.system.deployments.runtime_overrides import prepare_runtime_compose_config
from tests.system.harness import RuntimeAddressPlan, fetch_runtime_rows, fetch_runtime_value


if TYPE_CHECKING:
    from pathlib import Path

    from tests.system.harness import ComposeServiceStatus, SystemArtifactBundle


pytestmark = pytest.mark.system


SEEDER_BOOTSTRAP_SERVICES = ("postgres", "pgbouncer")
SEEDER_ARTIFACT_SERVICES = (*SEEDER_BOOTSTRAP_SERVICES, "seeder")
_CANDIDATE_ROWS_SQL = """
    SELECT
        owner,
        state_type,
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


def _configure_seed_runtime(
    plan: RuntimeAddressPlan,
    *,
    file_path: str,
    to_validate: bool,
    seed_lines: tuple[str, ...] | None,
) -> None:
    config_path = plan.runtime_root / "config" / "services" / "seeder.yaml"
    config_payload = yaml.safe_load(config_path.read_text())
    assert isinstance(config_payload, dict)

    seed_payload = config_payload.setdefault("seed", {})
    assert isinstance(seed_payload, dict)
    seed_payload["file_path"] = file_path
    seed_payload["to_validate"] = to_validate
    config_path.write_text(yaml.safe_dump(config_payload, sort_keys=False))

    if seed_lines is None:
        return

    seed_path = plan.runtime_root / file_path
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_text("\n".join(seed_lines) + "\n")


def _run_seeder_once(
    *,
    label: str,
    stack,
    bundle: SystemArtifactBundle,
    build: bool = False,
    force_recreate: bool = False,
) -> ComposeServiceStatus:
    stack.up("seeder", build=build, force_recreate=force_recreate)
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


@pytest.mark.timeout(900)
def test_seeder_candidate_mode_persists_unique_candidates_and_exits_once(tmp_path: Path) -> None:
    bundle = create_bundle(tmp_path, "seeder-candidate-mode")
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", "seeder-candidate-mode")
    prepare_runtime_compose_config(plan)
    _configure_seed_runtime(
        plan,
        file_path="static/seed_relays.txt",
        to_validate=True,
        seed_lines=(
            "# seeded by system test",
            "wss://relay.one.example.com",
            "wss://relay.one.example.com",
            "wss://relay.two.example.com/path",
            "https://not-a-relay.example.com",
        ),
    )
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    try:
        stack.up(*SEEDER_BOOTSTRAP_SERVICES)
        stack.wait_until_ready(SEEDER_BOOTSTRAP_SERVICES)

        first_status = _run_seeder_once(
            label="candidate-first", stack=stack, bundle=bundle, build=True
        )
        first_rows = _candidate_rows(plan)
        bundle.capture_db_snapshot("candidate-first", first_rows)
        relay_count = fetch_runtime_value(plan, "SELECT COUNT(*) FROM relay")

        second_status = _run_seeder_once(
            label="candidate-second",
            stack=stack,
            bundle=bundle,
            force_recreate=True,
        )
        second_rows = _candidate_rows(plan)
        bundle.capture_db_snapshot("candidate-second", second_rows)
        seeder_logs = stack.run("logs", "--no-color", "seeder").stdout
        bundle.capture_container_logs("candidate-final-seeder", seeder_logs)
    finally:
        capture_stack_artifacts(bundle, stack, services=SEEDER_ARTIFACT_SERVICES)
        stack.down()

    assert first_status.state == "exited"
    assert first_status.exit_code == 0
    assert second_status.state == "exited"
    assert second_status.exit_code == 0
    assert relay_count == 0
    assert tuple(row["state_key"] for row in first_rows) == (
        "wss://relay.one.example.com",
        "wss://relay.two.example.com/path",
    )
    assert {row["owner"] for row in first_rows} == {"validator"}
    assert {row["state_type"] for row in first_rows} == {"checkpoint"}
    assert {row["network"] for row in first_rows} == {"clearnet"}
    assert {row["failures"] for row in first_rows} == {0}
    assert all(isinstance(row["timestamp"], int) and row["timestamp"] > 0 for row in first_rows)
    assert second_rows == first_rows
    assert "relay_parse_failed:" in seeder_logs


@pytest.mark.timeout(900)
def test_seeder_direct_mode_inserts_relays_without_duplicate_drift(tmp_path: Path) -> None:
    bundle = create_bundle(tmp_path, "seeder-direct-mode")
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", "seeder-direct-mode")
    prepare_runtime_compose_config(plan)
    _configure_seed_runtime(
        plan,
        file_path="static/seed_relays.txt",
        to_validate=False,
        seed_lines=(
            "wss://relay.direct-one.example.com",
            "wss://relay.direct-two.example.com/ws",
            "wss://relay.direct-one.example.com",
            "mailto:not-a-relay@example.com",
        ),
    )
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    try:
        stack.up(*SEEDER_BOOTSTRAP_SERVICES)
        stack.wait_until_ready(SEEDER_BOOTSTRAP_SERVICES)

        _run_seeder_once(label="direct-first", stack=stack, bundle=bundle, build=True)
        first_rows = _relay_rows(plan)
        bundle.capture_db_snapshot("direct-first", first_rows)
        candidate_count = fetch_runtime_value(
            plan,
            "SELECT COUNT(*) FROM service_state WHERE owner = 'validator' AND state_type = 'checkpoint'",
        )

        _run_seeder_once(label="direct-second", stack=stack, bundle=bundle, force_recreate=True)
        second_rows = _relay_rows(plan)
        bundle.capture_db_snapshot("direct-second", second_rows)
        seeder_logs = stack.run("logs", "--no-color", "seeder").stdout
        bundle.capture_container_logs("direct-final-seeder", seeder_logs)
    finally:
        capture_stack_artifacts(bundle, stack, services=SEEDER_ARTIFACT_SERVICES)
        stack.down()

    assert candidate_count == 0
    assert tuple(row["url"] for row in first_rows) == (
        "wss://relay.direct-one.example.com",
        "wss://relay.direct-two.example.com/ws",
    )
    assert {row["network"] for row in first_rows} == {"clearnet"}
    assert all(isinstance(row["stored_at"], int) and row["stored_at"] > 0 for row in first_rows)
    assert second_rows == first_rows
    assert "relay_parse_failed:" in seeder_logs


@pytest.mark.timeout(900)
def test_seeder_missing_source_exits_cleanly_without_persistence(tmp_path: Path) -> None:
    bundle = create_bundle(tmp_path, "seeder-missing-source")
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", "seeder-missing-source")
    prepare_runtime_compose_config(plan)
    _configure_seed_runtime(
        plan,
        file_path="static/does-not-exist.txt",
        to_validate=True,
        seed_lines=None,
    )
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    try:
        stack.up(*SEEDER_BOOTSTRAP_SERVICES)
        stack.wait_until_ready(SEEDER_BOOTSTRAP_SERVICES)

        status = _run_seeder_once(label="missing-source", stack=stack, bundle=bundle, build=True)
        relay_count = fetch_runtime_value(plan, "SELECT COUNT(*) FROM relay")
        candidate_count = fetch_runtime_value(
            plan,
            "SELECT COUNT(*) FROM service_state WHERE owner = 'validator' AND state_type = 'checkpoint'",
        )
        bundle.capture_db_snapshot(
            "missing-source-counts",
            {
                "relay_count": relay_count,
                "candidate_count": candidate_count,
            },
        )
        seeder_logs = stack.run("logs", "--no-color", "seeder").stdout
        bundle.capture_container_logs("missing-source-final-seeder", seeder_logs)
    finally:
        capture_stack_artifacts(bundle, stack, services=SEEDER_ARTIFACT_SERVICES)
        stack.down()

    assert status.state == "exited"
    assert status.exit_code == 0
    assert relay_count == 0
    assert candidate_count == 0
    assert "seed_file_read_error:" in seeder_logs
    assert "no_valid_relays" in seeder_logs
