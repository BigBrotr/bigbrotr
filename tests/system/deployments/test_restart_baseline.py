from __future__ import annotations

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
from tests.system.harness import RuntimeAddressPlan


if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.system


def _run_restart_cycle(
    plan: RuntimeAddressPlan,
    bundle_root: Path,
    *,
    cycle_label: str,
) -> None:
    bundle = create_bundle(bundle_root, cycle_label)
    prepare_runtime_compose_config(plan)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    relay = None
    relay_container_name = ""
    ready = ()
    snapshot = {}
    try:
        stack.up(*BOOTSTRAP_SERVICES, build=True)
        relay = start_baseline_relay(plan)
        relay_container_name = relay.container_name
        configure_runtime_relay_targets(plan, relay)
        stack.up(build=True)
        ready = stack.wait_until_ready(CONTINUOUS_SERVICES)
        snapshot = {status.service: status for status in stack.ps(all_services=True)}
        capture_stack_artifacts(bundle, stack, services=ALL_SERVICES)
    finally:
        if relay is not None:
            relay.stop()
        stack.down()

    assert relay_container_name
    assert_expected_baseline(bundle, ready, snapshot)
    assert_runtime_resources_removed(plan, relay_container_name)


@pytest.mark.parametrize("profile", ["bigbrotr", "lilbrotr"])
@pytest.mark.timeout(1500)
def test_profile_stack_restarts_cleanly_after_full_teardown(tmp_path: Path, profile: str) -> None:
    plan = RuntimeAddressPlan.create(profile, tmp_path / "runtime", f"{profile}-restart-baseline")
    bundle_root = tmp_path / "artifacts"

    _run_restart_cycle(plan, bundle_root, cycle_label=f"{profile}-restart-cycle-1")
    _run_restart_cycle(plan, bundle_root, cycle_label=f"{profile}-restart-cycle-2")
