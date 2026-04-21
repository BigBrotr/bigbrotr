from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.system.deployments.runtime_overrides import (
    BOOTSTRAP_SERVICES,
    configure_runtime_relay_targets,
    prepare_runtime_compose_config,
    start_baseline_relay,
)
from tests.system.harness import ComposeStack, RuntimeAddressPlan, SystemArtifactBundle
from tests.system.harness.compose import deployment_dir


if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.system

ALL_SERVICES = (
    "postgres",
    "pgbouncer",
    "tor",
    "seeder",
    "finder",
    "validator",
    "monitor",
    "synchronizer",
    "refresher",
    "ranker",
    "api",
    "dvm",
    "assertor",
    "postgres-exporter",
    "prometheus",
    "alertmanager",
    "grafana",
)
CONTINUOUS_SERVICES = tuple(service for service in ALL_SERVICES if service != "seeder")
PRODUCT_SERVICES = (
    "seeder",
    "finder",
    "validator",
    "monitor",
    "synchronizer",
    "refresher",
    "ranker",
    "api",
    "dvm",
    "assertor",
)


def _create_bundle(tmp_path: Path, run_name: str) -> SystemArtifactBundle:
    return SystemArtifactBundle.create(tmp_path / "artifacts", run_name)


def _capture_stack_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    services: tuple[str, ...],
) -> None:
    bundle.write_text_artifact(
        category="containers",
        subdir="containers",
        name="compose-ps",
        contents=stack.run("ps", "--all", "--format", "json").stdout,
        suffix=".jsonl",
    )
    for service in services:
        bundle.capture_container_logs(
            service,
            stack.run("logs", "--no-color", "--tail", "200", service).stdout,
        )


@pytest.mark.timeout(900)
def test_lilbrotr_stack_reaches_expected_baseline(tmp_path: Path) -> None:
    bundle = _create_bundle(tmp_path, "lilbrotr-stack-baseline")
    plan = RuntimeAddressPlan.create("lilbrotr", tmp_path / "runtime", "lilbrotr-stack-baseline")
    prepare_runtime_compose_config(plan)
    stack = ComposeStack(
        profile=plan.profile,
        project_name=plan.project_name,
        project_dir=deployment_dir(plan.profile),
        env_file=plan.env_file,
        compose_files=(plan.compose_file,),
        ready_timeout=420.0,
        poll_interval=2.0,
    )
    bundle.write_json_artifact(
        category="containers",
        subdir="containers",
        name="runtime-plan",
        payload={
            "project_name": plan.project_name,
            "compose_file": plan.compose_file,
            "env_file": plan.env_file,
        },
    )

    relay = None
    try:
        stack.up(*BOOTSTRAP_SERVICES, build=True)
        relay = start_baseline_relay(plan)
        configure_runtime_relay_targets(plan, relay)
        stack.up(build=True)
        ready = stack.wait_until_ready(CONTINUOUS_SERVICES)
        snapshot = {status.service: status for status in stack.ps(all_services=True)}
        _capture_stack_artifacts(bundle, stack, services=ALL_SERVICES)
    finally:
        if relay is not None:
            relay.stop()
        stack.down()

    assert tuple(status.service for status in ready) == CONTINUOUS_SERVICES
    assert len(snapshot) == len(ALL_SERVICES)
    assert set(snapshot) == set(ALL_SERVICES)
    assert all(status.is_ready for status in ready)
    assert snapshot["seeder"].state == "exited"
    assert snapshot["seeder"].exit_code == 0

    for service_name in PRODUCT_SERVICES:
        log_path = bundle.root / "containers" / f"{service_name}.log"
        log_text = log_path.read_text()
        assert "config_not_found" not in log_text
        assert "DB_ADMIN_PASSWORD environment variable not set" not in log_text
        assert "permission denied for table service_state" not in log_text
        assert "UnexpectedUniFFICallbackError" not in log_text
        assert "NoneType can't be used in 'await' expression" not in log_text
        assert "could not connect to any publishing relay" not in log_text
        assert "could not connect to any relay" not in log_text

    assert bundle.manifest_path.is_file()
