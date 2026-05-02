from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

from tests.system.harness import (
    ComposeStack,
    RuntimeAddressPlan,
    SystemArtifactBundle,
    docker_container_exists,
    docker_network_exists,
)
from tests.system.harness.compose import deployment_dir


if TYPE_CHECKING:
    from pathlib import Path

    from tests.system.harness import ComposeServiceStatus, LocalRelayRuntime


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


def create_bundle(tmp_path: Path, run_name: str) -> SystemArtifactBundle:
    return SystemArtifactBundle.create(tmp_path / "artifacts", run_name)


def create_stack(plan: RuntimeAddressPlan) -> ComposeStack:
    return ComposeStack(
        profile=plan.profile,
        project_name=plan.project_name,
        project_dir=deployment_dir(plan.profile),
        env_file=plan.env_file,
        compose_files=(plan.compose_file,),
        ready_timeout=420.0,
        poll_interval=2.0,
    )


def record_runtime_plan(bundle: SystemArtifactBundle, plan: RuntimeAddressPlan) -> None:
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


def capture_stack_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    services: tuple[str, ...] = ALL_SERVICES,
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


def teardown_stack_runtime(
    bundle: SystemArtifactBundle | None,
    stack: ComposeStack | None,
    *,
    relay: LocalRelayRuntime | None = None,
    services: tuple[str, ...] = ALL_SERVICES,
    down_timeout: int | None = None,
) -> None:
    cleanup_errors: list[tuple[str, Exception]] = []
    active_exception = sys.exc_info()[1]

    if bundle is not None and stack is not None:
        try:
            capture_stack_artifacts(bundle, stack, services=services)
        except Exception as exc:  # pragma: no cover - exercised via helper unit tests
            cleanup_errors.append(("capture_stack_artifacts", exc))

    if relay is not None:
        try:
            relay.stop()
        except Exception as exc:  # pragma: no cover - exercised via helper unit tests
            cleanup_errors.append(("relay.stop", exc))

    if stack is not None:
        try:
            stack.down(timeout=down_timeout)
        except Exception as exc:  # pragma: no cover - exercised via helper unit tests
            cleanup_errors.append(("stack.down", exc))

    if not cleanup_errors:
        return

    details = "\n".join(f"- {step}: {type(exc).__name__}: {exc}" for step, exc in cleanup_errors)
    message = f"System runtime cleanup failed:\n{details}"
    if active_exception is not None:
        active_exception.add_note(message)
        return
    raise RuntimeError(message) from cleanup_errors[0][1]


def assert_expected_baseline(
    bundle: SystemArtifactBundle,
    ready: tuple[ComposeServiceStatus, ...],
    snapshot: dict[str, ComposeServiceStatus],
) -> None:
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


def all_container_names(plan: RuntimeAddressPlan) -> tuple[str, ...]:
    return tuple(f"{plan.project_name}-{service}" for service in ALL_SERVICES)


def assert_runtime_resources_removed(
    plan: RuntimeAddressPlan,
    relay_container_name: str,
    *,
    timeout: float = 15.0,
    poll_interval: float = 0.5,
) -> None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if (
            not docker_network_exists(plan.data_network_name)
            and not docker_network_exists(plan.monitoring_network_name)
            and not docker_container_exists(relay_container_name)
            and all(
                not docker_container_exists(container_name)
                for container_name in all_container_names(plan)
            )
        ):
            return
        time.sleep(poll_interval)

    assert not docker_network_exists(plan.data_network_name)
    assert not docker_network_exists(plan.monitoring_network_name)
    assert not docker_container_exists(relay_container_name)
    for container_name in all_container_names(plan):
        assert not docker_container_exists(container_name)
