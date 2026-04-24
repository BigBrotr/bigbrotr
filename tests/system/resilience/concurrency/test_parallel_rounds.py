from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from tests.system.deployments.baseline import (
    ALL_SERVICES,
    CONTINUOUS_SERVICES,
    assert_expected_baseline,
    assert_runtime_resources_removed,
    capture_stack_artifacts,
    create_bundle,
    create_stack,
    record_runtime_plan,
)
from tests.system.deployments.runtime_overrides import (
    BOOTSTRAP_SERVICES,
    configure_runtime_relay_targets,
    prepare_runtime_compose_config,
    start_baseline_relay,
)
from tests.system.harness import LocalRelayRuntime, RuntimeAddressPlan, SystemArtifactBundle


if TYPE_CHECKING:
    from pathlib import Path

    from tests.system.harness import ComposeServiceStatus, ComposeStack


pytestmark = pytest.mark.system


@dataclass(slots=True)
class RunningProfileBaseline:
    bundle: SystemArtifactBundle
    plan: RuntimeAddressPlan
    stack: ComposeStack
    relay: LocalRelayRuntime
    ready: tuple[ComposeServiceStatus, ...]
    snapshot: dict[str, ComposeServiceStatus]


def _start_profile_baseline(
    tmp_path: Path,
    *,
    profile: str,
    run_name: str,
    slot: int,
) -> RunningProfileBaseline:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create(profile, tmp_path / "runtime", run_name, slot=slot)
    prepare_runtime_compose_config(plan)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    stack.up(*BOOTSTRAP_SERVICES, build=True)
    relay = start_baseline_relay(plan)
    configure_runtime_relay_targets(plan, relay)
    stack.up(build=True)
    ready = stack.wait_until_ready(CONTINUOUS_SERVICES)
    snapshot = {status.service: status for status in stack.ps(all_services=True)}
    capture_stack_artifacts(bundle, stack, services=ALL_SERVICES)

    return RunningProfileBaseline(
        bundle=bundle,
        plan=plan,
        stack=stack,
        relay=relay,
        ready=ready,
        snapshot=snapshot,
    )


def _stop_profile_baseline(runtime: RunningProfileBaseline) -> None:
    relay_container_name = runtime.relay.container_name
    runtime.relay.stop()
    runtime.stack.down(timeout=30)
    assert_runtime_resources_removed(runtime.plan, relay_container_name)


@pytest.mark.timeout(2400)
def test_built_in_profile_stacks_coexist_across_repeated_rounds_without_resource_drift(
    tmp_path: Path,
) -> None:
    round_pairs = ((82, 83), (84, 85), (86, 87))
    seen_project_names: set[str] = set()

    for round_index, (big_slot, lil_slot) in enumerate(round_pairs, start=1):
        running: list[RunningProfileBaseline] = []
        try:
            bigbrotr = _start_profile_baseline(
                tmp_path / f"round-{round_index}" / "bigbrotr",
                profile="bigbrotr",
                run_name=f"bigbrotr-overlap-round-{round_index}",
                slot=big_slot,
            )
            running.append(bigbrotr)

            lilbrotr = _start_profile_baseline(
                tmp_path / f"round-{round_index}" / "lilbrotr",
                profile="lilbrotr",
                run_name=f"lilbrotr-overlap-round-{round_index}",
                slot=lil_slot,
            )
            running.append(lilbrotr)

            bigbrotr_live = {
                status.service: status for status in bigbrotr.stack.ps(all_services=True)
            }
            lilbrotr_live = {
                status.service: status for status in lilbrotr.stack.ps(all_services=True)
            }

            assert_expected_baseline(bigbrotr.bundle, bigbrotr.ready, bigbrotr_live)
            assert_expected_baseline(lilbrotr.bundle, lilbrotr.ready, lilbrotr_live)

            assert bigbrotr.plan.project_name != lilbrotr.plan.project_name
            assert bigbrotr.plan.data_network_name != lilbrotr.plan.data_network_name
            assert bigbrotr.plan.monitoring_network_name != lilbrotr.plan.monitoring_network_name
            assert bigbrotr.plan.prometheus_volume_name != lilbrotr.plan.prometheus_volume_name
            assert bigbrotr.plan.alertmanager_volume_name != lilbrotr.plan.alertmanager_volume_name
            assert bigbrotr.plan.grafana_volume_name != lilbrotr.plan.grafana_volume_name
            assert bigbrotr.plan.ports.db != lilbrotr.plan.ports.db
            assert bigbrotr.plan.ports.prometheus != lilbrotr.plan.ports.prometheus
            assert bigbrotr.plan.ports.grafana != lilbrotr.plan.ports.grafana
            assert tuple(status.service for status in bigbrotr.ready) == CONTINUOUS_SERVICES
            assert tuple(status.service for status in lilbrotr.ready) == CONTINUOUS_SERVICES
            assert all(
                status.is_ready for status in bigbrotr_live.values() if status.service != "seeder"
            )
            assert all(
                status.is_ready for status in lilbrotr_live.values() if status.service != "seeder"
            )

            seen_project_names.add(bigbrotr.plan.project_name)
            seen_project_names.add(lilbrotr.plan.project_name)
        finally:
            for runtime in reversed(running):
                _stop_profile_baseline(runtime)

    assert len(seen_project_names) == len(round_pairs) * 2
